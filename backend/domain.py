"""纯领域计算：不依赖 HTTP、数据库或模型凭证。

本模块刻意把金额、证据和方案约束放在确定性代码中，Agent 只能调用这些能力，
不能用一段自然语言直接覆盖业务事实。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP, ROUND_UP
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MONEY_QUANT = Decimal("0.01")
TEACHER_BASELINE_VERSION = "teacher-v1"
TEACHER_LEVEL_SET = frozenset({"A", "B", "C", "D", "Z", "H"})
TEACHER_STOP_VALUES = frozenset({"停采", "停止采购", "停售", "停购"})


def money(value: Any) -> Optional[Decimal]:
    """把金额转为两位 Decimal；未知值保持 None。"""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def dec(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def round_up(value: Decimal, places: int) -> Decimal:
    """复刻 Excel ROUNDUP：非零值始终远离零点取整。"""
    return value.quantize(Decimal("1").scaleb(-places), rounding=ROUND_UP)


def compare_sales(local_sales: int, comparison_sales: Sequence[int]) -> Dict[str, Any]:
    """计算同规格、同单位门店的可复核差异，不推断原因。"""
    values = [int(v) for v in comparison_sales if v is not None]
    result: Dict[str, Any] = {
        "local_sales": int(local_sales),
        "comparison_values": values,
        "comparison_count": len(values),
        "comparison_median": None,
        "difference_percent": None,
        "evidence_level": "insufficient",
        "missing_fields": [],
        "formula": "median(comparison_sales) - local_sales / median(comparison_sales)",
    }
    if not values:
        result["missing_fields"] = ["comparison_sales"]
        return result
    comparison_median = Decimal(str(median(values)))
    result["comparison_median"] = float(comparison_median)
    if comparison_median == 0:
        result["missing_fields"] = ["non_zero_comparison_denominator"]
        return result
    difference = ((comparison_median - Decimal(local_sales)) / comparison_median * Decimal(100)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    result["difference_percent"] = float(difference)
    result["evidence_level"] = "sufficient"
    return result


def teacher_baseline(
    row: Dict[str, Any],
    *,
    target_ratio: Any = 3,
    allowed_levels: Sequence[str] = tuple(sorted(TEACHER_LEVEL_SET)),
) -> Dict[str, Any]:
    """按老师口径计算一条门店商品的基线和降库存候选。

    该函数只做确定性计算，不做预测、评分或优化。缺少关键字段时返回
    ``status=blocked``，避免把未知销量静默当成零销量。
    """
    ratio = dec(target_ratio)
    missing: List[str] = []

    inventory_amount = money(row.get("available_inventory_amount"))
    if inventory_amount is None:
        inventory_amount = money(row.get("inventory_amount"))
    if inventory_amount is None:
        missing.append("inventory_amount")

    inventory_qty = dec(row.get("inventory_qty"))
    if inventory_qty is None:
        inventory_qty = dec(row.get("available_qty"))
    if inventory_qty is None:
        missing.append("inventory_qty")

    sales_30 = dec(row.get("sales_30"))
    if sales_30 is None:
        missing.append("sales_30")

    sales_cost_30 = money(row.get("sales_cost_30"))
    if sales_cost_30 is None:
        missing.append("sales_cost_30")

    sales_90 = dec(row.get("sales_90"))
    if sales_90 is None:
        missing.append("sales_90")

    level = str(row.get("stat_class") or row.get("classification") or "").strip()
    if not level:
        missing.append("stat_class")

    purchase_status = str(row.get("purchase_status") or "").strip()
    has_stock = inventory_qty is not None and inventory_qty > 0

    if ratio is None or ratio <= 0:
        missing.append("target_ratio")

    result: Dict[str, Any] = {
        "calculation_version": TEACHER_BASELINE_VERSION,
        "status": "blocked" if missing else "calculated",
        "eligible": False,
        "candidate": False,
        "missing_fields": list(dict.fromkeys(missing)),
        "stat_class": level or None,
        "monthly_sales": None,
        "teacher_ratio": None,
        "reduction_ratio": None,
        "stockout": None,
        "near_stockout": None,
        "target_ratio": float(ratio) if ratio is not None else None,
        "target_inventory_amount": None,
        "suggested_reduction_amount": None,
        "reference_reduction_quantity": None,
        "priority": None,
        "trigger_reason": None,
    }
    if missing:
        return result

    assert inventory_amount is not None
    assert inventory_qty is not None
    assert sales_30 is not None
    assert sales_cost_30 is not None
    assert sales_90 is not None
    assert ratio is not None

    # 教程基线：先将 90 天销量除以 3 向上取一位小数，再用较大的 30 天销量
    # 或月均销量作分母；最终存销比向上取两位小数。
    sales_30 = max(sales_30, Decimal("0"))
    sales_90 = max(sales_90, Decimal("0"))
    monthly_sales = round_up(sales_90 / Decimal("3"), 1)
    denominator = max(sales_30, monthly_sales)
    if inventory_qty == 0:
        teacher_ratio = Decimal("0")
    elif denominator > 0:
        teacher_ratio = round_up(inventory_qty / denominator, 2)
    else:
        teacher_ratio = Decimal("9999")

    # 降库存存销比与老师口径存销比是两件事：前者以金额/成本衡量。
    reduction_ratio = (
        inventory_amount / sales_cost_30
        if inventory_amount > 0 and sales_cost_30 > 0
        else Decimal("9999") if inventory_amount > 0
        else Decimal("0")
    )
    target_inventory_amount = (sales_cost_30 * ratio).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    suggested_reduction = max(inventory_amount - target_inventory_amount, Decimal("0")).quantize(
        MONEY_QUANT, rounding=ROUND_HALF_UP
    )
    unit_cost = inventory_amount / inventory_qty if inventory_qty > 0 else Decimal("0")
    if sales_cost_30 <= 0 and has_stock:
        reference_reduction_quantity = inventory_qty
    elif suggested_reduction > 0 and unit_cost > 0:
        reference_reduction_quantity = min(
            inventory_qty,
            (suggested_reduction / unit_cost).to_integral_value(rounding=ROUND_CEILING),
        )
    else:
        reference_reduction_quantity = Decimal("0")

    derived_near_stockout = teacher_ratio > 0 and teacher_ratio < Decimal("0.5")
    derived_stockout = sales_30 != 0 and inventory_qty == 0
    # 兼容已接入的显式缺货标记；当前示例源数据没有该列时使用老师公式重算。
    stockout = bool(row.get("stockout")) or derived_stockout
    near_stockout = bool(row.get("near_stockout")) or derived_near_stockout
    if purchase_status in TEACHER_STOP_VALUES:
        stockout = False

    eligible = (
        level in set(allowed_levels)
        and has_stock
        and not stockout
        and not near_stockout
    )
    priority: Optional[str] = None
    reason: Optional[str] = None
    candidate = eligible and (reduction_ratio > ratio or teacher_ratio >= Decimal("9999"))
    if candidate and sales_90 == 0 and purchase_status in TEACHER_STOP_VALUES:
        priority, reason = "P1", "停采且90天无销售"
    elif candidate and (reduction_ratio >= Decimal("9999") or teacher_ratio >= Decimal("9999")):
        priority, reason = "P1", "不动销（存销比=9999）"
    elif candidate and reduction_ratio > Decimal("3"):
        priority, reason = "P2", "降库存存销比超过3"
    elif candidate:
        priority, reason = "P3", "超过设定目标存销比"

    result.update(
        {
            "eligible": eligible,
            "candidate": candidate,
            "monthly_sales": float(monthly_sales),
            "teacher_ratio": float(teacher_ratio),
            "reduction_ratio": float(reduction_ratio),
            "stockout": stockout,
            "near_stockout": near_stockout,
            "target_inventory_amount": float(target_inventory_amount),
            "suggested_reduction_amount": float(suggested_reduction),
            "reference_reduction_quantity": float(reference_reduction_quantity),
            "priority": priority,
            "trigger_reason": reason,
        }
    )
    return result


def evidence_level(
    supporting_refs: Sequence[str],
    missing_fields: Sequence[str],
    conflicts: Sequence[str],
    required_fields: Sequence[str],
) -> str:
    """针对单个命题分级，而不是针对整张方案给置信度。"""
    if conflicts:
        return "insufficient"
    if not supporting_refs:
        return "insufficient"
    if missing_fields or any(field not in supporting_refs for field in required_fields):
        return "partial"
    return "sufficient"


def evidence_label(level: str) -> str:
    return {
        "sufficient": "证据充分",
        "partial": "部分支持",
        "insufficient": "信息不足",
    }.get(level, "信息不足")


def dedupe_attention_cost(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """滞销/近效期等标签覆盖同一批库存时按并集计一次成本。"""
    seen = set()
    total = Decimal("0")
    labels: Dict[str, int] = {}
    for item in items:
        key = item.get("lot_id") or item.get("stock_key")
        if key in seen:
            continue
        seen.add(key)
        qty = dec(item.get("quantity"))
        unit_cost = money(item.get("unit_cost"))
        if qty is None or unit_cost is None:
            continue
        total += qty * unit_cost
        for label in item.get("labels", []):
            labels[label] = labels.get(label, 0) + 1
    return {"amount": money(total), "covered_keys": list(seen), "labels": labels}


def cash_net(events: Iterable[Dict[str, Any]], cutoff: date) -> Optional[Decimal]:
    """计算截止日现金净流量；未知金额会使完整结果不可用。"""
    total = Decimal("0")
    seen = set()
    for event in events:
        event_key = event.get("event_id") or event.get("business_ref")
        if event_key and event_key in seen:
            continue
        if event_key:
            seen.add(event_key)
        event_date = parse_date(event.get("event_date"))
        amount = money(event.get("amount"))
        if event_date is None or amount is None:
            return None
        if event_date <= cutoff:
            total += amount if event.get("direction") == "in" else -amount
    return money(total)


def scenario_cash(
    baseline_events: Sequence[Dict[str, Any]],
    scenario_events: Sequence[Dict[str, Any]],
    cutoff: date,
    *,
    known_cash_effect: Optional[Decimal] = None,
    missing_fields: Optional[Sequence[str]] = None,
    assumptions: Optional[Sequence[str]] = None,
    baseline_id: str = "baseline-demo-v1",
    snapshot_id: str = "snapshot-demo-v1",
) -> Dict[str, Any]:
    baseline = cash_net(baseline_events, cutoff)
    scenario = cash_net(scenario_events, cutoff)
    missing = list(missing_fields or [])
    # 两边都没有事件时只能表达“未观测到现金事件”；一边有事实而另一边没有
    # 基准，不能把缺失基准当成 0。
    if not baseline_events and not scenario_events:
        baseline = Decimal("0")
        scenario = Decimal("0")
    if (not baseline_events and scenario_events) or (baseline is None or scenario is None):
        improvement: Optional[Decimal] = None
        completeness = "unavailable"
    else:
        improvement = money(scenario - baseline)
        completeness = "partial" if missing else "complete"
    return {
        "estimated_net_cash_improvement": improvement,
        "baseline_net_cash_flow": baseline,
        "scenario_net_cash_flow": scenario,
        "known_cash_effect": money(known_cash_effect),
        "completeness": completeness,
        "missing_fields": missing,
        "assumptions": list(assumptions or []),
        "horizon": cutoff.isoformat(),
        "baseline_id": baseline_id,
        "snapshot_id": snapshot_id,
        "cash_event_refs": list(dict.fromkeys(e.get("event_id") for e in scenario_events if e.get("event_id"))),
    }


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_feedback_dates(
    text: str, submitted_at: datetime, timezone: str = "Asia/Shanghai"
) -> Dict[str, Any]:
    """解析可安全确认的相对日期，保留模糊范围而不补造具体日期。"""
    # 首期只承诺客户样例所需的 Asia/Shanghai；不引入第三方时区包。
    tz = timezone if timezone == "Asia/Shanghai" else "UTC"
    local_submitted = submitted_at.astimezone(timezone_offset(tz))
    yesterday = local_submitted.date() - timedelta(days=1)
    result: Dict[str, Any] = {
        "relative_date": None,
        "relative_date_resolved": None,
        "uncertain_ranges": [],
        "needs_confirmation": True,
    }
    if "昨天" in text:
        result["relative_date"] = "昨天"
        result["relative_date_resolved"] = yesterday.isoformat()
    if "上个月" in text:
        month_start = (local_submitted.replace(day=1) - timedelta(days=1)).replace(day=1).date()
        next_month = (local_submitted.replace(day=1) - timedelta(days=1)).date()
        result["uncertain_ranges"].append(
            {"label": "上个月", "start": month_start.isoformat(), "end": next_month.isoformat()}
        )
    return result


def timezone_offset(name: str) -> timezone:
    return timezone(timedelta(hours=8 if name == "Asia/Shanghai" else 0))


def validate_action_bundle(
    actions: Sequence[Dict[str, Any]],
    *,
    available_by_lot: Dict[str, int],
    allowed_routes: Sequence[Tuple[str, str]],
    reserved_by_lot: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """统一检查组合方案，不让专家口头收益相加掩盖数量冲突。"""
    reserved = reserved_by_lot or {}
    used: Dict[str, int] = {}
    errors: List[str] = []
    for action in actions:
        lot_id = action.get("lot_id")
        quantity = int(action.get("quantity") or 0)
        allocation_key = "chain:%s" % action.get("chain_from_transfer_id") if action.get("chain_from_transfer_id") else lot_id
        used[allocation_key] = used.get(allocation_key, 0) + quantity
        if action.get("type") == "transfer":
            route = (action.get("source_store_id"), action.get("target_store_id"))
            if route not in allowed_routes:
                errors.append("路线不在允许范围内")
        if action.get("type") == "promo" and action.get("chain_from_transfer_id"):
            chain_qty = int(action.get("chain_available_quantity") or 0)
            if quantity > chain_qty:
                errors.append("促销数量超过关联调拨到货可用量")
    for lot_id, quantity in used.items():
        if str(lot_id).startswith("chain:"):
            action_id = str(lot_id).split(":", 1)[1]
            available = next((int(action.get("chain_available_quantity") or 0) for action in actions if action.get("chain_from_transfer_id") == action_id), 0)
        else:
            available = int(available_by_lot.get(lot_id, 0)) - int(reserved.get(lot_id, 0))
        if quantity > available:
            errors.append("同一批次动作占用数量超过可用量")
    return {"valid": not errors, "errors": errors, "used_by_lot": used}


def _integer(value: Any, default: int = 0) -> int:
    """边界层传入的数量统一向下收敛为非负整数。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _coverage(quantity: int, daily_sales: Optional[Decimal]) -> Optional[float]:
    if daily_sales is None or daily_sales <= 0:
        return None
    return float((Decimal(quantity) / daily_sales).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def calculate_transfer(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """调拨专用试算：只计算物流和库存约束，不把内部移动当成现金回款。"""
    quantity = _integer(input_data.get("quantity"))
    source_on_hand = _integer(input_data.get("source_on_hand"))
    source_safety = _integer(input_data.get("source_safety"))
    target_on_hand = _integer(input_data.get("target_on_hand"))
    target_capacity = _integer(input_data.get("target_capacity"))
    sellable_days = _integer(input_data.get("sellable_days"))
    eta_days = _integer(input_data.get("eta_days"))
    source_daily = dec(input_data.get("source_daily_sales"))
    target_daily = dec(input_data.get("target_daily_sales"))
    fee = money(input_data.get("transport_fee"))
    errors: List[str] = []
    if quantity <= 0:
        errors.append("调拨数量必须大于 0")
    available = max(0, source_on_hand - source_safety)
    receiving_capacity = max(0, target_capacity - target_on_hand)
    if quantity > available:
        errors.append("超出调出门店可调数量：需保留安全库存 %s 件" % source_safety)
    if quantity > receiving_capacity:
        errors.append("超出接收门店容量：最多还可接收 %s 件" % receiving_capacity)
    if sellable_days and eta_days >= sellable_days:
        errors.append("预计到货晚于或等于该批次可售截止，不能调拨")
    source_after = source_on_hand - quantity
    target_after = target_on_hand + quantity
    unit_cost = money(input_data.get("unit_cost")) or Decimal("0")
    source_sale_before_expiry = int((source_daily or Decimal("0")) * max(0, sellable_days))
    source_surplus_at_deadline = max(0, source_on_hand - source_safety - source_sale_before_expiry)
    target_sale_before_expiry = int((target_daily or Decimal("0")) * max(0, sellable_days - eta_days))
    transferable_sale_qty = min(quantity, target_sale_before_expiry)
    avoidable_loss_qty = min(source_surplus_at_deadline, transferable_sale_qty)
    potential_loss_without_transfer = money(Decimal(source_surplus_at_deadline) * unit_cost)
    avoided_loss = money(Decimal(avoidable_loss_qty) * unit_cost)
    net_avoidable_loss = money((avoided_loss or Decimal("0")) - (fee or Decimal("0")))
    return {
        "valid": not errors,
        "errors": errors,
        "allocation": {"lot_id": input_data.get("lot_id"), "quantity": quantity},
        "limits": {"available_to_transfer": available, "receiving_capacity": receiving_capacity},
        "before_after": {
            "source": {"store": input_data.get("source_store"), "on_hand_before": source_on_hand, "on_hand_after": source_after, "safety_stock": source_safety, "coverage_before": _coverage(source_on_hand, source_daily), "coverage_after": _coverage(source_after, source_daily), "expiry_risk": "正常" if not sellable_days else ("需关注" if sellable_days < 30 else "低")},
            "target": {"store": input_data.get("target_store"), "on_hand_before": target_on_hand, "on_hand_after": target_after, "safety_stock": _integer(input_data.get("target_safety")), "coverage_before": _coverage(target_on_hand, target_daily), "coverage_after": _coverage(target_after, target_daily), "expiry_risk": "需关注" if sellable_days and eta_days + 7 >= sellable_days else "低"},
        },
        "cash": {
            "inventory_cost": money(Decimal(quantity) * unit_cost),
            "estimated_net_cash_improvement": None,
            "known_cash_effect": money(-(fee or Decimal("0"))),
            "avoided_loss": None,
            "completeness": "unavailable",
            "missing_fields": ["target_store_future_sales_receipts"],
            "note": "内部调拨不产生现金释放；仅已知运输费用计入现金影响。",
        },
        "economic": {
            "potential_loss_without_transfer": potential_loss_without_transfer,
            "source_surplus_at_deadline_qty": source_surplus_at_deadline,
            "target_sale_before_expiry_qty": transferable_sale_qty,
            "avoided_loss": avoided_loss,
            "transport_fee": fee,
            "net_avoidable_loss": net_avoidable_loss,
            "note": "这是按当前销量与可售天数估算的避免报损，不是已实现利润或现金回款。",
        },
    }


def calculate_expiry_rescue(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """近效期处置的数量守恒试算。促销不臆造价格弹性或销量提升。"""
    inventory = _integer(input_data.get("inventory_qty"))
    sellable_days = _integer(input_data.get("sellable_days"))
    sales_30 = _integer(input_data.get("sales_30"))
    transfer_qty = _integer(input_data.get("transfer_qty"))
    promo_qty = _integer(input_data.get("promo_qty"))
    return_qty = _integer(input_data.get("return_qty"))
    promo_price = money(input_data.get("promo_price"))
    promo_fee = money(input_data.get("promo_fee")) or Decimal("0")
    unit_cost = money(input_data.get("unit_cost")) or Decimal("0")
    normal_sale = min(inventory, int(Decimal(sellable_days) * Decimal(sales_30) / Decimal(30)))
    total_handling = transfer_qty + promo_qty + return_qty
    errors: List[str] = []
    if total_handling + normal_sale > inventory:
        errors.append("正常预计销售与处置数量合计超过本批次库存，不能重复占用")
    if promo_qty and promo_price is None:
        errors.append("促销数量已填写，但缺少审核后的促销价格")
    remaining = max(0, inventory - normal_sale - total_handling)
    assumptions: List[str] = []
    missing = ["price_sales_elasticity", "supplier_return_terms"]
    if promo_qty:
        assumptions.append("促销数量为待确认投放量，不代表销量一定提升")
    if transfer_qty:
        assumptions.append("调拨后销量与回款尚未取得，不能算作现金释放")
    return {
        "valid": not errors,
        "errors": errors,
        "allocation": {"lot_id": input_data.get("lot_id"), "quantity": total_handling},
        "forecast": {"normal_sale_qty": normal_sale, "transfer_qty": transfer_qty, "promo_qty": promo_qty, "return_qty": return_qty, "expected_remaining_qty": remaining, "latest_disposal_date": input_data.get("latest_disposal_date"), "sellable_days": sellable_days},
        "alternatives": [
            {"type": "正常销售", "quantity": normal_sale, "fee": Decimal("0"), "cash_impact": None, "remaining_risk": max(0, inventory - normal_sale)},
            {"type": "跨店调拨", "quantity": transfer_qty, "fee": money(input_data.get("transfer_fee")) or Decimal("0"), "cash_impact": None, "remaining_risk": remaining},
            {"type": "促销", "quantity": promo_qty, "fee": promo_fee, "cash_impact": None, "remaining_risk": remaining, "assumption": "缺少价格与销量关系依据，待人工确认"},
            {"type": "退供", "quantity": return_qty, "fee": Decimal("0"), "cash_impact": None, "remaining_risk": remaining, "assumption": "缺少供应商退换条款"},
        ],
        "cash": {"inventory_cost": money(Decimal(inventory) * unit_cost), "estimated_net_cash_improvement": None, "known_cash_effect": money(-promo_fee), "avoided_loss": money(Decimal(return_qty) * unit_cost) if return_qty else None, "completeness": "unavailable", "missing_fields": missing, "assumptions": assumptions},
    }


def calculate_procurement_brake(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """采购刹车试算：库存、在途、未执行订单分列，不相加为同一库存。"""
    current = _integer(input_data.get("current_inventory"))
    in_transit = _integer(input_data.get("in_transit_qty"))
    open_qty = _integer(input_data.get("open_purchase_qty"))
    adjustment_qty = _integer(input_data.get("adjustment_qty"))
    safety = _integer(input_data.get("safety_stock"))
    action = str(input_data.get("action") or "reduce")
    unit_cost = money(input_data.get("unit_cost")) or Decimal("0")
    cutoff = parse_date(input_data.get("cutoff_date"))
    payment_date = parse_date(input_data.get("payment_date"))
    new_payment_date = parse_date(input_data.get("new_payment_date"))
    errors: List[str] = []
    if action not in ("reduce", "cancel", "delay_arrival", "delay_payment"):
        errors.append("不支持的采购调整方式")
    if adjustment_qty <= 0:
        errors.append("调整数量必须大于 0")
    if adjustment_qty > open_qty:
        errors.append("调整数量超过未执行采购量")
    remaining_order = open_qty - adjustment_qty if action in ("reduce", "cancel") else open_qty
    projected = current + in_transit + remaining_order
    if action in ("reduce", "cancel") and projected < safety:
        errors.append("调整后预计库存低于安全库存，存在缺货风险")
    adjusted_amount = money(Decimal(adjustment_qty) * unit_cost) or Decimal("0")
    baseline_in_window = bool(cutoff and payment_date and payment_date <= cutoff)
    scenario_in_window = baseline_in_window
    deferred_pressure: Optional[Decimal] = None
    if action in ("reduce", "cancel"):
        scenario_in_window = False
    elif action == "delay_payment":
        if new_payment_date is None:
            errors.append("延期付款需要新的付款日期")
        else:
            scenario_in_window = bool(cutoff and new_payment_date <= cutoff)
            if cutoff and new_payment_date > cutoff:
                deferred_pressure = adjusted_amount
    improvement = adjusted_amount if baseline_in_window and not scenario_in_window else Decimal("0")
    return {
        "valid": not errors,
        "errors": errors,
        "inventory_position": {"current_inventory": current, "in_transit_qty": in_transit, "unexecuted_purchase_qty": open_qty, "adjusted_purchase_qty": adjustment_qty, "remaining_purchase_qty": remaining_order, "projected_after_adjustment": projected, "safety_stock": safety},
        "payment": {"baseline_payment_date": input_data.get("payment_date"), "scenario_payment_date": input_data.get("new_payment_date") if action == "delay_payment" else input_data.get("payment_date"), "adjusted_amount": adjusted_amount, "baseline_in_window": baseline_in_window, "scenario_in_window": scenario_in_window, "deferred_payment_pressure": deferred_pressure},
        "cash": {"inventory_cost": money(Decimal(current) * unit_cost), "estimated_net_cash_improvement": money(improvement), "known_cash_effect": money(improvement), "avoided_loss": None, "completeness": "complete" if baseline_in_window else "partial", "missing_fields": [] if baseline_in_window else ["payment_date_in_horizon"], "note": "减少采购支出与推迟付款分别展示；延期付款会产生后续付款压力。"},
        "order": {"po_number": input_data.get("po_number"), "line_number": input_data.get("line_number"), "arrival_date": input_data.get("arrival_date"), "payment_date": input_data.get("payment_date"), "status": input_data.get("order_status")},
    }


def idempotency_key(*parts: Any) -> str:
    return "|".join(str(part) for part in parts)


def solve_cash_goal(
    target: Decimal,
    horizon_days: int,
    candidates: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """小规模可重复背包求解；不宣称没有证明的最优结果。"""
    ordered = sorted(candidates, key=lambda item: money(item.get("cash_effect")) or Decimal("0"), reverse=True)
    selected: List[Dict[str, Any]] = []
    total = Decimal("0")
    for candidate in ordered:
        effect = money(candidate.get("cash_effect")) or Decimal("0")
        if effect <= 0:
            continue
        selected.append(candidate)
        total += effect
        if total >= target:
            break
    total = money(total) or Decimal("0")
    gap = money(max(target - total, Decimal("0"))) or Decimal("0")
    return {
        "selected": selected,
        "achieved": total,
        "target": money(target),
        "gap": gap,
        "horizon_days": int(horizon_days),
        "status": "feasible" if total >= target else "gap",
        "solver_status": "feasible_advice",
    }
