"""Read projections of saved proposals and execution ledgers; no business writes."""
from copy import deepcopy
from decimal import Decimal

from ..errors import BusinessConflict
from .domain import number


ACTION_LABELS = {"keep": "保留原计划", "transfer": "跨店调拨", "promotion": "促销",
                 "return": "退供", "procurement": "采购调整", "combination": "组合处置"}
EVENT_LABELS = {"transfer_shipped": "调拨出库", "transfer_received": "调拨签收", "supplier_confirmed": "供应商确认",
                "return_shipped": "退供出库", "supplier_accepted": "退供验收", "exchange_received": "换货签收",
                "credit_issued": "抵款额度确认", "credit_applied": "抵款生效", "order_confirmed": "采购订单确认",
                "purchase_received": "采购收货", "purchase_cancelled": "采购取消确认", "promotion_price_effective": "促销价格生效",
                "promotion_ended": "促销结束", "execution_exception": "执行异常"}


def metadata(context):
    return {"is_demo": context["is_demo"], "source": "saved_business_records",
            "as_of_date": context["as_of"][:10], "as_of": context["as_of"],
            "data_version": context["data_version"], "fact_version": context["fact_version"],
            "source_refs": deepcopy(context["source_refs"]), "missing_fields": deepcopy(context["missing_fields"])}


def proposal_view(row, version, payload, context):
    candidate = payload["candidate"]
    action_type = candidate.get("action_type", "combination")
    plan = candidate["calculation"]["execution_plan"]
    # Quantities and unit costs are the saved, server-validated action snapshot.
    costs = [None if action.get("quantity") is None or action.get("unit_cost") is None
             else number(action["quantity"]) * number(action["unit_cost"])
             for action in plan["actions"]]
    inventory_cost = sum(costs, Decimal(0)) if costs and all(c is not None for c in costs) else None
    saved_context = deepcopy(payload["context"])
    stale = any(saved_context[key] != context[key] for key in ("fact_version", "data_version", "as_of"))
    return {"proposal_id": row["id"], "proposal_version": version["version"],
            "case_id": row["id"], "status": row["status"] if version["version"] == row["current_version"] else version["status"],
            "version_status": version["status"], "invalid_reason": version["invalid_reason"],
            "context": saved_context, "candidate_id": payload["candidate_id"], "action_type": action_type,
            "title": payload.get("title") or ACTION_LABELS[action_type],
            "risk_keys": deepcopy(payload.get("risk_keys", payload["comparison_request"].get("risk_keys", [payload["risk_key"]]))),
            "action_lines": deepcopy(payload["action_lines"]), "created_at": row["created_at"],
            "updated_at": version["created_at"], "missing_fields": deepcopy(candidate["missing_fields"]),
            "comparison_id": payload["comparison_id"], "baseline_id": payload["baseline_id"],
            "candidate": deepcopy(candidate), "calculation": deepcopy(candidate["calculation"]),
            "comparison_request": deepcopy(payload["comparison_request"]),
            "inventory_cost_cny": inventory_cost, "requires_recalculation": stale,
            "created_by": payload["created_by"], "is_demo": saved_context["is_demo"], "external_write": False}


def pending_summary(proposals):
    costs = [p["inventory_cost_cny"] for p in proposals]
    known = sum((amount for amount in costs if amount is not None), Decimal(0))
    missing = sum(amount is None for amount in costs)
    return {"count": len(proposals), "amount": None if missing else known,
            "known_amount": known if any(amount is not None for amount in costs) or not costs else None,
            "missing_count": missing}


def select_tasks(tasks, request):
    selected = [task for task in tasks if
                (not request.get("task_id") or task["task_id"] == request["task_id"]) and
                (not request.get("proposal_id") or task["proposal_id"] == request["proposal_id"])]
    if (request.get("task_id") or request.get("proposal_id")) and not selected:
        raise ValueError("Unknown task or proposal in this context")
    for field, actual in (("task_version", "version"), ("proposal_version", "proposal_version")):
        if field in request:
            if not request.get("task_id") and (field == "task_version" or not request.get("proposal_id")):
                raise ValueError(f"{field} requires the corresponding task or proposal selector")
            if type(request[field]) is not int or request[field] < 1:
                raise ValueError(f"{field} must be a positive integer")
            if any(task[actual] != request[field] for task in selected):
                raise BusinessConflict("version_conflict", "请求的任务或方案版本已变化")
    return selected


def scoped_cash(state, task_ids):
    """Expose only the selected task's part of a shared cash event."""
    result = {}
    for row in state["cash_events"]:
        own = row.get("task_id") in task_ids
        allocations = [item for item in state["cash_allocations"]
                       if item["cash_event_id"] == row["cash_event_id"] and item.get("task_id") in task_ids]
        if own or allocations:
            amount = number(row["amount"]) if own else sum((number(a["allocated_amount"]) for a in allocations), Decimal(0))
            result[row["cash_event_id"]] = {**deepcopy(row), "amount": amount,
                "amount_scope": "task_attributed" if own else "allocated_to_selected_tasks",
                "allocation_ids": [a["allocation_id"] for a in allocations]}
    return result


def receipt_timeline(state, entries, task_ids=None):
    cash = {c["cash_event_id"]: c for c in state["cash_events"]} if task_ids is None else scoped_cash(state, task_ids)
    rows = []
    for entry, record in entries:
        if entry["kind"] == "cash":
            if record["cash_event_id"] not in cash:
                continue
            record = cash[record["cash_event_id"]]
        elif task_ids is not None and record.get("task_id") not in task_ids:
            continue
        rows.append({"event_id": entry["event_key"], "kind": entry["kind"], "record": deepcopy(record),
                     "occurred_at": record.get("occurred_at", record.get("date", record.get("known_at"))),
                     "known_at": record.get("known_at"), "event_type": record.get("event_type", entry["kind"]),
                     "task_id": record.get("task_id"), "quantity": record.get("quantity", record.get("sold_qty")),
                     "base_unit": record.get("base_unit"), "amount": record.get("amount", record.get("sales_amount", record.get("allocated_amount"))),
                     "receipt_ref": record.get("receipt_ref"), "source": record.get("source", "execution_receipts"),
                     "label": EVENT_LABELS.get(record.get("event_type"), {"sale": "销售记录", "cash_allocation": "现金核销",
                         "cash": "现金到账" if record.get("direction") == "in" else "实际付款", "return_confirmation": "退供条件确认"}.get(entry["kind"], "业务回执")),
                     "is_actual": True, "is_demo": True, "external_write": False})
    return sorted(rows, key=lambda row: (row["occurred_at"] or "", row["known_at"] or "", row["event_id"]))
