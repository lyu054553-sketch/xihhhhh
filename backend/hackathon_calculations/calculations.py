"""Deterministic decisions over a single, time-filtered retail scenario snapshot.

No fixture answers, future execution records, model calls or database writes belong
here.  Dates use half-open observation windows; money is CNY and uses Decimal.
The HTTP/application layer supplies confirmed facts and persists returned actions.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import re

from backend.domain import money, parse_date

ZERO = Decimal(0)
ONE = Decimal(1)


def _number(value, name, *, optional=False, integer=False):
    if value is None or value == "":
        if optional:
            return None
        raise ValueError(f"缺少 {name}")
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为非负数值")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} 必须为非负数值") from None
    if not result.is_finite() or result < 0 or (integer and result != result.to_integral_value()):
        raise ValueError(f"{name} 必须为有限非负{'整数' if integer else '数值'}")
    return result


def _date(value, name):
    result = parse_date(value)
    if result is None:
        raise ValueError(f"{name} 必须为有效日期")
    return result


def _rows(facts, name, **match):
    return [r for r in facts.get("tables", {}).get(name, [])
            if all(r.get(k) == v for k, v in match.items())]


def _single(rows, name):
    if len(rows) != 1:
        raise ValueError(f"{name} 必须唯一匹配，当前 {len(rows)} 条")
    return rows[0]


def _scope(facts, request):
    target = {**facts.get("target", {}), **{k: request[k] for k in ("store_id", "sku_id", "lot_id") if k in request}}
    start = _date(facts.get("clock_at"), "clock_at")
    end = _date(request.get("evaluation_end", facts.get("evaluation_end")), "evaluation_end")
    if end <= start or (end - start).days > 366:
        raise ValueError("观察期必须为 1 至 366 天，结束日期不包含在内")
    return target, start, end


def _available(row):
    qty = _number(row.get("quantity"), "inventory.quantity")
    blocked = _number(row.get("blocked_qty", 0), "blocked_qty")
    reserved = _number(row.get("reserved_qty", 0), "reserved_qty")
    if blocked + reserved > qty:
        raise ValueError("冻结与预占不能超过实物库存")
    return qty - blocked - reserved


def _stock(facts, store, sku):
    return _rows(facts, "inventory", store_id=store, sku_id=sku, stock_state="on_hand")


def _product(facts, sku):
    return _single(_rows(facts, "products", sku_id=sku), "商品")


def _config(facts, store, sku):
    return _single(_rows(facts, "store_products", store_id=store, sku_id=sku), "门店商品配置")


def _focus(facts, target):
    return _single([r for r in _stock(facts, target.get("store_id"), target.get("sku_id"))
                    if r.get("lot_id") == target.get("lot_id")], "目标在库批次")


def _event(key, kind, amount, direction, when, *, evidence_ref=None):
    return {"event_id": key, "event_type": kind, "amount": money(amount), "direction": direction,
            "event_date": when.isoformat() if isinstance(when, date) else when,
            "certainty": "estimated", "evidence_ref": evidence_ref}


def simulate_cash(baseline_events, proposed_events, *, start_date, end_date):
    """Compare planned events in [start_date, end_date); never classify them as paid.

    An exact duplicate event is ignored; conflicting identities are rejected.
    Unknown amount/date preserves a partial known subtotal, not a fabricated zero.
    """
    start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
    if end <= start:
        raise ValueError("现金观察期无效")

    def total(events):
        incoming = outgoing = ZERO
        missing, seen = [], {}
        for event in events:
            event_id = event.get("event_id")
            if not event_id:
                raise ValueError("现金事件必须有唯一 event_id")
            if event_id in seen:
                if seen[event_id] != event:
                    raise ValueError("同一现金事件编号存在冲突内容")
                continue
            seen[event_id] = event
            if event.get("direction") not in ("in", "out"):
                raise ValueError("现金方向必须为 in 或 out")
            amount = _number(event.get("amount"), "cash.amount", optional=True)
            if amount == 0:
                continue
            when = parse_date(event.get("event_date"))
            if when is None:
                missing.append(f"{event_id}.event_date")
                continue
            if not start <= when < end:
                continue
            if amount is None:
                missing.append(f"{event_id}.amount")
            elif event["direction"] == "in":
                incoming += amount
            else:
                outgoing += amount
        return {"expected_cash_in": money(incoming) if not missing else None,
                "expected_cash_out": money(outgoing) if not missing else None,
                "expected_net_cash": money(incoming - outgoing) if not missing else None,
                "known_cash_in": money(incoming), "known_cash_out": money(outgoing),
                "missing_fields": missing, "completeness": "partial" if missing else "complete"}

    baseline, proposed = total(baseline_events), total(proposed_events)
    return {"baseline": baseline, "proposed": proposed,
            "incremental_net_cash_vs_baseline": money(proposed["expected_net_cash"] - baseline["expected_net_cash"])
            if proposed["expected_net_cash"] is not None and baseline["expected_net_cash"] is not None else None,
            "start_date": start.isoformat(), "end_date_exclusive": end.isoformat()}


def _candidate(key, kind):
    return {"strategy_id": key, "type": kind, "feasibility": "feasible", "blocking_reasons": [],
            "missing_fields": [], "assumptions": [], "allocations": [], "actions": [], "allocated_qty": ZERO,
            "expected_sold_qty": None, "expected_unsold_qty": None, "expected_sales_revenue": None,
            "expected_gross_profit": None, "execution_cost": ZERO, "settlement_timeline": [],
            "evidence_refs": [], "details": {}, "confidence_basis": "known_facts_and_explicit_demand_assumptions"}


def _finish(candidate, start, end, baseline_events=None):
    cash = simulate_cash(baseline_events or [], candidate["settlement_timeline"], start_date=start, end_date=end)
    candidate.update({k: cash["proposed"][k] for k in ("expected_cash_in", "expected_cash_out", "expected_net_cash")})
    candidate["cash_completeness"] = cash["proposed"]["completeness"]
    candidate["incremental_net_cash_vs_baseline"] = cash["incremental_net_cash_vs_baseline"] if baseline_events is not None else None
    candidate["missing_fields"] = list(dict.fromkeys(candidate["missing_fields"] + cash["proposed"]["missing_fields"]))
    candidate["blocking_reasons"] = list(dict.fromkeys(candidate["blocking_reasons"]))
    if candidate["blocking_reasons"]:
        candidate["feasibility"] = "blocked"
    elif candidate["missing_fields"]:
        candidate["feasibility"] = "needs_confirmation"
    if candidate["missing_fields"] or candidate["blocking_reasons"]:
        candidate["cash_completeness"] = "partial"
        for key in ("expected_cash_in", "expected_cash_out", "expected_net_cash", "incremental_net_cash_vs_baseline"):
            candidate[key] = None
    return candidate


def _allocation(row, qty):
    return {"store_id": row["store_id"], "sku_id": row["sku_id"], "lot_id": row["lot_id"], "quantity": qty}


def _supply(facts, store, sku, start):
    supply, missing = [], []
    for row in _stock(facts, store, sku):
        expiry = parse_date(row.get("sellable_until"))
        if expiry is None:
            missing.append(f"{row['lot_id']}.sellable_until")
            continue
        supply.append({"lot_id": row["lot_id"], "quantity": _available(row), "arrival": start,
                       "expiry": expiry, "unit_cost": _number(row.get("unit_cost"), "unit_cost")})
    seen = set()
    for shipment in _rows(facts, "in_transit", store_id=store, sku_id=sku):
        sid = shipment.get("shipment_line_id")
        if not sid or sid in seen:
            raise ValueError("在途明细 shipment_line_id 缺失或重复")
        seen.add(sid)
        if shipment.get("status") in ("cancelled", "completed", "received"):
            continue
        quantity = _number(shipment.get("shipped_qty"), "shipped_qty") - _number(shipment.get("received_qty"), "received_qty")
        if quantity < 0:
            raise ValueError("签收数量超过发货数量")
        arrival = parse_date(shipment.get("expected_arrival_at"))
        matching = _rows(facts, "inventory", shipment_line_id=sid, stock_state="in_transit")
        expiry = parse_date(matching[0].get("sellable_until")) if len(matching) == 1 else None
        if len(matching) == 1:
            if _number(matching[0]["quantity"], "quantity") != quantity:
                raise ValueError("在途库存与发运明细的未收数量不一致")
            quantity = _available(matching[0])
        if arrival is None or expiry is None:
            missing.append(f"{sid}.arrival_or_sellable_until")
            continue
        if arrival < start and quantity:
            missing.append(f"{sid}.overdue_arrival_requires_confirmation")
            continue
        if quantity:
            supply.append({"lot_id": shipment["lot_id"], "quantity": quantity, "arrival": max(start, arrival),
                           "expiry": expiry, "unit_cost": _number(shipment.get("unit_cost"), "unit_cost")})
    # An unshipped confirmed order is distinct from the shipped portion above.
    for order in _rows(facts, "purchase_orders", store_id=store, sku_id=sku):
        if order.get("order_status") in ("cancelled", "completed"):
            continue
        shipments = [r for r in _rows(facts, "in_transit", store_id=store, sku_id=sku)
                     if r.get("purchase_order_line_id") == order.get("po_line_id")]
        unshipped = (_number(order.get("ordered_qty"), "ordered_qty") - _number(order.get("received_qty", 0), "received_qty")
                     - sum((_number(r["shipped_qty"], "shipped_qty") - _number(r["received_qty"], "received_qty") for r in shipments), ZERO))
        if unshipped < 0:
            raise ValueError("订单与在途数量不一致")
        if unshipped:
            arrival = parse_date(order.get("expected_arrival_at"))
            expiry = parse_date(order.get("sellable_until"))
            if arrival is None or expiry is None:
                missing.append(f"{order['po_line_id']}.unshipped_arrival_or_sellable_until")
            else:
                supply.append({"lot_id": order["lot_id"], "quantity": unshipped, "arrival": max(start, arrival),
                               "expiry": expiry, "unit_cost": _number(order["unit_cost"], "unit_cost")})
    return supply, missing


def _simulate(facts, store, sku, start, end, *, remove=None, additions=(), suppressed_sales=()):
    supply, missing = _supply(facts, store, sku, start)
    remove = dict(remove or {})
    for row in supply:
        qty = min(row["quantity"], remove.get(row["lot_id"], ZERO))
        row["quantity"] -= qty
        remove[row["lot_id"]] = remove.get(row["lot_id"], ZERO) - qty
    if any(qty > 0 for qty in remove.values()):
        raise ValueError("移出数量超过可用库存")
    supply.extend(deepcopy(list(additions)))
    forecasts, calendar = {}, {}
    for row in _rows(facts, "demand_forecasts", store_id=store, sku_id=sku):
        day = _date(row.get("date"), "forecast.date")
        if day in forecasts:
            raise ValueError("同店同商品同日需求重复")
        forecasts[day] = row
    for row in _rows(facts, "store_calendar", store_id=store):
        day = _date(row.get("date"), "calendar.date")
        if day in calendar:
            raise ValueError("同店同日日历重复")
        calendar[day] = row
    sales, days, expired = [], [], ZERO
    for offset in range((end - start).days):
        day = start + timedelta(days=offset)
        cal, forecast = calendar.get(day), forecasts.get(day)
        suppressed = any(since <= day < until for since, until in suppressed_sales)
        if cal is None:
            missing.append(f"{store}.{day}.calendar")
        if not suppressed and (forecast is None or forecast.get("demand_base") is None):
            missing.append(f"{store}.{sku}.{day}.demand_base")
        demand = _number(forecast.get("demand_base"), "demand_base", optional=True) if forecast else None
        if cal and cal.get("is_open") is False:
            demand = ZERO
        if suppressed:
            demand = ZERO
        for row in supply:
            if row["arrival"] <= day and row["expiry"] <= day:
                expired += row["quantity"]
                row["quantity"] = ZERO
        current = [r for r in supply if r["arrival"] <= day < r["expiry"]]
        opening = sum((r["quantity"] for r in current), ZERO)
        remaining_demand = demand if demand is not None and cal is not None else ZERO
        for row in sorted(current, key=lambda r: r["expiry"]):
            sold = min(row["quantity"], remaining_demand)
            if sold:
                sales.append({"date": day, "lot_id": row["lot_id"], "quantity": sold, "cost": sold * row["unit_cost"]})
                row["quantity"] -= sold
                remaining_demand -= sold
        days.append({"date": day.isoformat(), "opening_qty": opening, "demand_qty": demand,
                     "closing_qty": sum((r["quantity"] for r in current), ZERO), "unmet_demand_qty": remaining_demand})
    return {"sales": sales, "days": days, "remaining_qty": sum((r["quantity"] for r in supply if r["arrival"] < end), ZERO),
            "unmet_demand_qty": sum((r["unmet_demand_qty"] for r in days), ZERO), "expired_qty": expired,
            "missing_fields": missing, "supply": supply}


def _sale_events(sales, price, lag, prefix):
    result = []
    for index, sale in enumerate(sales):
        when = sale["date"] + timedelta(days=int(lag)) if lag is not None else None
        result.append(_event(f"{prefix}:sale:{index}", "sales_receipt", sale["quantity"] * price, "in", when,
                             evidence_ref=sale["lot_id"]))
    return result


def _sales_result(candidate, sales, price, original, cost):
    sold = sum((r["quantity"] for r in sales), ZERO)
    candidate.update(expected_sold_qty=sold, expected_unsold_qty=original - sold,
                     expected_sales_revenue=money(sold * price), expected_gross_profit=money(sold * (price - cost)))


def _normal(facts, request, target, start, end):
    row = _focus(facts, target)
    product = _product(facts, target["sku_id"])
    result = _candidate("retain", "retain")
    sim = _simulate(facts, target["store_id"], target["sku_id"], start, end)
    sales = [r for r in sim["sales"] if r["lot_id"] == target["lot_id"]]
    price, cost = _number(product.get("regular_unit_price"), "regular_unit_price"), _number(row.get("unit_cost"), "unit_cost")
    _sales_result(result, sales, price, _available(row), cost)
    lag = _number(request.get("sales_settlement_days"), "sales_settlement_days", optional=True, integer=True)
    result["settlement_timeline"] = _sale_events(sales, price, lag, "retain")
    result["missing_fields"] = sim["missing_fields"]
    if sim["missing_fields"]:
        for field in ("expected_sold_qty", "expected_unsold_qty", "expected_sales_revenue", "expected_gross_profit"):
            result[field] = None
    result["evidence_refs"] = [row.get("inventory_id"), target["lot_id"]]
    result["details"] = {"projected_stock_by_day": sim["days"]}
    result["details"]["store_settlement_timeline"] = _sale_events(sim["sales"], price, lag, f"retain:{target['store_id']}")
    result["assumptions"] = ["逐日需求为明确情景假设，预计销量不代表已销售或已到账"]
    return _finish(result, start, end)


def _transfer(facts, request, target, start, end, route, baseline):
    row, product = _focus(facts, target), _product(facts, target["sku_id"])
    source, destination, sku = target["store_id"], route["to_store_id"], target["sku_id"]
    config, target_config = _config(facts, source, sku), _config(facts, destination, sku)
    result = _candidate(f"transfer:{destination}", "transfer")
    expiry = parse_date(row.get("sellable_until"))
    eta = int(_number(request.get("eta_days", route.get("eta_days")), "eta_days", integer=True))
    arrival = start + timedelta(days=eta)
    fee = _number(request.get("transport_fee", route.get("fee_amount")), "transport_fee", optional=True)
    source_available = sum((_available(r) for r in _stock(facts, source, sku)), ZERO)
    send_limit = min(_available(row), max(ZERO, source_available - _number(config.get("safety_stock_qty"), "source.safety_stock_qty")))
    target_sim = _simulate(facts, destination, sku, start, min(end, expiry) if expiry and expiry > start else end)
    net_demand = target_sim["unmet_demand_qty"] + max(ZERO, _number(target_config.get("safety_stock_qty"), "target.safety_stock_qty") - target_sim["remaining_qty"])
    arrival_day = next((r for r in target_sim["days"] if r["date"] == arrival.isoformat()), None)
    calendar = _rows(facts, "store_calendar", store_id=destination, date=arrival.isoformat())
    receiving = calendar[0] if len(calendar) == 1 else {}
    capacity = _number(receiving.get("capacity_override") if receiving.get("capacity_override") is not None else target_config.get("capacity_qty"), "capacity_qty")
    capacity_left = max(ZERO, capacity - (arrival_day["opening_qty"] if arrival_day else ZERO))
    trip_limit = _number(route.get("max_qty_per_trip"), "max_qty_per_trip")
    limit = max(ZERO, min(send_limit, net_demand, capacity_left, trip_limit)).to_integral_value(rounding=ROUND_FLOOR)
    quantity = _number(request.get("quantity", limit), "quantity", integer=True)
    reasons = result["blocking_reasons"]
    if quantity <= 0:
        reasons.append("没有满足安全库存及接收需求的可调数量")
    if quantity > limit:
        reasons.append("调拨数量超出源店安全量、接收净需求、容量或单趟限制")
    if route.get("applicable_sku_id") != sku or route.get("quantity_unit") != product.get("base_unit"):
        reasons.append("路线报价不适用于该商品或计量单位")
    if route.get("storage_condition") != product.get("storage_condition") or target_config.get("storage_condition") != product.get("storage_condition"):
        reasons.append("路线或接收店存储条件不匹配")
    if not (_date(route.get("valid_from"), "route.valid_from") <= arrival < _date(route.get("valid_to"), "route.valid_to")):
        reasons.append("路线报价已不在有效期")
    if not receiving.get("is_open") or not receiving.get("can_receive") or not target_config.get("can_receive_transfer") or not target_config.get("is_listed"):
        reasons.append("预计到货日门店闭店、不能收货或商品未上架")
    if expiry is None:
        result["missing_fields"].append("sellable_until")
    elif arrival >= expiry or (expiry - arrival).days < _number(target_config.get("min_receive_sellable_days"), "min_receive_sellable_days"):
        reasons.append("到货后剩余可售时间不满足要求")
    if arrival >= end:
        reasons.append("到货已超出本次评估周期")
    result["missing_fields"].extend(target_sim["missing_fields"])
    result["details"] = {"target_store_id": destination, "arrival_date": arrival.isoformat(), "route_id": route.get("route_id"),
                         "available_to_transfer": send_limit, "target_net_demand": net_demand,
                         "receiving_capacity": capacity_left, "max_quantity": limit, "transport_fee": money(fee)}
    result["evidence_refs"] = [route.get("route_id"), row.get("inventory_id"), target["lot_id"]]
    if reasons or expiry is None:
        return _finish(result, start, end, baseline["settlement_timeline"])
    cost = _number(row.get("unit_cost"), "unit_cost")
    source_sim = _simulate(facts, source, sku, start, end, remove={target["lot_id"]: quantity})
    received_sim = _simulate(facts, destination, sku, start, end, additions=[
        {"lot_id": target["lot_id"], "quantity": quantity, "arrival": arrival, "expiry": expiry, "unit_cost": cost}])
    for day in received_sim["days"]:
        cal = _rows(facts, "store_calendar", store_id=destination, date=day["date"])
        daily_capacity = cal[0].get("capacity_override") if cal else None
        if day["opening_qty"] > _number(daily_capacity if daily_capacity is not None else target_config["capacity_qty"], "capacity_qty"):
            reasons.append("调拨后某日库存超过接收容量")
    source_sales = [r for r in source_sim["sales"] if r["lot_id"] == target["lot_id"]]
    target_sales = [r for r in received_sim["sales"] if r["lot_id"] == target["lot_id"]]
    price = _number(product.get("regular_unit_price"), "regular_unit_price")
    _sales_result(result, source_sales + target_sales, price, _available(row), cost)
    lag = _number(request.get("sales_settlement_days"), "sales_settlement_days", optional=True, integer=True)
    result["settlement_timeline"] = _sale_events(source_sales, price, lag, result["strategy_id"] + ":source")
    target_events = _sale_events(target_sales, price, lag, result["strategy_id"] + ":target")
    result["settlement_timeline"].extend(target_events)
    result["settlement_timeline"].append(_event(f"{result['strategy_id']}:freight", "transport_fee", fee, "out", arrival, evidence_ref=route.get("route_id")))
    result["allocated_qty"] = quantity
    result["allocations"] = [_allocation(row, quantity)]
    result["actions"] = [{"type": "transfer", **_allocation(row, quantity), "source_store_id": source,
                           "unit_cost": money(cost), "target_store_id": destination,
                           "route_id": route.get("route_id"), "arrival_date": arrival.isoformat(), "transport_fee": money(fee)}]
    result["execution_cost"] = money(fee)
    result["missing_fields"].extend(source_sim["missing_fields"] + received_sim["missing_fields"])
    if source_sim["missing_fields"] or received_sim["missing_fields"]:
        for field in ("expected_sold_qty", "expected_unsold_qty", "expected_sales_revenue", "expected_gross_profit"):
            result[field] = None
    result["details"].update(source_projected_stock_by_day=source_sim["days"], target_projected_stock_by_day=received_sim["days"],
                             target_expected_sold_qty=sum((r["quantity"] for r in target_sales), ZERO),
                             target_settlement_timeline=target_events)
    result["assumptions"] = ["内部调拨不产生现金；回款基于逐日需求与明确结算周期估算", "候选方案分别比较，不能将互斥候选的收益相加"]
    result = _finish(result, start, end, baseline["settlement_timeline"])
    target_baseline = target_sim if not expiry or expiry >= end else _simulate(facts, destination, sku, start, end)
    pair_baseline = baseline["details"]["store_settlement_timeline"] + _sale_events(target_baseline["sales"], price, lag, f"baseline:{destination}")
    pair_proposed = (_sale_events(source_sim["sales"], price, lag, f"proposed:{source}")
                     + _sale_events(received_sim["sales"], price, lag, f"proposed:{destination}")
                     + [e for e in result["settlement_timeline"] if e["event_type"] == "transport_fee"])
    comparison = simulate_cash(pair_baseline, pair_proposed, start_date=start, end_date=end)
    result["details"]["cash_comparison"] = comparison
    result["details"]["cash_comparison_scope"] = {"store_ids": [source, destination], "sku_id": sku, "all_existing_lots": True}
    result["details"]["target_store_baseline_timeline"] = _sale_events(target_baseline["sales"], price, lag, f"baseline:{destination}")
    result["details"]["target_store_proposed_timeline"] = _sale_events(received_sim["sales"], price, lag, f"proposed:{destination}")
    if result["feasibility"] == "feasible":
        result["incremental_net_cash_vs_baseline"] = comparison["incremental_net_cash_vs_baseline"]
    return result


def calculate_promotion(facts, request=None):
    """Calculate a shared-inventory, multi-stage bundle under explicit demand cases."""
    request = request or {}
    target, start, end = _scope(facts, request)
    stages = _rows(facts, "promotion_stages", store_id=target["store_id"])
    if request.get("promotion_id"):
        stages = [s for s in stages if s.get("promotion_id") == request["promotion_id"]]
    result = _candidate("promotion", "promotion")
    if not stages:
        result["missing_fields"] = ["promotion_stages"]
        return _finish(result, start, end)
    promotion_ids = {s["promotion_id"] for s in stages}
    if len(promotion_ids) != 1 or len({s["bundle_id"] for s in stages}) != 1:
        raise ValueError("必须明确选择一个促销活动和组合")
    stages = sorted(stages, key=lambda s: _date(s["start_date"], "start_date"))
    parts = _rows(facts, "bundle_items", bundle_id=stages[0]["bundle_id"])
    if not parts or len({p["sku_id"] for p in parts}) != len(parts):
        raise ValueError("促销组成缺失或商品重复")
    if target.get("sku_id") not in {p["sku_id"] for p in parts}:
        result["blocking_reasons"].append("所选商品不属于该促销组合")
    prices = request.get("stage_prices", {})
    if not isinstance(prices, dict) or set(prices) - {s["stage_id"] for s in stages}:
        raise ValueError("stage_prices 必须引用当前活动的阶段")
    last_end = None
    activity_end = max(_date(s["end_date_exclusive"], "end_date_exclusive") for s in stages)
    activity_start = _date(stages[0]["start_date"], "start_date")
    if activity_start < start or activity_end > end:
        result["blocking_reasons"].append("活动阶段必须完整位于本次观察期内")
    bundle_cost = ZERO
    component_stocks = []
    cap = min(_number(s["available_bundle_qty"], "available_bundle_qty", integer=True) for s in stages)
    for part in parts:
        product = _product(facts, part["sku_id"])
        if part.get("base_unit") != product.get("base_unit"):
            raise ValueError("组合商品单位与主数据不一致")
        multiplier = _number(part.get("qty_per_bundle"), "qty_per_bundle", integer=True)
        if multiplier <= 0:
            raise ValueError("组合商品用量必须大于零")
        stocks = []
        for row in _stock(facts, target["store_id"], part["sku_id"]):
            expiry = parse_date(row.get("sellable_until"))
            if expiry is None:
                result["missing_fields"].append(f"{row['lot_id']}.sellable_until")
            elif expiry >= activity_end:
                stocks.append(row)
        stocks.sort(key=lambda r: r["sellable_until"])
        available = sum((_available(r) for r in stocks), ZERO)
        cap = min(cap, (available / multiplier).to_integral_value(rounding=ROUND_FLOOR))
        # A bundle has one cost rule; heterogeneous costs require a separate lot plan.
        costs = {_number(r["unit_cost"], "unit_cost") for r in stocks if _available(r)}
        if len(costs) > 1:
            result["missing_fields"].append(f"{part['sku_id']}.lot_cost_allocation")
        bundle_cost += (max(costs) if costs else _number(part["unit_cost"], "unit_cost")) * multiplier
        component_stocks.append((part, stocks, multiplier))
    requested = _number(request.get("quantity", cap), "quantity", integer=True)
    if requested <= 0 or requested > cap:
        result["blocking_reasons"].append("促销组数必须大于零且不超过组件库存与活动共享上限")
    limit = min(requested, cap)
    prepared, fees = [], ZERO
    for stage in stages:
        since = _date(stage["start_date"], "stage.start_date")
        until = _date(stage["end_date_exclusive"], "stage.end_date_exclusive")
        if until <= since or (last_end and since < last_end):
            result["blocking_reasons"].append("促销阶段日期无效或重叠")
        last_end = until
        price = _number(prices.get(stage["stage_id"], stage.get("bundle_price")), "bundle_price")
        floor = _number(stage.get("floor_price"), "floor_price")
        margin = _number(stage.get("min_margin_pct"), "min_margin_pct")
        if margin >= 100:
            raise ValueError("最低毛利率必须小于 100%")
        minimum = max(floor, (bundle_cost / (ONE - margin / 100)).quantize(Decimal("0.01"), rounding=ROUND_CEILING))
        if price < minimum:
            result["blocking_reasons"].append(f"{stage['stage_id']} 价格低于底价或毛利下限 {minimum}")
        fee = _number(stage.get("execution_fee"), "execution_fee")
        fees += fee
        prepared.append({**stage, "price": price, "minimum_price": minimum, "fee": fee, "since": since, "until": until})
    lag = _number(request.get("sales_settlement_days"), "sales_settlement_days", optional=True, integer=True)
    scenarios = {}
    for demand_case in ("low", "base", "high"):
        remaining, sold, revenue = limit, ZERO, ZERO
        entries, timeline = [], []
        for stage in prepared:
            demand = _number(stage.get(f"demand_{demand_case}"), f"demand_{demand_case}", optional=True)
            if demand is None:
                result["missing_fields"].append(f"{stage['stage_id']}.demand_{demand_case}")
                amount = None
            else:
                amount = min(remaining, demand)
                remaining -= amount
                sold += amount
                revenue += amount * stage["price"]
                when = stage["until"] - timedelta(days=1) + timedelta(days=int(lag)) if lag is not None else None
                timeline.append(_event(f"{stage['stage_id']}:{demand_case}:sale", "sales_receipt", amount * stage["price"], "in", when,
                                       evidence_ref=stage.get("assumption_id")))
            entries.append({"stage_id": stage["stage_id"], "expected_sold_qty": amount, "bundle_price": money(stage["price"]),
                            "minimum_price": money(stage["minimum_price"]), "remaining_bundle_qty": remaining})
            if stage["fee"]:
                timeline.append(_event(f"{stage['stage_id']}:fee", "promotion_fee", stage["fee"], "out", stage["since"]))
        scenarios[demand_case] = {"stages": entries, "expected_sold_qty": sold, "expected_unsold_qty": remaining,
                                  "expected_sales_revenue": money(revenue), "expected_gross_profit": money(revenue - sold * bundle_cost),
                                  "settlement_timeline": timeline}
    result.update({k: v for k, v in scenarios["base"].items() if k != "stages"})
    result["allocated_qty"] = limit
    result["execution_cost"] = money(fees)
    for part, stocks, multiplier in component_stocks:
        needed = limit * multiplier
        for row in stocks:
            quantity = min(_available(row), needed)
            if quantity:
                result["allocations"].append(_allocation(row, quantity))
                needed -= quantity
    result["actions"] = [{"type": "promotion", "promotion_id": stages[0]["promotion_id"],
                           "store_id": target["store_id"], "sku_id": target["sku_id"], "lot_id": target["lot_id"],
                           "unit_cost": money(bundle_cost), "execution_fee": money(fees), "components": deepcopy(result["allocations"]),
                           "bundle_id": stages[0]["bundle_id"], "quantity": limit,
                           "stages": [{"stage_id": s["stage_id"], "start_date": s["since"].isoformat(),
                                       "end_date_exclusive": s["until"].isoformat(), "bundle_price": money(s["price"])} for s in prepared]}]
    result["details"] = {"bundle_cost": money(bundle_cost), "max_bundle_qty": cap, "demand_scenarios": scenarios}
    result["evidence_refs"] = list(dict.fromkeys(s.get("assumption_id") for s in stages))
    result["assumptions"] = ["三个需求情景为显式假设，不是统计置信区间", "阶段销量包含正常销售，不再叠加正常销量",
                             "修改价格后保持给定需求假设；缺少价格弹性证据，不推断销量提升", "阶段销售收款按阶段末日及给定结算天数估计"]
    return _finish(result, start, end)


def calculate_return(facts, request=None):
    """Keep contract eligibility, supplier acceptance and settlement separate."""
    request = request or {}
    target, start, end = _scope(facts, request)
    row = _focus(facts, target)
    product = _product(facts, target["sku_id"])
    terms = [r for r in _rows(facts, "return_terms", supplier_id=product["supplier_id"])
             if target["sku_id"] in str(r.get("sku_scope", "")).split(";")]
    result = _candidate("return", "return")
    if not terms:
        result["missing_fields"] = ["supplier_return_terms"]
        return _finish(result, start, end)
    term = _single(terms, "退供条款")
    mode = request.get("settlement_mode", facts.get("branch_id") if facts.get("branch_id") in ("cash_refund", "exchange", "payable_credit") else "cash_refund")
    confirmed = request.get("return_terms") or {}
    if not isinstance(confirmed, dict):
        raise ValueError("return_terms 必须为结构化字段")
    allowed_modes = term.get("allowed_settlement_modes", term.get("settlement_mode"))
    if not allowed_modes:
        result["missing_fields"].append("allowed_settlement_modes")
    elif mode not in str(allowed_modes).split(";"):
        result["blocking_reasons"].append("退供条款不允许所选结算方式")
    effective_from = parse_date(term.get("effective_from"))
    effective_to = parse_date(term.get("effective_to", term.get("return_deadline")))
    if effective_from is None or effective_to is None:
        result["missing_fields"].append("return_terms.effective_dates")
    elif not effective_from <= start <= effective_to:
        result["blocking_reasons"].append("退供条款未生效或已过期")
    if term.get("contract_allows_return") is False:
        result["blocking_reasons"].append("已确认条款不允许退供")
    if not term.get("term_id"):
        result["missing_fields"].append("return_terms.term_id")
    expiry = parse_date(row.get("sellable_until"))
    minimum_days = _number(term.get("min_remaining_shelf_life_days"), "min_remaining_shelf_life_days", optional=True)
    if minimum_days is None:
        result["missing_fields"].append("min_remaining_shelf_life_days")
    if expiry is None:
        result["missing_fields"].append("sellable_until")
    elif minimum_days is not None and (expiry - start).days < minimum_days:
        result["blocking_reasons"].append("退供申请不满足最低剩余可售期限")
    quantity = _number(request.get("quantity", _available(row)), "quantity", integer=True)
    ratio_cap = _number(term.get("max_return_ratio"), "max_return_ratio", optional=True)
    quantity_cap = _number(term.get("max_return_qty"), "max_return_qty", optional=True)
    if ratio_cap is not None and ratio_cap > 100:
        raise ValueError("退供比例不能超过 100%")
    if ratio_cap is None:
        result["missing_fields"].append("max_return_ratio")
    if quantity_cap is None:
        result["missing_fields"].append("max_return_qty")
    known_limits = [_available(row)]
    if quantity_cap is not None:
        known_limits.append(quantity_cap)
    if ratio_cap is not None:
        known_limits.append(_available(row) * ratio_cap / 100)
    maximum = min(known_limits)
    if quantity <= 0 or quantity > maximum:
        result["blocking_reasons"].append("退供数量超出可用库存或条款上限")
    for field in ("packaging_confirmed", "supplier_confirmed"):
        if confirmed.get(field) is not True:
            result["missing_fields"].append(field)
    refund_ratio = _number(confirmed.get("refund_ratio_pct"), "refund_ratio_pct", optional=True)
    match = re.fullmatch(r"原进货价的(\d+(?:\.\d+)?)%", str(term.get("refund_price_rule", "")))
    contract_ratio = _number(term.get("refund_pct"), "refund_pct", optional=True)
    if contract_ratio is None and match:
        contract_ratio = _number(match.group(1), "refund_ratio_pct")
    if refund_ratio is None:
        if contract_ratio is not None:
            refund_ratio = contract_ratio
        else:
            result["missing_fields"].append("refund_ratio_pct")
    if refund_ratio is not None and refund_ratio > 100:
        raise ValueError("退款比例不能超过原进货价 100%")
    if contract_ratio is not None and refund_ratio is not None and refund_ratio > contract_ratio:
        result["blocking_reasons"].append("退款比例超过已发布条款；应先确认并更新条款事实")
    restocking = _number(confirmed.get("restocking_fee", term.get("restocking_fee_cny", term.get("restocking_fee_rule"))), "restocking_fee", optional=True)
    freight = _number(confirmed.get("freight_fee", term.get("freight_fee_cny")), "freight_fee", optional=True)
    if term.get("freight_payer") == "supplier":
        freight = ZERO
    if freight is None:
        result["missing_fields"].append("freight_fee")
    if restocking is None:
        result["missing_fields"].append("restocking_fee")
    amount = money(quantity * _number(row["unit_cost"], "unit_cost") * refund_ratio / 100) if refund_ratio is not None else None
    acceptance = parse_date(confirmed.get("acceptance_date"))
    if acceptance is None:
        result["missing_fields"].append("acceptance_date")
    if acceptance and acceptance < start:
        raise ValueError("预计退货验收日期不能早于决策日期")
    settlement_days = _number(term.get("settlement_days"), "settlement_days", optional=True, integer=True)
    if settlement_days is None:
        result["missing_fields"].append("settlement_days")
    settlement = acceptance + timedelta(days=int(settlement_days)) if acceptance and settlement_days is not None else None
    result["allocated_qty"] = quantity
    result["allocations"] = [_allocation(row, quantity)]
    result["execution_cost"] = money(freight + restocking) if freight is not None and restocking is not None else None
    result["expected_unsold_qty"] = _available(row) - quantity
    result["actions"] = [{"type": "return", **_allocation(row, quantity), "supplier_id": product["supplier_id"],
                           "unit_cost": money(row["unit_cost"]),
                           "term_id": term.get("term_id"), "settlement_mode": mode, "expected_settlement_amount": amount,
                           "expected_acceptance_date": acceptance.isoformat() if acceptance else None,
                           "freight_fee": money(freight), "restocking_fee": money(restocking)}]
    result["settlement_timeline"] = [_event("return:freight", "return_freight", freight, "out", start),
                                     _event("return:restocking", "restocking_fee", restocking, "out", settlement)]
    baseline_events = None
    if mode == "cash_refund":
        result["settlement_timeline"].append(_event("return:refund", "supplier_refund", amount, "in", settlement, evidence_ref=term.get("source_ref")))
    elif mode == "exchange":
        result["details"]["non_cash_exchange_value"] = amount
        required = ("replacement_sku_id", "replacement_lot_id", "replacement_qty", "replacement_unit_cost", "cash_difference")
        absent = [key for key in required if confirmed.get(key) in (None, "")]
        result["missing_fields"].extend(absent)
        if not absent:
            _product(facts, confirmed["replacement_sku_id"])
            _single(_rows(facts, "lots", lot_id=confirmed["replacement_lot_id"], sku_id=confirmed["replacement_sku_id"]), "换入批次")
            replacement_qty = _number(confirmed["replacement_qty"], "replacement_qty", integer=True)
            replacement_cost = _number(confirmed["replacement_unit_cost"], "replacement_unit_cost")
            difference = _number(confirmed["cash_difference"], "cash_difference")
            if replacement_qty <= 0 or amount is None or money(replacement_qty * replacement_cost) != money(amount + difference):
                result["blocking_reasons"].append("换入数量或成本与结算价值及补款不一致")
            result["actions"][0].update(replacement_sku_id=confirmed["replacement_sku_id"],
                                          replacement_lot_id=confirmed["replacement_lot_id"], replacement_qty=replacement_qty,
                                          replacement_unit_cost=money(replacement_cost), cash_difference=money(difference))
            result["settlement_timeline"].append(_event("return:exchange_difference", "exchange_difference", difference, "out", settlement))
        result["assumptions"].append("换入商品只改变库存，明确补款计现金流出，不生成现金退款")
    elif mode == "payable_credit":
        result["details"]["potential_payable_credit"] = amount
        payable_id, applied_date = confirmed.get("payable_id"), parse_date(confirmed.get("credit_apply_date"))
        if not payable_id or applied_date is None:
            result["missing_fields"].append("payable_id_or_credit_apply_date")
        else:
            payable = _single(_rows(facts, "payables", payable_id=payable_id), "抵款应付单据")
            if payable.get("supplier_id") != product["supplier_id"]:
                raise ValueError("抵款应付供应商与退供供应商不匹配")
            outstanding = _number(payable["outstanding_amount"], "outstanding_amount")
            due = _date(payable["due_at"], "due_at")
            if settlement is None:
                result["missing_fields"].append("acceptance_date")
            elif applied_date < settlement or applied_date > due:
                result["blocking_reasons"].append("抵款生效须在结算后且不晚于原付款日")
            applied = min(outstanding, amount) if amount is not None else None
            baseline_events = [_event("return:payable", "purchase_payment", outstanding, "out", due, evidence_ref=payable_id)]
            result["settlement_timeline"].append(_event("return:payable", "purchase_payment", outstanding - applied if applied is not None else None,
                                                       "out", due, evidence_ref=payable_id))
            result["actions"][0].update(payable_id=payable_id, credit_apply_date=applied_date.isoformat(),
                                          applied_credit_amount=money(applied))
            result["details"].update(applied_credit_amount=money(applied),
                                     unused_credit_amount=money(amount - applied) if applied is not None else None,
                                     baseline_settlement_timeline=baseline_events)
        result["assumptions"].append("取得额度不产生现金收入；按明确关联应付和使用日估算少付款，未使用额度单列")
    result["details"].update(max_return_qty=maximum, settlement_mode=mode, conditional_settlement_amount=amount,
                             supplier_confirmed=confirmed.get("supplier_confirmed") is True)
    result["evidence_refs"] = [term.get("term_id"), term.get("source_ref"), row.get("inventory_id")]
    return _finish(result, start, end, baseline_events)


def calculate_purchase(facts, request=None):
    """Evaluate a purchase intention against dated supply, demand and lot multiples."""
    request = request or {}
    target, start, end = _scope(facts, request)
    intents = _rows(facts, "purchase_intents", store_id=target["store_id"], sku_id=target["sku_id"])
    result = _candidate("purchase", "purchase")
    supplied = request.get("purchase_intent", {})
    if not isinstance(supplied, dict):
        raise ValueError("purchase_intent 必须为结构化字段")
    if "intent_id" in supplied:
        intent_id = supplied["intent_id"]
        if not isinstance(intent_id, str) or not intent_id.strip():
            raise ValueError("purchase_intent.intent_id 必须为非空字符串")
        if set(supplied) != {"intent_id"}:
            raise ValueError("选择已确认采购意向时不能覆盖其金额或其他事实；应先确认并更新该意向")
        # A confirmed material adds a separately identified intention. Selection
        # resolves that exact published fact instead of copying model fields or
        # arbitrarily preferring the latest row for the same product/store.
        intent = _single([row for row in intents if row.get("intent_id") == intent_id], "指定采购意向")
    elif len(intents) > 1:
        result["allocated_qty"] = None
        result["missing_fields"] = ["purchase_intent.intent_id"]
        result["details"] = {"available_intent_ids": sorted(row["intent_id"] for row in intents)}
        return _finish(result, start, end)
    else:
        intent = {**(intents[0] if intents else {}), **supplied}
    required = ("quantity", "unit", "unit_cost", "expected_arrival_date", "payment_date", "supplier_id")
    result["missing_fields"] = [f"purchase_intent.{key}" for key in required if intent.get(key) in (None, "")]
    if result["missing_fields"]:
        return _finish(result, start, end)
    product = _product(facts, target["sku_id"])
    if any(intent.get(key) not in (None, target[key]) for key in ("store_id", "sku_id")):
        raise ValueError("采购意向的商品和门店必须与当前评估对象一致")
    if not _rows(facts, "suppliers", supplier_id=intent["supplier_id"]):
        raise ValueError("采购意向引用未知供应商")
    unit = intent["unit"]
    if unit == product.get("base_unit"):
        factor = ONE
    elif unit == product.get("purchase_unit"):
        factor = _number(product.get("units_per_purchase_unit"), "units_per_purchase_unit", integer=True)
        if factor <= 0:
            raise ValueError("采购单位换算必须大于零")
    else:
        raise ValueError("采购单位未与商品基础单位建立换算")
    original = _number(intent["quantity"], "quantity", integer=True) * factor
    cost = _number(intent["unit_cost"], "unit_cost") / factor
    arrival = _date(intent["expected_arrival_date"], "expected_arrival_date")
    payment = _date(intent["payment_date"], "payment_date")
    if arrival < start or payment < start:
        raise ValueError("拟采购的到货与付款日期不能早于决策日期")
    config = _config(facts, target["store_id"], target["sku_id"])
    policies = _rows(facts, "procurement_policy", store_id=target["store_id"], sku_id=target["sku_id"])
    policy = policies[0] if len(policies) == 1 else {}
    minimum = _number(policy.get("min_order_qty"), "min_order_qty", optional=True)
    multiple = _number(policy.get("order_multiple"), "order_multiple", optional=True)
    if minimum is None or multiple is None:
        result["missing_fields"].append("procurement_policy.min_order_qty_or_order_multiple")
    if multiple == 0:
        raise ValueError("订货倍数必须大于零")
    baseline = _simulate(facts, target["store_id"], target["sku_id"], start, end)
    result["missing_fields"].extend(baseline["missing_fields"])
    safety = _number(config["safety_stock_qty"], "safety_stock_qty")
    need = max(ZERO, baseline["unmet_demand_qty"] + safety - baseline["remaining_qty"])
    recommended = need.to_integral_value(rounding=ROUND_CEILING)
    if recommended and minimum is not None and multiple is not None:
        recommended = (max(recommended, minimum) / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
    quantity = _number(request.get("recommended_quantity", recommended), "recommended_quantity", integer=True)
    if quantity and ((minimum is not None and quantity < minimum) or (multiple is not None and quantity % multiple != 0)):
        result["blocking_reasons"].append("采购数量不满足最小起订量或订货倍数")
    if quantity < need:
        result["blocking_reasons"].append("采购后无法覆盖观察期需求及期末安全库存")
    if arrival >= end and quantity:
        result["blocking_reasons"].append("采购到货晚于本次观察期")
    addition = {"lot_id": "planned-purchase", "quantity": quantity, "arrival": arrival, "expiry": end, "unit_cost": cost}
    projected = _simulate(facts, target["store_id"], target["sku_id"], start, end, additions=[addition])
    if projected["unmet_demand_qty"]:
        result["blocking_reasons"].append("按预计到货时间仍存在期间缺货，不能仅看期末总量")
    capacity = _number(config["capacity_qty"], "capacity_qty")
    if any(day["opening_qty"] > capacity for day in projected["days"]):
        result["blocking_reasons"].append("拟采购到货后超过门店容量")
    original_amount, adjusted_amount = money(original * cost), money(quantity * cost)
    new_payment = _date(request.get("new_payment_date", payment), "new_payment_date")
    if new_payment < start:
        raise ValueError("新付款日期不能早于决策日期")
    baseline_events = [_event("purchase:payment", "purchase_payment", original_amount, "out", payment)]
    result["settlement_timeline"] = [_event("purchase:payment", "purchase_payment", adjusted_amount, "out", new_payment)]
    result["allocated_qty"] = quantity
    result["expected_unsold_qty"] = projected["remaining_qty"]
    result["actions"] = [{"type": "purchase", "store_id": target["store_id"], "sku_id": target["sku_id"],
                           "quantity": quantity, "unit": product["base_unit"], "unit_cost": money(cost),
                           "supplier_id": intent["supplier_id"], "expected_arrival_date": arrival.isoformat(),
                           "payment_date": new_payment.isoformat(), "intent_id": intent.get("intent_id")}]
    result["details"] = {"original_quantity": original, "recommended_quantity": recommended, "selected_quantity": quantity,
                         "net_purchase_requirement": need, "original_amount": original_amount, "adjusted_amount": adjusted_amount,
                         "quantity_payment_reduction": money((original - quantity) * cost),
                         "deferred_payment_amount": adjusted_amount if start <= payment < end <= new_payment else ZERO,
                         "new_purchase_expected_sold_qty": sum((sale["quantity"] for sale in projected["sales"] if sale["lot_id"] == "planned-purchase"), ZERO),
                         "new_purchase_ending_qty": quantity - sum((sale["quantity"] for sale in projected["sales"] if sale["lot_id"] == "planned-purchase"), ZERO),
                         "projected_store_ending_qty": projected["remaining_qty"],
                         "safety_stock_qty": safety, "projected_stock_by_day": projected["days"],
                         "baseline_settlement_timeline": baseline_events}
    result["evidence_refs"] = [intent.get("source_ref"), intent.get("intent_id")]
    result["assumptions"] = ["已付在途只计供给，不再次产生付款", "拟采购货物假设到货后在本观察期内可售，收货时需核对实际批次效期",
                             "付款差额是同周期原意向与建议的计划差额，尚未形成已确认节省"]
    if intent.get("intent_status") not in (None, "draft_unconfirmed", "draft", "intention"):
        result["missing_fields"].append("confirmed_order_change_permission_and_fee")
    return _finish(result, start, end, baseline_events)


def validate_combination(facts, candidates, strategy_ids):
    """Validate additive actions, never add independent full-batch alternative cash."""
    if not isinstance(strategy_ids, list) or not strategy_ids or len(strategy_ids) != len(set(strategy_ids)):
        raise ValueError("组合必须为非空、不重复的策略编号列表")
    indexed = {c["strategy_id"]: c for c in candidates}
    if any(key not in indexed for key in strategy_ids):
        raise ValueError("组合引用未知策略")
    used, errors, targets, settlements = defaultdict(lambda: ZERO), [], set(), {}
    procurements, promotions, credit_payables = set(), set(), set()
    for key in strategy_ids:
        candidate = indexed[key]
        if candidate["feasibility"] != "feasible":
            errors.append(f"{key} 尚不可执行")
        if candidate["type"] == "retain":
            errors.append("保留原店是比较基线，不能作为额外组合动作")
        for allocation in candidate["allocations"]:
            stock_key = (allocation["store_id"], allocation["sku_id"], allocation["lot_id"])
            used[stock_key] += _number(allocation["quantity"], "allocation.quantity")
        for action in candidate["actions"]:
            if action["type"] == "transfer":
                key = (action["target_store_id"], action["sku_id"])
                if key in targets:
                    errors.append("同店同商品接收需求被多个方案重复占用，需要联合重算")
                targets.add(key)
            elif action["type"] == "return":
                key = (action["store_id"], action["sku_id"], action["lot_id"])
                existing = settlements.get(key)
                if existing and existing["mode"] != action["settlement_mode"]:
                    errors.append("同一批货的退供结算分支互斥")
                total = (existing["quantity"] if existing else ZERO) + action["quantity"]
                limit = candidate["details"].get("max_return_qty")
                if limit is not None and total > limit:
                    errors.append("组合退供总量超过同批条款上限")
                settlements[key] = {"mode": action["settlement_mode"], "quantity": total}
                payable = action.get("payable_id")
                if payable and payable in credit_payables:
                    errors.append("同一应付款不能被多个退供方案重复抵扣")
                if payable:
                    credit_payables.add(payable)
            elif action["type"] == "purchase":
                key = (action["store_id"], action["sku_id"])
                if key in procurements:
                    errors.append("同店同商品采购需求不能被多个意向重复满足")
                procurements.add(key)
            elif action["type"] == "promotion":
                key = (action["store_id"], action["promotion_id"])
                if key in promotions:
                    errors.append("同一促销活动应统一阶段分配，不能重复创建")
                promotions.add(key)
    source_scopes = {(store, sku) for store, sku, _ in used}
    if source_scopes.intersection(targets):
        errors.append("组合存在相互调入调出的门店商品，需要统一网络时序重算")
    allocations = []
    for key, quantity in used.items():
        store, sku, lot = key
        available = sum((_available(r) for r in _stock(facts, store, sku) if r["lot_id"] == lot), ZERO)
        if quantity > available:
            errors.append(f"{store}/{sku}/{lot} 组合分配超过可用库存")
        allocations.append({"store_id": store, "sku_id": sku, "lot_id": lot, "quantity": quantity})
    return {"valid": not errors, "errors": errors, "allocations": allocations,
            "strategy_ids": strategy_ids, "expected_net_cash": None,
            "note": "组合金额需基于联合分配重新计算；独立候选已包含原店剩余销售，不能直接相加"}


def _combine(facts, request, children, start, end):
    """Recompute retained sales once after every selected action's reservation."""
    result = _candidate("combination", "combination")
    result["children"] = children
    check = validate_combination(facts, children, [c["strategy_id"] for c in children])
    result["allocations"] = check["allocations"]
    # Missing facts remain conditions; impossible quantities remain hard blocks.
    result["blocking_reasons"] = [e for e in check["errors"] if not e.endswith("尚不可执行")]
    for child in children:
        result["blocking_reasons"].extend(child["blocking_reasons"])
        result["missing_fields"].extend(child["missing_fields"])
        result["actions"].extend(child["actions"])
        result["evidence_refs"].extend(child["evidence_refs"])
    if result["blocking_reasons"]:
        return _finish(result, start, end)
    groups = defaultdict(dict)
    for allocation in result["allocations"]:
        groups[(allocation["store_id"], allocation["sku_id"])][allocation["lot_id"]] = allocation["quantity"]
    purchase_scopes = {(a["store_id"], a["sku_id"]) for a in result["actions"] if a["type"] == "purchase"}
    if purchase_scopes.intersection(groups):
        result["blocking_reasons"].append("同店同商品采购与处置不能相加；需要统一到货和需求规划")
        return _finish(result, start, end)
    baseline_events, source_events, retained = [], [], []
    lag = _number(request.get("sales_settlement_days"), "sales_settlement_days", optional=True, integer=True)
    for (store, sku), removed in groups.items():
        source_stock = sum((_available(r) for r in _stock(facts, store, sku)), ZERO)
        if any(a["type"] == "transfer" and a["store_id"] == store and a["sku_id"] == sku for a in result["actions"]):
            if source_stock - sum(removed.values(), ZERO) < _number(_config(facts, store, sku)["safety_stock_qty"], "safety_stock_qty"):
                result["blocking_reasons"].append("组合处置后调出店库存低于安全库存")
        before = _simulate(facts, store, sku, start, end)
        suppressed = []
        for action in result["actions"]:
            if action["type"] == "promotion" and action["store_id"] == store and any(p["sku_id"] == sku for p in action["components"]):
                suppressed.extend((_date(s["start_date"], "start_date"), _date(s["end_date_exclusive"], "end_date_exclusive")) for s in action["stages"])
        after = _simulate(facts, store, sku, start, end, remove=removed, suppressed_sales=suppressed)
        price = _number(_product(facts, sku)["regular_unit_price"], "regular_unit_price")
        # Include other lots of the affected SKU: a transferred early-expiry lot
        # may displace their sales; removing it may free demand at the origin.
        before_sales, after_sales = before["sales"], after["sales"]
        baseline_events.extend(_sale_events(before_sales, price, lag, f"baseline:{store}:{sku}"))
        source_events.extend(_sale_events(after_sales, price, lag, f"retained:{store}:{sku}"))
        result["missing_fields"].extend(before["missing_fields"] + after["missing_fields"])
        retained.append({"store_id": store, "sku_id": sku,
                         "expected_sold_qty": sum((s["quantity"] for s in after_sales), ZERO),
                         "expected_sales_revenue": money(sum((s["quantity"] for s in after_sales), ZERO) * price)})
    result["settlement_timeline"] = source_events
    fees = ZERO
    for child in children:
        if child["execution_cost"] is None:
            fees = None
        elif fees is not None:
            fees += child["execution_cost"]
        if child["type"] == "transfer":
            # The child's source sales assume only its own allocation. They are
            # replaced by the joint retained computation above, exactly once.
            events = child["details"].get("target_store_proposed_timeline", []) + [
                e for e in child["settlement_timeline"] if e["event_type"] == "transport_fee"]
            baseline_events.extend(child["details"].get("target_store_baseline_timeline", []))
        else:
            events = child["settlement_timeline"]
        result["settlement_timeline"].extend(deepcopy(events))
        baseline_events.extend(child["details"].get("baseline_settlement_timeline", []))
    result["execution_cost"] = money(fees)
    result["details"] = {"retained_sales": retained, "baseline_settlement_timeline": baseline_events,
                         "allocation_check": check}
    result["assumptions"] = ["联合分配后重新计算一次原店剩余销售，独立候选收入不直接相加",
                             "活动期组件销量使用促销总需求，未分配库存不额外叠加正常销售；活动外恢复正常需求",
                             "多 SKU 的件、袋、瓶数量分别列于 allocations，不合为一个误导性数量"]
    result["allocated_qty"] = None
    return _finish(result, start, end, baseline_events)


def calculate_combination(facts, request):
    """request.combination contains explicit independently sized action inputs.

    Example: [{"type":"transfer","target_store_id":"ST-002","quantity":40},
              {"type":"transfer","target_store_id":"ST-004","quantity":20}].
    Allocation and receiving-demand conflicts are rejected before cash aggregation.
    """
    specs = request.get("combination")
    if not isinstance(specs, list) or not specs or len(specs) > 20:
        raise ValueError("combination 必须包含 1 至 20 个动作")
    _, start, end = _scope(facts, request)
    shared = {k: v for k, v in request.items() if k not in ("combination", "strategy_ids", "quantity", "target_store_id")}
    children = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise ValueError("组合动作必须为对象")
        inputs = {**shared, **spec}
        target, child_start, child_end = _scope(facts, inputs)
        if child_start != start or child_end != end:
            raise ValueError("组合子动作必须使用同一观察期")
        kind = spec.get("type")
        if kind == "transfer":
            route = _single(_rows(facts, "routes", from_store_id=target["store_id"], to_store_id=inputs.get("target_store_id")), "组合调拨路线")
            child = _transfer(facts, inputs, target, start, end, route, _normal(facts, inputs, target, start, end))
        elif kind == "promotion":
            child = calculate_promotion(facts, inputs)
        elif kind == "return":
            child = calculate_return(facts, inputs)
        elif kind == "purchase":
            child = calculate_purchase(facts, inputs)
        else:
            raise ValueError("组合只支持 transfer/promotion/return/purchase")
        child["strategy_id"] = f"combination:{index}:{child['strategy_id']}"
        # Stable per-action namespaces prevent accidental merging of separate
        # fees or receipts when identical event types occur in a combination.
        for event in child["settlement_timeline"]:
            event["event_id"] = f"child:{index}:{event['event_id']}"
        for event in child["details"].get("baseline_settlement_timeline", []):
            event["event_id"] = f"child:{index}:{event['event_id']}"
        for field in ("target_store_baseline_timeline", "target_store_proposed_timeline"):
            for event in child["details"].get(field, []):
                event["event_id"] = f"child:{index}:{event['event_id']}"
        children.append(child)
    return _combine(facts, request, children, start, end)


def compare_options(facts, request=None):
    """Return a common retain baseline and finite, separately calculated choices.

    request can set quantity, target_store_id, transport_fee, eta_days,
    sales_settlement_days, stage_prices, return_terms or purchase_intent.  These
    are scenario assumptions/confirmed user inputs, never future replay events.
    """
    request = request or {}
    target, start, end = _scope(facts, request)
    baseline = _normal(facts, request, target, start, end)
    candidates = [baseline]
    routes = _rows(facts, "routes", from_store_id=target["store_id"])
    if request.get("target_store_id"):
        routes = [r for r in routes if r["to_store_id"] == request["target_store_id"]]
    for route in routes:
        candidates.append(_transfer(facts, request, target, start, end, route, baseline))
    if request.get("target_store_id") and not routes:
        candidate = _candidate(f"transfer:{request['target_store_id']}", "transfer")
        candidate["missing_fields"] = ["applicable_transfer_route"]
        candidates.append(_finish(candidate, start, end, baseline["settlement_timeline"]))
    promotion = calculate_promotion(facts, request)
    candidates.append(promotion)
    returned = calculate_return(facts, request)
    candidates.append(returned)
    if _rows(facts, "purchase_intents", store_id=target["store_id"], sku_id=target["sku_id"]) or request.get("purchase_intent"):
        candidates.append(calculate_purchase(facts, request))
    baseline["incremental_net_cash_vs_baseline"] = ZERO if baseline["feasibility"] == "feasible" else None
    for candidate in (promotion, returned):
        if candidate["allocations"]:
            comparison = _combine(facts, request, [candidate], start, end)
            candidate["details"]["cash_comparison"] = {
                "expected_net_cash": comparison["expected_net_cash"],
                "baseline_settlement_timeline": comparison["details"].get("baseline_settlement_timeline", []),
                "proposed_settlement_timeline": comparison["settlement_timeline"],
                "incremental_net_cash_vs_baseline": comparison["incremental_net_cash_vs_baseline"]}
            candidate["incremental_net_cash_vs_baseline"] = comparison["incremental_net_cash_vs_baseline"]
    # Compare the change against each affected scope's no-action baseline.
    # Unaffected stores/products cancel out; raw bundle and single-lot receipts
    # cannot be ranked directly because their scopes differ.
    ranked = [c for c in candidates if c["feasibility"] == "feasible" and c["incremental_net_cash_vs_baseline"] is not None]
    ranked.sort(key=lambda c: (-c["incremental_net_cash_vs_baseline"], c["allocated_qty"], c["strategy_id"]))
    result = {key: facts.get(key) for key in ("dataset_id", "snapshot_id", "scenario_id", "branch_id", "clock_at", "data_version")}
    result.update(target=target, evaluation_end=end.isoformat(), baseline=baseline, candidates=candidates,
                  recommended_strategy_id=ranked[0]["strategy_id"] if ranked else None,
                  recommendation_scope="affected_stock_and_payment_scopes_same_horizon",
                  recommendation_note="有限候选按各自受影响范围的同周期基线净现金差比较；组合纳入全部组件，不宣称全局最优")
    if request.get("strategy_ids") is not None:
        check = validate_combination(facts, candidates, request["strategy_ids"])
        result["combination"] = _combine(facts, request, [c for c in candidates if c["strategy_id"] in check["strategy_ids"]], start, end)
        candidates.append(result["combination"])
    if request.get("combination") is not None:
        if request.get("strategy_ids") is not None:
            raise ValueError("组合输入与候选编号选择不能同时提供")
        result["combination"] = calculate_combination(facts, request)
        candidates.append(result["combination"])
    return result
