"""Read-only operating metrics from one authoritative, clock-filtered snapshot."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from backend.hackathon_shared import CONTRACT_VERSION
from .loader import parse_clock
from .risk import scenario_risks


def money(value):
    return None if value is None else float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def total(values):
    values = list(values)
    return None if any(value is None for value in values) else sum((Decimal(str(value)) for value in values), Decimal(0))


def inventory_cost(rows):
    return total(None if row.get("quantity") is None or row.get("unit_cost") is None
                 else Decimal(str(row["quantity"])) * Decimal(str(row["unit_cost"])) for row in rows)


def commitments(tables, today):
    """Payables supersede their order lines; an intent is never a liability."""
    end = today + timedelta(days=30)
    missing, included = [], []
    payables = [row for row in tables.get("payables", []) if row.get("status") not in {"cancelled", "void"}]
    covered_orders = {row["po_id"] for row in payables if row.get("po_id") and not row.get("po_line_id")}
    covered_lines = {row["po_line_id"] for row in payables if row.get("po_line_id")}
    obligations = [("payables." + row["payable_id"], row.get("due_at"), row.get("outstanding_amount"))
                   for row in payables]
    for row in tables.get("purchase_orders", []):
        if (row.get("po_id") in covered_orders or row.get("po_line_id") in covered_lines or
                row.get("order_status") not in {"confirmed", "partially_received", "received", "completed"}):
            continue
        amount = None if any(row.get(key) is None for key in ("ordered_qty", "unit_cost", "paid_amount")) else (
            Decimal(str(row["ordered_qty"])) * Decimal(str(row["unit_cost"])) - Decimal(str(row["paid_amount"])))
        obligations.append(("purchase_orders." + row["po_line_id"], row.get("due_at"), amount))
    for ref, due, value in obligations:
        if value is not None and Decimal(str(value)) < 0:
            raise ValueError("Outstanding purchase payment cannot be negative")
        if value is not None and Decimal(str(value)) == 0:
            continue
        if due is None:
            missing.append(ref + ".due_at")
            continue
        if not today <= date.fromisoformat(due) < end:
            continue
        included.append(value)
        if value is None:
            missing.append(ref + ".outstanding_amount")
    known = total(value for value in included if value is not None)
    return {"amount": None if missing else money(known), "count": None if missing else len(included),
            "known_amount": money(known), "horizon_days": 30, "horizon_start": today.isoformat(),
            "horizon_end_exclusive": end.isoformat(), "status": "unknown" if missing else "known",
            "source": "当前场景已确认应付；已关联采购单不重复计入，未确认采购意向不计入",
            "missing_fields": missing}


def turnover(tables, rows, store_id, today):
    # This is current stock coverage by historical net cost, not forecast sales.
    skus = {row["sku_id"] for row in rows}
    start = today - timedelta(days=30)
    history = [row for row in tables["sales_daily"] if row["store_id"] == store_id
               and start.isoformat() <= row["date"] < today.isoformat()]
    observed = {(row["sku_id"], row["date"]) for row in history}
    if not skus or any((sku, (start + timedelta(days=offset)).isoformat()) not in observed
                       for sku in skus for offset in range(30)):
        return None
    cost = inventory_cost(rows)
    net_cost = total(None if row.get("sold_cost") is None or row.get("returned_cost") is None else
                     Decimal(str(row["sold_cost"])) - Decimal(str(row["returned_cost"])) for row in history)
    return money(cost * 30 / net_cost) if cost is not None and net_cost is not None and net_cost > 0 else None


def build_overview(facts, context):
    tables, today = facts["tables"], parse_clock(context["as_of"]).date()
    assessed = scenario_risks(facts)
    stock, risks = defaultdict(list), defaultdict(list)
    for row in tables["inventory"]:
        stock[row["store_id"]].append(row)
    for row in assessed["items"]:
        risks[row["store_id"]].append(row)
    labels = {"slow": "滞销", "near_expiry": "近效期", "unsellable": "已过可售期限"}
    stores, missing = [], list(context["missing_fields"])
    for store in tables["stores"]:
        store_id = store["store_id"]
        rows, items = stock[store_id], risks[store_id]
        absent = not store["include_in_summary"] or not rows
        gaps = [f"stores.{store_id}.business_facts"] if absent else []
        risk_cost = None if absent else total(item["risk_inventory_cost"] for item in items)
        if not absent:
            gaps.extend(f"stores.{store_id}.{item['sku_id']}.{item['lot_id']}.{field}"
                        for item in items for kind in ("slow", "near_expiry") for field in item[kind]["missing_fields"])
            gaps.extend(f"stores.{store_id}.{item['sku_id']}.{item['lot_id']}.{field}"
                        for item in items for field in item.get("cost_missing_fields", []))
        days = None if absent else turnover(tables, rows, store_id, today)
        if not absent and days is None:
            gaps.append(f"stores.{store_id}.positive_complete_sales_cost_30d")
        ranked = sorted((item for item in items if item["risk_tags"]), key=lambda item:
                        (item["inventory_cost"] is None, -item["inventory_cost"] if item["inventory_cost"] is not None else 0))
        tags = list(dict.fromkeys(labels[tag] for item in ranked for tag in item["risk_tags"]))
        stores.append({"store_id": store_id, "store_name": store["store_name"],
                       "inventory_cost": None if absent else money(inventory_cost(rows)), "risk_cost": money(risk_cost),
                       "turnover_days": days, "primary_risk": tags[0] if tags else None, "risk_types": tags,
                       "work_item_id": None, "work_item_label": None, "pending_label": None,
                       "missing_fields": sorted(set(gaps))})
        missing.extend(gaps)
    accounts = tables.get("accounts", [])
    missing.extend(field for row in accounts for field in row.get("missing_fields", []))
    account_balance = total(row.get("available_balance") if row.get("currency") == "CNY" else None for row in accounts) if accounts else None
    if account_balance is None:
        missing.append("accounts.available_balance_cny")
    purchase = commitments(tables, today)
    missing.extend(purchase["missing_fields"])
    risk_cost = total(row["risk_inventory_cost"] for row in assessed["items"])
    return {"contract_version": CONTRACT_VERSION, "context": context,
            "overview": {"account": {"balance": money(account_balance), "status": "known" if account_balance is not None else "unknown",
                                     "source": "本场景账户快照与已记录的账户现金流水"},
                         "inventory": {"cost": money(inventory_cost(tables["inventory"])), "risk_cost": money(risk_cost),
                                       "source": "本场景已接入库存，含在途；预占不重复加库存，多风险批次只计一次；未接入门店不计入总额"},
                         "purchase_commitments": purchase, "stores": stores},
            "metadata": {"is_demo": context["is_demo"], "source": "versioned_retail_facts",
                         "as_of_date": today.isoformat(), "as_of": context["as_of"],
                         "data_version": context["data_version"], "fact_version": context["fact_version"],
                         "source_refs": context["source_refs"], "missing_fields": sorted(set(missing)),
                         "included_store_count": sum(bool(rows) for rows in stock.values()), "directory_store_count": len(stores),
                         "turnover_basis": "当前库存成本 ÷ 近30日净销售成本 × 30；销售历史不完整或净成本不为正时未知"}}
