"""Execution-only fixture import. It never participates in model input or planning."""
from copy import deepcopy
from decimal import Decimal

from ..errors import BusinessConflict
from . import domain


TASK_TYPES = {"transfer": "transfer", "return": "return", "promotion": "promotion", "purchase_change": "purchase"}
TABLES = {"return_confirmations": (0, "return_confirmation"), "business_receipts": (1, "business"),
          "sales": (2, "sale"), "cash_events": (3, "cash"), "cash_allocations": (4, "cash_allocation")}


def attribute_payment(record, tasks, state):
    matches = []
    for task in tasks:
        action = task["plan"]["actions"][0]
        reference = record["business_ref"]
        expected_fee = None
        if task["type"] == "transfer" and reference == action["route_id"]:
            expected_fee = action["transport_fee"]
        elif task["type"] == "purchase" and reference == task["progress"].get("po_line_id"):
            matches.append((task, "purchase_payment"))
        elif task["type"] == "return" and any(c["task_id"] == task["id"] and c["return_id"] == reference for c in state["return_confirmations"]):
            expected_fee = action["freight_fee"]
        elif task["type"] == "promotion" and reference == action["promotion_id"]:
            expected_fee = action["execution_fee"]
        if expected_fee is not None:
            if domain.number(record["amount"]) != domain.number(expected_fee):
                raise BusinessConflict("replay_fee_mismatch", "回放费用与已批准条件不同")
            matches.append((task, "execution_fee"))
    if len(matches) == 1:
        record["task_id"], record["category"] = matches[0][0]["id"], matches[0][1]
        record.update(proposal_id=matches[0][0]["proposal_id"], proposal_version=matches[0][0]["proposal_version"])
    elif not matches and any(p["payable_id"] == record["business_ref"] for p in state["payables"]):
        record["category"] = "payable_payment"
    else:
        raise BusinessConflict("replay_payment_mismatch", "回放支出无法唯一对应已批准动作或应付")


def advance(service, tx, facts, request):
    if service.replay_reader is None or service.clock_advancer is None:
        raise ValueError("Integration must inject the isolated replay reader and fact clock advancer")
    context = facts["context"]
    clock_at = domain.timestamp(request["as_of"]).isoformat()
    if request["expected_fact_version"] != context["fact_version"]:
        raise BusinessConflict("version_conflict", "回放事实版本已经变化")
    if domain.timestamp(clock_at) < domain.timestamp(context["as_of"]):
        raise ValueError("Replay clock cannot move backwards")
    before = service._hydrate(tx, facts)
    approved = [t for t in before["tasks"] if not t["cancelled"] and t["proposal_id"] == request["proposal_id"] and t["proposal_version"] == request["proposal_version"]]
    if not approved:
        raise BusinessConflict("replay_requires_approval", "回放需要已确认任务")
    replay = service.replay_reader(context["scenario_id"], context["branch_id"], clock_at=clock_at)
    if replay["scenario_id"] != context["scenario_id"] or replay["branch_id"] != context["branch_id"]:
        raise ValueError("Replay branch differs from approved context")
    tables = replay["tables"]
    task_map = {}
    for template in tables["tasks"]:
        kind = TASK_TYPES.get(template["type"])
        matches = [t for t in approved if t["type"] == kind and t["proposal_version"] == template["proposal_version"]
                   and t["base_unit"] == template["unit"] and domain.number(t["plan"]["allocated_qty"]) == domain.number(template["planned_qty"])]
        if len(matches) != 1:
            raise BusinessConflict("replay_plan_mismatch", "固定回放需要数量相符且唯一的批准任务")
        task_map[template["task_id"]] = matches[0]["id"]
    # Publish known reference data and the clock only; never future actual stock.
    updated = service.clock_advancer(tx, context, clock_at)
    context = updated["context"]
    facts = service._query(context)
    state = service._hydrate(tx, facts)
    state["clock_at"] = clock_at
    known_lots = facts["reference_data"]["tables"]["lots"]
    events = []
    for table, (order, kind) in TABLES.items():
        for raw in tables[table]:
            record = deepcopy(raw)
            if record.get("task_id"):
                if record["task_id"] not in task_map:
                    raise BusinessConflict("replay_plan_mismatch", "回执缺少相符的批准任务")
                record["task_id"] = task_map[record["task_id"]]
                task = next(t for t in approved if t["id"] == record["task_id"])
                record.update(proposal_id=task["proposal_id"], proposal_version=task["proposal_version"])
            if kind == "business" and record["event_type"] in {"purchase_received", "exchange_received"}:
                lot = next((l for l in known_lots if l["lot_id"] == record["lot_id"] and l["sku_id"] == record["sku_id"]), None)
                if lot:
                    record["sellable_until"] = lot.get("sellable_until")
            events.append((domain.timestamp(record["known_at"]), order, kind, record))
    # Prices are validated from the visible fixture lines as complete groups;
    # a changed approved bundle price cannot inherit old fixed sales.
    for task in state["tasks"]:
        if task["type"] != "promotion":
            continue
        action = task["plan"]["actions"][0]
        sales = [r for _, _, kind, r in events if kind == "sale" and r.get("task_id") == task["id"]]
        for sale_date in {r["date"] for r in sales}:
            day = [r for r in sales if r["date"] == sale_date]
            stage = next((s for s in action["stages"] if s["start_date"] <= sale_date < s["end_date_exclusive"]), None)
            if not stage:
                raise BusinessConflict("replay_plan_mismatch", "回放日期不属于批准促销阶段")
            components = {domain.resource(r): domain.number(r["quantity"]) / domain.number(action["quantity"], positive=True) for r in action["components"]}
            sold = {}
            for sale in day:
                key = domain.resource(sale)
                sold[key] = sold.get(key, Decimal(0)) + domain.number(sale["sold_qty"])
            counts = {sold[key] / per_group for key, per_group in components.items() if key in sold}
            total = sum((domain.number(r["sales_amount"]) for r in day), Decimal(0))
            if set(sold) != set(components) or len(counts) != 1 or total != next(iter(counts)) * domain.number(stage["bundle_price"]):
                raise BusinessConflict("replay_plan_mismatch", "回放组合价格与批准价格不同")
    applied, duplicates = [], []
    for _, _, kind, record in sorted(events, key=lambda item: (item[0], item[1])):
        if kind == "cash" and record["direction"] == "out":
            attribute_payment(record, [t for t in state["tasks"] if t["id"] in task_map.values()], state)
        event, duplicate = service._record(tx, context, state, kind, record, clock_at=clock_at)
        if event:
            applied.append(event)
        if duplicate:
            duplicates.append(duplicate)
    service._persist_tasks(tx, context, state)
    changed = service._publish(tx, context, applied) if applied else {"context": context, "inventory_deltas": [], "applied_event_ids": []}
    cash_ids = [r[0] for r in tx.execute("SELECT id FROM cash_events WHERE tenant_id=? AND scenario_id=? ORDER BY rowid", (context["tenant_id"], context["snapshot_id"]))]
    return {**changed, "advanced_to": clock_at, "duplicate_event_ids": duplicates, "held_event_ids": [],
            "cash_event_ids": cash_ids, "accounting": service._accounting(tx, changed["context"])}
