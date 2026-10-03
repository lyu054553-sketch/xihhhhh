"""Independent slow-stock and expiry assessments over one frozen read model."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from backend.hackathon_data.loader import parse_clock


CALCULATION_VERSION = "scenario-risk-v1"


def _number(value):
    return Decimal(str(value))


def _rounded(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _policy(facts, store_id, sku_id, today, policy_id=None):
    rows = [row for row in facts["tables"]["risk_policies"]
            if row["valid_from"] <= today.isoformat() < row["valid_to"]]
    if policy_id:
        return next((row for row in rows if row["policy_id"] == policy_id), None)
    scope = f"{facts['scenario_id']}:{store_id}:{sku_id}"
    return next((row for row in rows if row["scope"] == scope),
                next((row for row in rows if row["scope"] == "all_complete_stores"), None))


def _slow(quantity, sales, observed, missing, policy):
    missing = list(missing)
    if policy is None:
        missing.append("risk_policy")
    if sales is None:
        missing.append("sales_30")
    elif sales <= 0:
        missing.append("positive_observed_sales")
    if observed is None:
        missing.append("valid_observed_days")
    elif policy and observed < policy["min_observed_days"]:
        missing.append("sufficient_observed_days")
    coverage = None
    status = "unknown"
    if not missing:
        coverage = quantity * _number(observed) / sales
        status = "risk" if coverage > _number(policy["slow_coverage_days_threshold"]) else "normal"
    return {"status": status, "coverage_days": _rounded(coverage) if coverage is not None else None,
            "sales_30": _rounded(sales) if sales is not None else None, "valid_observed_days": observed,
            "threshold_days": policy["slow_coverage_days_threshold"] if policy else None,
            "missing_fields": list(dict.fromkeys(missing))}


def _expiry(sellable_until, today, policy):
    days = (date.fromisoformat(sellable_until) - today).days if sellable_until else None
    missing = []
    if days is None:
        missing.append("sellable_until")
    if policy is None:
        missing.append("risk_policy")
    if days is not None and days <= 0:
        status = "unsellable"
    elif missing:
        status = "unknown"
    else:
        status = "risk" if days <= policy["expiry_alert_days"] else "normal"
    return {"status": status, "remaining_sellable_days": days, "sellable_until": sellable_until,
            "threshold_days": policy["expiry_alert_days"] if policy else None, "missing_fields": missing}


def _observation(tables, today):
    start = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()
    sales = defaultdict(lambda: defaultdict(list))
    availability = defaultdict(dict)
    for row in tables["sales_daily"]:
        if start <= row["date"] < end:
            sales[(row["store_id"], row["sku_id"])][row["date"]].append(row)
    for row in tables["availability_daily"]:
        if start <= row["date"] < end:
            availability[(row["store_id"], row["sku_id"])][row["date"]] = row
    results = {}
    for key in set(sales) | set(availability):
        total, observed, missing = Decimal(0), 0, []
        for offset in range(30):
            day = (today - timedelta(days=30 - offset)).isoformat()
            state = availability[key].get(day)
            rows = sales[key].get(day)
            if state is None or rows is None:
                missing.append("sales_or_availability_history")
                continue
            # Count a day once even if several price/batch sales rows exist.
            if (state["listing_status"] != "listed" or state["stockout_flag"] or
                    not state["open_hours"] or state["on_shelf_hours"] < state["open_hours"] or
                    state["in_stock_hours"] < state["open_hours"]):
                continue
            if any(row["sold_qty"] is None or row["customer_return_qty"] is None for row in rows):
                missing.append("sales_30")
                continue
            total += sum((_number(row["sold_qty"]) - _number(row["customer_return_qty"]) for row in rows), Decimal(0))
            observed += 1
        results[key] = (total, observed, missing)
    return results


def scenario_risks(facts):
    tables = facts["tables"]
    today = parse_clock(facts["clock_at"]).date()
    stores = {row["store_id"]: row for row in tables["stores"]}
    products = {row["sku_id"]: row for row in tables["products"]}
    inventory = [row for row in tables["inventory"] if row["stock_state"] == "on_hand"]
    groups = defaultdict(list)
    for row in inventory:
        groups[(row["store_id"], row["sku_id"])].append(row)
    observations = _observation(tables, today)
    isolated = tables["risk_inputs"]
    items = []
    for (store_id, sku_id), batches in groups.items():
        policy = _policy(facts, store_id, sku_id, today, isolated[0]["policy_id"] if isolated else None)
        available = sum((_number(row["quantity"]) - _number(row["blocked_qty"]) - _number(row["reserved_qty"])
                         for row in batches if row["sellable_until"] is None or row["sellable_until"] > today.isoformat()), Decimal(0))
        if isolated:
            source = isolated[0]
            sales = _number(source["sales_30"]) if source["sales_30"] is not None else None
            observed, missing = source["valid_observed_days"], []
        else:
            sales, observed, missing = observations.get((store_id, sku_id), (None, None, ["sales_or_availability_history"]))
        slow = _slow(available, sales, observed, missing, policy)
        daily = sales / _number(observed) if slow["status"] != "unknown" else None
        preceding = Decimal(0)
        # A shared demand budget is consumed in FEFO order, never once per lot.
        for row in sorted(batches, key=lambda item: (item["sellable_until"] is None, item["sellable_until"] or "", item["lot_id"])):
            expiry = _expiry(row["sellable_until"], today, policy)
            quantity = _number(row["quantity"])
            sellable = quantity - _number(row["blocked_qty"]) - _number(row["reserved_qty"])
            cost = quantity * _number(row["unit_cost"])
            tags = []
            if slow["status"] == "risk":
                tags.append("slow")
            if expiry["status"] == "risk":
                tags.append("near_expiry")
            if expiry["status"] == "unsellable":
                tags.append("unsellable")
            unknown = slow["status"] == "unknown" or expiry["status"] == "unknown"
            unsold = None
            if daily is not None and expiry["remaining_sellable_days"] is not None:
                demand = max(Decimal(0), daily * max(0, expiry["remaining_sellable_days"]) - preceding)
                sold = min(sellable, demand)
                unsold = sellable - sold
                preceding += sold
            else:
                preceding += sellable
            items.append({"inventory_id": row["inventory_id"], "store_id": store_id,
                          "store_name": stores[store_id]["store_name"], "sku_id": sku_id,
                          "product_name": products[sku_id]["product_name"], "unit": products[sku_id]["base_unit"],
                          "lot_id": row["lot_id"], "quantity": _rounded(quantity), "sellable_qty": _rounded(sellable),
                          "inventory_cost": _rounded(cost),
                          "risk_inventory_cost": _rounded(cost) if tags else None if unknown else 0.0,
                          "slow": dict(slow), "near_expiry": expiry, "risk_tags": tags,
                          "predicted_unsold_qty": _rounded(unsold) if unsold is not None else None,
                          "prediction_basis": "按有效可售日净销量及先到期先出估算；不代表未来实际销售",
                          "policy_id": policy["policy_id"] if policy else None,
                          "calculation_version": CALCULATION_VERSION})
    risk_items = [item for item in items if item["risk_tags"]]
    unknown_items = [item for item in items if item["risk_inventory_cost"] is None]
    return {"snapshot_id": facts["snapshot_id"], "scenario_id": facts["scenario_id"],
            "branch_id": facts["branch_id"], "clock_at": facts["clock_at"], "is_demo": facts["is_demo"],
            "calculation_version": CALCULATION_VERSION, "items": items,
            "summary": {"inventory_cost": _rounded(sum((_number(item["inventory_cost"]) for item in items), Decimal(0))),
                        "known_risk_inventory_cost": _rounded(sum((_number(item["inventory_cost"]) for item in risk_items), Decimal(0))),
                        "unknown_risk_inventory_cost": _rounded(sum((_number(item["inventory_cost"]) for item in unknown_items), Decimal(0))),
                        "risk_batch_count": len(risk_items), "unknown_batch_count": len(unknown_items),
                        "risk_cost_complete": not unknown_items,
                        "included_store_count": len({item["store_id"] for item in items}),
                        "directory_store_count": len(stores)}}
