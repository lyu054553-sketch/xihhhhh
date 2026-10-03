"""Inventory, receipts and cash accounting for a versioned retail workspace.

All transitions operate on one aggregate inside Store.transaction(). Forecasts
never enter these ledgers: only validated, attributed business receipts do.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
import hashlib
import json
import uuid

from backend.errors import BusinessConflict


def number(value, field="quantity", *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} requires a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid {field}") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"Invalid {field}")
    return result


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Clock must be an ISO timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Clock must include a timezone")
    return parsed.astimezone(timezone(timedelta(hours=8)))


def identifier(prefix):
    return f"{prefix}-{uuid.uuid4().hex}"


def resource(row, state="on_hand"):
    values = [row.get(key) for key in ("store_id", "sku_id", "lot_id")]
    if any(not isinstance(value, str) or not value or "|" in value for value in values):
        raise ValueError("Stock resource requires store, SKU and lot IDs")
    return "|".join(values) + "|" + state


def _fingerprint(row):
    def normalized(value):
        if isinstance(value, (Decimal, float, int)) and not isinstance(value, bool):
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValueError("Event contains a nonfinite number")
            return {"number": str(value.normalize())}
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(normalized(row), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _receipt(ledger, id_field):
    """A receipt is atomic in memory as well as in the persistence transaction."""
    def decorate(function):
        @wraps(function)
        def apply(state, row):
            event_id = row.get(id_field)
            if not isinstance(event_id, str) or not event_id:
                raise ValueError(f"Event requires {id_field}")
            key, fingerprint = f"{ledger}:{event_id}", _fingerprint(row)
            previous = state["event_fingerprints"].get(key)
            if previous:
                if previous != fingerprint:
                    raise BusinessConflict("event_identity_conflict", "相同事件编号对应不同内容，不能覆盖已有记录")
                return False
            updated = deepcopy(state)
            function(updated, deepcopy(row))
            updated["event_fingerprints"][key] = fingerprint
            state.clear()
            state.update(updated)
            return True
        return apply
    return decorate


def initial_execution(facts):
    positions = {}
    for row in facts["tables"]["inventory"]:
        kind = row["stock_state"]
        key = resource(row, kind)
        if key in positions:
            existing = positions[key]
            if kind != "in_transit" or number(existing["unit_cost"]) != number(row["unit_cost"]) or existing["sellable_until"] != row["sellable_until"]:
                raise ValueError(f"Conflicting inventory resource: {key}")
            existing["quantity"] += number(row["quantity"])
            if row.get("shipment_line_id"):
                existing["shipments"][row["shipment_line_id"]] = number(row["quantity"])
            continue
        positions[key] = {
            "store_id": row["store_id"], "sku_id": row["sku_id"], "lot_id": row["lot_id"],
            "stock_state": kind, "quantity": number(row["quantity"]),
            "blocked_qty": number(row["blocked_qty"]),
            "external_reserved_qty": number(row["reserved_qty"]),
            "unit_cost": number(row["unit_cost"], "unit_cost"), "sellable_until": row["sellable_until"],
            "shipment_line_id": row.get("shipment_line_id"),
            "shipments": {row["shipment_line_id"]: number(row["quantity"])} if kind == "in_transit" and row.get("shipment_line_id") else {},
        }
    return {"positions": positions, "reservations": [], "tasks": [], "actions": [],
            "receipts": [], "sales": [], "cash_events": [], "cash_allocations": [],
            "return_confirmations": [], "credits": [], "payables": deepcopy(facts["tables"].get("payables", [])),
            "event_fingerprints": {}, "clock_at": facts["clock_at"],
            "account_ids": [row["account_id"] for row in facts["tables"].get("accounts", [])],
            "lots": deepcopy(facts["tables"]["lots"])}


def available(state, row):
    key = resource(row)
    position = state["positions"].get(key)
    if position is None:
        raise ValueError(f"Unknown stock resource: {key}")
    held = sum((number(item["quantity"]) for item in state["reservations"] if item["resource"] == key), Decimal(0))
    return number(position["quantity"]) - number(position["blocked_qty"]) - number(position["external_reserved_qty"]) - held


def arrange_execution(state, proposal, *, actor_id, owner_id, due_at):
    candidate = proposal["candidate"]
    if candidate["feasibility"] != "feasible" or candidate["blocking_reasons"] or candidate["missing_fields"]:
        raise BusinessConflict("infeasible_proposal", "方案存在未满足或未确认的执行条件")
    if candidate["type"] not in {"transfer", "promotion", "return", "purchase"}:
        raise ValueError("Only one executable action creates a task; split combinations into their children")
    if len(candidate["actions"]) != 1 or candidate["actions"][0]["type"] != candidate["type"]:
        raise ValueError("Execution requires one matching calculated action")
    if any(not isinstance(value, str) or not value.strip() for value in (actor_id, owner_id)):
        raise ValueError("Confirmation requires an actor and an execution owner")
    number(candidate["allocated_qty"], positive=candidate["type"] != "purchase")
    if any(t["proposal_id"] == proposal["id"] and t["plan"]["strategy_id"] == candidate["strategy_id"] for t in state["tasks"]):
        raise BusinessConflict("already_confirmed", "该方案已经安排执行")
    timestamp(due_at)
    allocations = candidate["allocations"]
    requested = {}
    for row in allocations:
        key = resource(row)
        requested[key] = requested.get(key, Decimal(0)) + number(row["quantity"], positive=True)
    for key, quantity in requested.items():
        row = next(a for a in allocations if resource(a) == key)
        if quantity > available(state, row):
            raise BusinessConflict("inventory_conflict", "库存已变化或被其他方案占用")
    if candidate["type"] != "purchase" and not requested:
        raise ValueError("Inventory actions require approved stock allocations")
    if proposal.get("evaluation_end"):
        date.fromisoformat(proposal["evaluation_end"])
    task = {
        "id": identifier("task"), "proposal_id": proposal["id"], "proposal_version": proposal["version"],
        "type": candidate["type"], "plan": deepcopy(candidate), "approved_by": actor_id,
        "owner_id": owner_id, "due_at": due_at, "version": 1, "cancelled": False,
        "evaluation_end": proposal.get("evaluation_end"),
        "exception_flags": [], "progress": {}, "execution_status": "pending", "accounting_status": "pending",
    }
    for key, quantity in requested.items():
        if quantity:
            state["reservations"].append({"task_id": task["id"], "resource": key, "quantity": quantity})
    state["tasks"].append(task)
    proposal["status"] = "confirmed"
    proposal["approved_by"] = actor_id
    return task


def _task(state, task_id, *, new_action=False):
    if task_id is None:
        return None
    for task in state["tasks"]:
        if task["id"] == task_id:
            if new_action and (task["cancelled"] or "replan_required" in task["exception_flags"]):
                raise BusinessConflict("replan_required", "任务已撤销或事实已变化，需要先确认新的业务动作")
            return task
    raise ValueError("Unknown execution task")


def _consume_reservation(state, task, row, quantity):
    key = resource(row)
    remaining = quantity
    for item in state["reservations"]:
        if item["task_id"] == task["id"] and item["resource"] == key:
            consumed = min(number(item["quantity"]), remaining)
            item["quantity"] = number(item["quantity"]) - consumed
            remaining -= consumed
    if remaining:
        raise BusinessConflict("outside_approved_stock", "回执数量超出方案库存预占")


def _move(state, row, quantity, *, from_state=None, to_state=None, to_store_id=None):
    template = dict(row)
    if from_state:
        key = resource(row, from_state)
        current = state["positions"].get(key)
        if current is None or number(current["quantity"]) < quantity:
            raise BusinessConflict("insufficient_inventory", "回执不能产生负库存")
        current["quantity"] = number(current["quantity"]) - quantity
        if from_state == "in_transit" and row.get("shipment_line_id"):
            shipment = row["shipment_line_id"]
            remaining = number(current.get("shipments", {}).get(shipment, 0)) - quantity
            if remaining < 0:
                raise BusinessConflict("receipt_exceeds_plan", "收货超过对应在途明细")
            current["shipments"][shipment] = remaining
        template = dict(current)
    if to_state:
        if from_state == "on_hand" and to_state == "in_transit":
            # A later transfer must not reuse an already-received PO shipment ID.
            template["shipment_line_id"] = row.get("shipment_line_id")
        template["store_id"] = to_store_id or row["store_id"]
        key = resource(template, to_state)
        if key not in state["positions"]:
            state["positions"][key] = {
                "store_id": template["store_id"], "sku_id": template["sku_id"], "lot_id": template["lot_id"],
                "stock_state": to_state, "quantity": Decimal(0),
                "blocked_qty": Decimal(0), "external_reserved_qty": Decimal(0),
                "unit_cost": number(template["unit_cost"], "unit_cost"),
                "sellable_until": template.get("sellable_until"), "shipment_line_id": template.get("shipment_line_id"),
            }
        target = state["positions"][key]
        if number(target["unit_cost"]) != number(template["unit_cost"]):
            raise BusinessConflict("lot_cost_changed", "同一批次入库成本不一致")
        target["quantity"] = number(target["quantity"]) + quantity


def _action(task, kind=None):
    action = task["plan"]["actions"][0]
    if kind is not None and action["type"] != kind:
        raise ValueError("Receipt action type differs from its confirmed task")
    return action


def _increment(task, name, quantity, maximum=None):
    value = number(task["progress"].get(name, 0)) + quantity
    if maximum is not None and value > number(maximum):
        raise BusinessConflict("receipt_exceeds_plan", "回执累计数量超出确认方案或前序回执")
    task["progress"][name] = value


def _check_resource(task, row, *, destination=False):
    allocations = task["plan"].get("allocations", [])
    if not any(a["sku_id"] == row.get("sku_id") and a["lot_id"] == row.get("lot_id")
               and (destination or a["store_id"] == row.get("store_id")) for a in allocations):
        raise BusinessConflict("receipt_scope_mismatch", "回执商品、批次或门店不属于已确认方案")
    if destination:
        action = _action(task, "transfer")
        target = action["target_store_id"]
        if target != row.get("store_id"):
            raise BusinessConflict("receipt_scope_mismatch", "接收门店与已确认方案不一致")


@_receipt("return_confirmations", "return_id")
def apply_return_confirmation(state, row):
    task = _task(state, row.get("task_id"))
    if task is None or task["type"] != "return":
        raise ValueError("Supplier confirmation requires a return task")
    action = _action(task)
    if any(row.get(k) is not None and row[k] != action.get(k) for k in ("supplier_id", "store_id")):
        raise BusinessConflict("supplier_terms_changed", "供应商确认不属于批准的供应商或门店")
    if any(item["task_id"] == task["id"] for item in state["return_confirmations"]):
        raise BusinessConflict("return_confirmation_changed", "供应商确认已保存，变更需要重新确认方案")
    quantity, planned = number(row["accepted_qty"], positive=True), number(action["quantity"], positive=True)
    if action["settlement_mode"] in {"exchange", "payable_credit"} and quantity != planned:
        raise BusinessConflict("supplier_terms_changed", "换货或抵款接受数量变化，需要重新计算结算条件")
    if (row["accepted_mode"] != action["settlement_mode"] or quantity > planned or
            row["sku_id"] != action["sku_id"] or row["lot_id"] != action["lot_id"] or row["term_id"] != action["term_id"]):
        raise BusinessConflict("supplier_terms_changed", "供应商确认与批准条件不同")
    if number(row["accepted_unit_price"]) * planned != number(action["expected_settlement_amount"]):
        raise BusinessConflict("supplier_terms_changed", "供应商结算单价与批准条件不同")
    if number(row["return_fee"]) != number(action["freight_fee"]) + number(action["restocking_fee"]):
        raise BusinessConflict("supplier_terms_changed", "供应商退货费用与批准条件不同")
    if action["settlement_mode"] == "exchange":
        for key in ("replacement_sku_id", "replacement_lot_id", "replacement_qty", "replacement_unit_cost"):
            if row.get(key) != action.get(key):
                raise BusinessConflict("replacement_mismatch", "换货明细与批准条件不同")
    elif action["settlement_mode"] == "payable_credit":
        if row["payable_id"] != action["payable_id"] or number(row["credit_amount"]) != number(action["expected_settlement_amount"]):
            raise BusinessConflict("supplier_terms_changed", "抵款明细与批准条件不同")
    state["return_confirmations"].append(row)
    task["progress"]["return_id"] = row["return_id"]


@_receipt("receipts", "event_id")
def apply_business_receipt(state, row):
    kind = row["event_type"]
    occurred = timestamp(row["occurred_at"])
    task = _task(state, row.get("task_id"), new_action=kind in {"transfer_shipped", "return_shipped", "order_confirmed", "purchase_cancelled", "promotion_price_effective"})
    quantity_kinds = {"transfer_shipped", "transfer_received", "supplier_confirmed", "return_shipped", "supplier_accepted", "exchange_received", "order_confirmed", "purchase_received"}
    quantity = number(row.get("quantity"), positive=kind != "order_confirmed") if kind in quantity_kinds else Decimal(0)
    action = _action(task) if task else {}
    planned = task["plan"].get("allocated_qty", 0) if task else 0
    if kind == "transfer_shipped":
        if task is None or task["type"] != "transfer":
            raise ValueError("Transfer receipt requires a confirmed transfer task")
        _check_resource(task, row)
        destination = action["target_store_id"]
        if row.get("to_store_id") != destination:
            raise BusinessConflict("receipt_scope_mismatch", "调拨收货门店与方案不一致")
        _increment(task, "shipped_qty", quantity, planned)
        _consume_reservation(state, task, row, quantity)
        _move(state, row, quantity, from_state="on_hand", to_state="in_transit", to_store_id=destination)
    elif kind == "transfer_received":
        if task is None or task["type"] != "transfer":
            raise ValueError("Transfer receipt requires a confirmed transfer task")
        _check_resource(task, row, destination=True)
        if row.get("from_store_id") != action["source_store_id"]:
            raise BusinessConflict("receipt_scope_mismatch", "发货门店与已确认方案不一致")
        shipped_by_time = sum((number(item["quantity"]) for item in state["receipts"]
                               if item.get("task_id") == task["id"] and item["event_type"] == "transfer_shipped"
                               and timestamp(item["occurred_at"]) <= occurred), Decimal(0))
        _increment(task, "received_qty", quantity, shipped_by_time)
        _move(state, row, quantity, from_state="in_transit", to_state="on_hand")
        task["progress"].setdefault("first_received_date", occurred.date().isoformat())
    elif kind == "supplier_confirmed":
        if task is None or task["type"] != "return":
            raise ValueError("Return confirmation requires a return task")
        confirmation = next((item for item in state["return_confirmations"] if item["task_id"] == task["id"]), None)
        if not confirmation or row.get("accepted_mode") != confirmation["accepted_mode"] or quantity != number(confirmation["accepted_qty"]):
            raise BusinessConflict("supplier_terms_changed", "供应商确认与批准条件不同，需要重新确认方案")
        task["progress"]["supplier_confirmed_qty"] = quantity
    elif kind == "return_shipped":
        if task is None or task["type"] != "return":
            raise ValueError("Return shipment requires a return task")
        _check_resource(task, row)
        _increment(task, "shipped_qty", quantity, task["progress"].get("supplier_confirmed_qty", 0))
        _consume_reservation(state, task, row, quantity)
        _move(state, row, quantity, from_state="on_hand", to_state="return_in_transit")
    elif kind == "supplier_accepted":
        if task is None or task["type"] != "return":
            raise ValueError("Supplier acceptance requires a return task")
        _increment(task, "accepted_qty", quantity, task["progress"].get("shipped_qty", 0))
        allocation = task["plan"]["allocations"][0]
        _move(state, allocation, quantity, from_state="return_in_transit")
    elif kind == "exchange_received":
        if task is None or action.get("settlement_mode") != "exchange":
            raise ValueError("Replacement receipt requires an approved exchange")
        confirmation = next((c for c in state["return_confirmations"] if c["task_id"] == task["id"]), None)
        if not confirmation or row["sku_id"] != confirmation["replacement_sku_id"] or row["lot_id"] != confirmation["replacement_lot_id"]:
            raise BusinessConflict("replacement_mismatch", "换货商品与供应商确认不一致")
        if number(task["progress"].get("accepted_qty", 0)) < number(confirmation["accepted_qty"]):
            raise BusinessConflict("return_not_accepted", "原退货尚未完成供应商验收")
        if row["store_id"] != action["store_id"] or number(row["unit_cost"]) != number(action["replacement_unit_cost"]):
            raise BusinessConflict("replacement_mismatch", "换货门店或单价与已确认条件不同")
        if row.get("cash_difference") is not None and number(row["cash_difference"]) != number(action["cash_difference"]):
            raise BusinessConflict("replacement_mismatch", "换货差价与已确认条件不同")
        _increment(task, "replacement_qty", quantity, confirmation["replacement_qty"])
        _move(state, row, quantity, to_state="on_hand")
    elif kind == "credit_issued":
        if task is None or action.get("settlement_mode") != "payable_credit":
            raise ValueError("Credit requires an approved credit return")
        confirmation = next((c for c in state["return_confirmations"] if c["task_id"] == task["id"]), None)
        amount = number(row["amount"], "amount", positive=True)
        if not confirmation or number(task["progress"].get("accepted_qty", 0)) < number(confirmation["accepted_qty"]):
            raise BusinessConflict("unconfirmed_credit", "抵款额度尚未确认或退货尚未验收")
        if any(c["credit_note_id"] == row["credit_note_id"] for c in state["credits"]):
            raise BusinessConflict("duplicate_credit", "抵款凭证已存在")
        if row["supplier_id"] != action["supplier_id"]:
            raise BusinessConflict("supplier_mismatch", "抵款供应商与已确认方案不同")
        date.fromisoformat(row["expires_at"])
        _increment(task, "credit_issued", amount, confirmation["credit_amount"])
        state["credits"].append({**row, "used_amount": Decimal(0)})
    elif kind == "credit_applied":
        credit = next((c for c in state["credits"] if c["credit_note_id"] == row["credit_note_id"]), None)
        payable = next((p for p in state["payables"] if p.get("payable_id") == row["payable_id"]), None)
        amount = number(row["amount"], "amount", positive=True)
        if not credit or not payable or not task or credit["task_id"] != task["id"] or row["payable_id"] != action["payable_id"]:
            raise ValueError("Unknown credit or payable")
        if payable.get("supplier_id") != credit.get("supplier_id"):
            raise BusinessConflict("supplier_mismatch", "抵款不能用于其他供应商")
        if occurred.date() > date.fromisoformat(credit["expires_at"]):
            raise BusinessConflict("credit_expired", "抵款凭证已过期")
        if amount > number(credit["amount"]) - number(credit["used_amount"]) or amount > number(payable["outstanding_amount"]):
            raise BusinessConflict("credit_exceeded", "抵扣超出可用额度或应付金额")
        credit["used_amount"] = number(credit["used_amount"]) + amount
        payable["applied_credit_amount"] = number(payable["applied_credit_amount"]) + amount
        payable["outstanding_amount"] = number(payable["outstanding_amount"]) - amount
        _increment(task, "credit_applied", amount)
    elif kind == "purchase_cancelled":
        if task is None or task["type"] != "purchase" or number(action["quantity"]) != 0:
            raise BusinessConflict("order_changed", "不下单回执必须对应已经批准的零采购方案")
        if row.get("intent_id") != action["intent_id"] or not row.get("receipt_ref") or any(row.get(k) != action[k] for k in ("store_id", "sku_id", "supplier_id")):
            raise BusinessConflict("order_changed", "不下单确认与批准意向不一致")
        task["progress"]["purchase_cancelled"] = True
    elif kind == "order_confirmed":
        if task is None or task["type"] != "purchase":
            raise ValueError("Order confirmation requires a purchase task")
        if number(action["quantity"]) == 0:
            raise BusinessConflict("order_changed", "零采购方案需要不下单确认，不能创建零数量订单")
        if quantity != number(action.get("quantity", planned)):
            raise BusinessConflict("order_changed", "订单数量与批准方案不一致")
        if number(row["unit_cost"]) != number(action["unit_cost"]):
            raise BusinessConflict("order_changed", "订单单价与批准方案不一致")
        if any(row.get(key) != action[key] for key in ("store_id", "sku_id")) or row["payment_due"] != action["payment_date"]:
            raise BusinessConflict("order_changed", "订单商品、门店或付款日期与批准方案不同")
        if task["progress"].get("po_line_id") and task["progress"]["po_line_id"] != row["po_line_id"]:
            raise BusinessConflict("order_changed", "不能将同一采购任务绑定到第二张订单")
        task["progress"].update({"ordered_qty": quantity, "po_line_id": row["po_line_id"],
                                 "confirmed_payment": quantity * number(row["unit_cost"]), "payment_due": row["payment_due"]})
    elif kind == "purchase_received":
        if row.get("shipment_line_id"):
            source = next((p for p in state["positions"].values() if row["shipment_line_id"] in p.get("shipments", {}) and p["stock_state"] == "in_transit"), None)
            if source is None or any(source[k] != row[k] for k in ("store_id", "sku_id", "lot_id")):
                raise BusinessConflict("unknown_inbound", "在途收货必须匹配原运输明细")
            _move(state, row, quantity, from_state="in_transit", to_state="on_hand")
        else:
            if task is None or task["progress"].get("po_line_id") != row.get("po_line_id"):
                raise BusinessConflict("order_not_confirmed", "采购收货缺少已确认订单")
            if task["type"] != "purchase" or any(row.get(key) != action[key] for key in ("store_id", "sku_id")) or number(row["unit_cost"]) != number(action["unit_cost"]):
                raise BusinessConflict("order_changed", "采购收货商品、门店或单价与已批准方案不同")
            _increment(task, "received_qty", quantity, task["progress"].get("ordered_qty", 0))
            _move(state, row, quantity, to_state="on_hand")
    elif kind in ("promotion_price_effective", "promotion_ended"):
        if task is None or task["type"] != "promotion":
            raise ValueError("Promotion receipt requires a promotion task")
        if row["promotion_id"] != action["promotion_id"]:
            raise BusinessConflict("promotion_mismatch", "促销回执不属于该活动")
        if kind == "promotion_ended" and not task["progress"].get("promotion_price_effective"):
            raise BusinessConflict("promotion_not_active", "活动尚未生效")
        task["progress"][kind] = True
        if kind == "promotion_ended":
            state["reservations"] = [r for r in state["reservations"] if r["task_id"] != task["id"]]
    elif kind == "execution_exception":
        if task is None:
            raise ValueError("Exception requires a task")
        task["exception_flags"].append(row.get("reason") or "execution_exception")
    elif kind in {"supplier_reply_recorded", "supplier_terms_reviewed"}:
        if task is None or task["type"] != "return":
            raise ValueError("Supplier communications require a confirmed return task")
        # A recorded local reply is an audit item only. It does not mean that
        # the supplier accepted the return or changed the approved terms.
        task["progress"].setdefault("supplier_communications", []).append({
            "event_type": kind, "receipt_ref": row.get("receipt_ref"),
            "detail": row.get("detail"), "occurred_at": row.get("occurred_at"),
        })
    else:
        raise ValueError(f"Unsupported business receipt: {kind}")
    state["receipts"].append(deepcopy(row))
    if task:
        task["version"] += 1
    return True


@_receipt("sales", "sale_id")
def apply_sale(state, row):
    quantity = number(row["sold_qty"], positive=True)
    revenue = number(row["sales_amount"], "sales_amount")
    if revenue != quantity * number(row["unit_price"], "unit_price"):
        raise ValueError("Sale amount must equal quantity times transaction price")
    task = _task(state, row.get("task_id"))
    if task:
        if task["type"] not in {"transfer", "promotion"}:
            raise ValueError("This task does not own the sold stock")
        _check_resource(task, row, destination=task["type"] == "transfer")
        if task["type"] == "transfer":
            if row["date"] < task["progress"].get("first_received_date", "9999-12-31"):
                raise BusinessConflict("sale_before_receipt", "销售不能早于调拨签收")
            received_by_date = sum((number(r["quantity"]) for r in state["receipts"] if r.get("task_id") == task["id"]
                                   and r["event_type"] == "transfer_received" and timestamp(r["occurred_at"]).date().isoformat() <= row["date"]), Decimal(0))
            prior_sales = sum((number(s["sold_qty"]) for s in state["sales"] if s.get("task_id") == task["id"] and s["date"] <= row["date"]), Decimal(0))
            if prior_sales + quantity > received_by_date:
                raise BusinessConflict("sale_before_receipt", "该销售日的已签收数量不足")
            _increment(task, "sold_qty", quantity, task["progress"].get("received_qty", 0))
        if task["type"] == "promotion":
            if not task["progress"].get("promotion_price_effective") or task["progress"].get("promotion_ended"):
                raise BusinessConflict("promotion_not_active", "促销尚未生效或已经结束")
            if not any(stage["start_date"] <= row["date"] < stage["end_date_exclusive"] for stage in _action(task)["stages"]):
                raise BusinessConflict("outside_promotion_period", "销售日期不属于批准活动阶段")
            _consume_reservation(state, task, row, quantity)
            components = task["progress"].setdefault("sold_components", {})
            components[row["sku_id"]] = number(components.get(row["sku_id"], 0)) + quantity
    key = resource(row)
    position = state["positions"].get(key)
    if position is None:
        raise ValueError("Sale references unknown stock")
    if position.get("sellable_until") is None:
        raise BusinessConflict("unknown_sellable_deadline", "缺少可售截止日，不能核对销售")
    if date.fromisoformat(row["date"]) >= date.fromisoformat(position["sellable_until"]):
        raise BusinessConflict("past_sellable_deadline", "销售日期已到不可售日期")
    cost = quantity * number(position["unit_cost"], "unit_cost")
    if row.get("sold_cost") is not None and number(row["sold_cost"], "sold_cost") != cost:
        raise BusinessConflict("sale_cost_mismatch", "销售成本与原批次成本不一致")
    if (task is None or task["type"] == "transfer") and quantity > available(state, row):
        raise BusinessConflict("reserved_stock", "普通销售不能消耗其他方案已预占库存")
    _move(state, row, quantity, from_state="on_hand")
    state["sales"].append({**deepcopy(row), "sold_cost": cost})
    return True


@_receipt("cash_events", "cash_event_id")
def apply_cash(state, row):
    if row["direction"] not in ("in", "out") or not row.get("receipt_ref"):
        raise ValueError("Cash requires direction and a receipt reference")
    if row["account_id"] not in state["account_ids"]:
        raise ValueError("Cash references an unknown account")
    amount = number(row["amount"], "amount", positive=True)
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Cash receipts require whole cents in CNY")
    timestamp(row["occurred_at"])
    task = _task(state, row.get("task_id"))
    category = row.get("category")
    if category == "purchase_payment":
        if task is None or task["type"] != "purchase" or row["direction"] != "out" or row["business_ref"] != task["progress"].get("po_line_id"):
            raise BusinessConflict("payment_scope_mismatch", "付款必须匹配已确认采购订单")
        _increment(task, "purchase_paid", amount, task["progress"].get("confirmed_payment", 0))
    elif category == "payable_payment":
        payable = next((p for p in state["payables"] if p["payable_id"] == row["business_ref"]), None)
        if not payable or row["direction"] != "out" or amount > number(payable["outstanding_amount"]):
            raise BusinessConflict("payment_scope_mismatch", "付款不能超过关联应付未付金额")
        if task and _action(task).get("payable_id") != payable["payable_id"]:
            raise BusinessConflict("payment_scope_mismatch", "应付不属于该任务")
        payable["paid_amount"] = number(payable["paid_amount"]) + amount
        payable["outstanding_amount"] = number(payable["outstanding_amount"]) - amount
        payable["status"] = "paid" if payable["outstanding_amount"] == 0 else "partially_paid"
    elif category == "exchange_difference":
        if task is None or _action(task).get("settlement_mode") != "exchange" or row["direction"] != "out":
            raise ValueError("Exchange difference requires an outgoing exchange payment")
        _increment(task, "exchange_difference_paid", amount, _action(task)["cash_difference"])
    elif category == "execution_fee":
        if task is None or row["direction"] != "out":
            raise ValueError("Execution fees require an outgoing payment and a task")
    state["cash_events"].append(deepcopy(row))
    return True


def receivable(state, business_ref):
    sale = next((s for s in state["sales"] if s["sale_id"] == business_ref), None)
    if sale:
        return number(sale["sales_amount"]), sale.get("task_id"), "sale", sale["sale_id"]
    for confirmation in state["return_confirmations"]:
        if business_ref in (confirmation["return_id"], confirmation.get("confirmation_ref")):
            task = next(t for t in state["tasks"] if t["id"] == confirmation["task_id"])
            if confirmation["accepted_mode"] != "cash_refund":
                raise ValueError("Exchange and credit are not cash receivables")
            amount = number(task["progress"].get("accepted_qty", 0)) * number(confirmation["accepted_unit_price"])
            return amount, task["id"], "refund", confirmation["return_id"]
    raise ValueError("Cash allocation references an unknown receivable")


def _payable(state, business_ref):
    task = next((item for item in state["tasks"] if item["type"] == "purchase" and
                 item["progress"].get("po_line_id") == business_ref), None)
    if task:
        return number(task["progress"]["confirmed_payment"]), task["id"], "purchase_payment", business_ref
    payable = next((item for item in state["payables"] if item["payable_id"] == business_ref), None)
    if payable:
        task = next((item for item in state["tasks"] if _action(item).get("payable_id") == business_ref), None)
        return number(payable["original_amount"]) - number(payable["applied_credit_amount"]), task["id"] if task else None, "payable_payment", business_ref
    raise ValueError("Outgoing allocation references an unknown confirmed payable")


@_receipt("cash_allocations", "allocation_id")
def apply_cash_allocation(state, row):
    event = next((c for c in state["cash_events"] if c["cash_event_id"] == row["cash_event_id"]), None)
    if event is None:
        raise ValueError("Allocation requires an existing cash event")
    amount = number(row["allocated_amount"], "allocated_amount", positive=True)
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Cash allocations require whole cents in CNY")
    matched = sum((number(a["allocated_amount"]) for a in state["cash_allocations"] if a["cash_event_id"] == event["cash_event_id"]), Decimal(0))
    lookup = receivable if event["direction"] == "in" else _payable
    due, task_id, kind, reference = lookup(state, row["business_ref"])
    previously = sum((number(a["allocated_amount"]) for a in state["cash_allocations"] if a["receivable_ref"] == reference), Decimal(0))
    if matched + amount > number(event["amount"]) or previously + amount > due:
        raise BusinessConflict("over_allocation", "核销不能超过流水金额或应收金额")
    if event.get("task_id") and event["task_id"] != task_id:
        raise BusinessConflict("payment_scope_mismatch", "流水的业务归属与应收任务不同")
    if event["direction"] == "out":
        if event.get("category") in {"purchase_payment", "payable_payment"}:
            if event["business_ref"] != reference or event["category"] != kind:
                raise BusinessConflict("payment_scope_mismatch", "付款流水与待核销应付不同")
        elif kind == "purchase_payment":
            task = _task(state, task_id)
            _increment(task, "purchase_paid", amount, task["progress"]["confirmed_payment"])
        else:
            payable = next(item for item in state["payables"] if item["payable_id"] == reference)
            if amount > number(payable["outstanding_amount"]):
                raise BusinessConflict("over_allocation", "付款核销不能超过应付未付金额")
            payable["paid_amount"] = number(payable["paid_amount"]) + amount
            payable["outstanding_amount"] = number(payable["outstanding_amount"]) - amount
    state["cash_allocations"].append({**deepcopy(row), "task_id": task_id, "kind": kind, "receivable_ref": reference})
    return True


def project_execution(state, *, clock_at=None):
    """Case cash is allocated; account cash is the separate actual cash ledger."""
    clock = timestamp(clock_at or state["clock_at"])
    for task in state["tasks"]:
        progress, kind = task["progress"], task["type"]
        planned = number(task["plan"]["allocated_qty"])
        action = _action(task)
        completed_qty = number(progress.get("received_qty", progress.get("accepted_qty", 0)))
        finished = False
        if kind == "transfer":
            finished = number(progress.get("received_qty", 0)) >= planned
        elif kind == "return":
            finished = number(progress.get("accepted_qty", 0)) >= planned
            if _action(task).get("settlement_mode") == "exchange":
                finished = finished and number(progress.get("replacement_qty", 0)) >= number(action["replacement_qty"])
        elif kind == "purchase":
            finished = bool(progress.get("purchase_cancelled")) if planned == 0 else (
                "ordered_qty" in progress and number(progress.get("received_qty", 0)) >= number(progress["ordered_qty"]))
        elif kind == "promotion":
            finished = bool(progress.get("promotion_ended"))
        task["execution_status"] = "completed" if finished else "in_progress" if progress else "pending"
        sales = [s for s in state["sales"] if s.get("task_id") == task["id"]]
        matched = [a for a in state["cash_allocations"] if a.get("task_id") == task["id"]]
        revenue = sum((number(s["sales_amount"]) for s in sales), Decimal(0))
        sales_cash = sum((number(a["allocated_amount"]) for a in matched if a["kind"] == "sale"), Decimal(0))
        refund_cash = sum((number(a["allocated_amount"]) for a in matched if a["kind"] == "refund"), Decimal(0))
        cost = sum((number(s["sold_cost"]) for s in sales), Decimal(0))
        fees = sum((number(c["amount"]) for c in state["cash_events"] if c.get("task_id") == task["id"] and c["direction"] == "out" and c.get("category") == "execution_fee"), Decimal(0))
        fee_pending = max(Decimal(0), number(task["plan"]["execution_cost"]) - fees)
        purchase_paid = number(progress.get("purchase_paid", 0))
        credit_pending = Decimal(0)
        task["result"] = {"sales_amount": revenue, "sales_cash_received": sales_cash,
                          "sales_receivable": revenue - sales_cash, "sold_cost": cost,
                          "refund_cash_received": refund_cash, "execution_fees_paid": fees,
                          "realized_gross_profit_less_paid_fees": revenue - cost - fees,
                          "purchase_cash_paid": purchase_paid, "unpaid_planned_execution_cost": fee_pending,
                          "credit_applied": number(progress.get("credit_applied", 0)),
                          "remaining_execution_qty": max(Decimal(0), planned - completed_qty) if kind != "promotion" else None,
                          "remaining_replacement_qty": max(Decimal(0), number(action["replacement_qty"]) - number(progress.get("replacement_qty", 0)))
                          if kind == "return" and action["settlement_mode"] == "exchange" else None,
                          "sold_components": deepcopy(progress.get("sold_components", {}))}
        outstanding = revenue - sales_cash
        if kind == "return" and _action(task).get("settlement_mode") == "cash_refund":
            confirmations = [c for c in state["return_confirmations"] if c["task_id"] == task["id"]]
            if confirmations:
                outstanding += number(progress.get("accepted_qty", 0)) * number(confirmations[-1]["accepted_unit_price"]) - refund_cash
        elif kind == "return" and action["settlement_mode"] == "exchange":
            outstanding += number(action["cash_difference"]) - number(progress.get("exchange_difference_paid", 0))
        elif kind == "return" and action["settlement_mode"] == "payable_credit":
            credit_pending = max(Decimal(0), number(action["applied_credit_amount"]) - number(progress.get("credit_applied", 0)))
        elif kind == "purchase":
            outstanding += number(progress.get("confirmed_payment", 0)) - purchase_paid
        task["result"]["outstanding_cash"] = outstanding
        period_closed = bool(task["evaluation_end"] and clock.date() >= date.fromisoformat(task["evaluation_end"]))
        task["result"].update(credit_pending=credit_pending, observation_period_closed=period_closed)
        settled = finished and outstanding == 0 and fee_pending == 0 and credit_pending == 0
        if kind in {"transfer", "promotion"}:
            settled = settled and period_closed
        task["accounting_status"] = "completed" if settled else "in_progress" if matched or sales or fees or progress else "pending"
    incoming = sum((number(c["amount"]) for c in state["cash_events"] if c["direction"] == "in"), Decimal(0))
    outgoing = sum((number(c["amount"]) for c in state["cash_events"] if c["direction"] == "out"), Decimal(0))
    return {"cash_in": incoming, "cash_out": outgoing, "net_cash_change": incoming - outgoing,
            "tasks": deepcopy(state["tasks"]), "inventory": list(deepcopy(state["positions"]).values())}
