"""零售经营展示与采购情景计算。合成账户流水独立于库存估值，所有计算只读。"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

DEMO_DATE = date(2026, 10, 3)
DEMO_SOURCE = "零食仓 · 合成零售经营样例 v1"
CALCULATION_VERSION = "retail-scenario-v1"


def amount(value: Any) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def demo_dataset(risks: List[Dict[str, Any]], network: List[Any]) -> Dict[str, Any]:
    """固定的 50 店样例，风险记录沿用原 ID、数量和成本，正常周转商品另有来源标识。"""
    names = {item["store_id"]: item["store"] for item in sorted(risks, key=lambda x: x["id"])}
    for item in network:
        names.setdefault(item[2], item[1])
    stores = [{"id": key, "name": value} for key, value in list(names.items())[:50]]
    # sku / 品名 / 品类 / 单位 / 成本 / 零售价 / 日均销售
    catalog = [
        ("SN-001", "香辣薯片 110g", "膨化零食", "袋", "5.20", "7.90", 8),
        ("SN-002", "酸奶夹心饼干 100g", "饼干糕点", "袋", "3.80", "5.90", 10),
        ("SN-003", "无糖乌龙茶 500ml", "饮料乳品", "瓶", "2.60", "4.00", 16),
        ("SN-004", "每日坚果 25g", "坚果炒货", "袋", "3.40", "5.00", 11),
        ("SN-005", "山楂果脯 200g", "糖果果干", "袋", "4.50", "6.90", 6),
        ("SN-006", "奶香蛋卷 150g", "饼干糕点", "盒", "7.20", "10.90", 5),
    ]
    target_days_by_category = {"膨化零食": 7, "饼干糕点": 8, "饮料乳品": 7, "坚果炒货": 9, "糖果果干": 9}
    rows = []
    for index, shop in enumerate(stores):
        for product_index, (sku, product, category, unit, cost, price, daily) in enumerate(catalog):
            speed = Decimal(daily) * Decimal(8 + index % 5) / 10
            on_hand = int(speed * (5 + (index + product_index) % 9))
            rows.append({"sku": sku, "product": product, "category": category, "unit": unit,
                         "store_id": shop["id"], "store_name": shop["name"], "on_hand": on_hand,
                         "unit_cost": Decimal(cost), "unit_price": Decimal(price), "daily_demand": speed,
                         "in_transit": int(speed * (1 + product_index % 2)), "safety_days": 5,
                         "target_days": target_days_by_category[category] + index % 2,
                         "risk_tags": [], "source": "synthetic_regular_inventory_v1"})
    for risk in risks:
        if risk["store_id"] not in {shop["id"] for shop in stores}:
            continue
        product = risk["product"]
        category = ("坚果炒货" if "坚果" in product or "腰果" in product else "饮料乳品" if any(word in product for word in ("牛奶", "果汁", "乌龙茶")) else "糖果果干" if "果脯" in product or "果冻" in product else "膨化零食" if "薯片" in product else "饼干糕点")
        rows.append({"sku": risk["sku"], "product": product, "category": category, "unit": "件",
                     "store_id": risk["store_id"], "store_name": risk["store"], "on_hand": risk["inventory_qty"],
                     "unit_cost": Decimal(str(risk["unit_cost"])), "unit_price": Decimal(str(risk["unit_cost"])) * Decimal("1.35"),
                     "daily_demand": Decimal(risk["sales_30"]) / 30, "in_transit": 0, "safety_days": 5, "target_days": target_days_by_category[category],
                     "risk_tags": risk["tags"], "risk_id": risk["id"], "risk_reason": risk.get("observation"), "source": "sample-data/ac01"})
    # 独立的演示采购付款计划；只把已确认且在未来 30 天到期的付款列入首页。
    confirmed_payments = []
    for index, shop in enumerate(stores):
        confirmed_payments.extend([
            {"store_id": shop["id"], "order_id": f"DEMO-PO-{index + 1:03d}-A",
             "due_date": (DEMO_DATE + timedelta(days=12)).isoformat(),
             "amount": amount(Decimal(90 + index % 5 * 10) * Decimal("5.20")),
             "confirmation_status": "confirmed"},
            {"store_id": shop["id"], "order_id": f"DEMO-PO-{index + 1:03d}-B",
             "due_date": (DEMO_DATE + timedelta(days=26)).isoformat(),
             "amount": amount(Decimal(150 + index % 7 * 10) * Decimal("2.60")),
             "confirmation_status": "confirmed"},
        ])
    return {"stores": stores, "rows": rows, "confirmed_payments": confirmed_payments,
            "as_of_date": DEMO_DATE.isoformat(), "is_demo": True, "source": DEMO_SOURCE}


def select_rows(dataset: Dict[str, Any], store_id: Optional[str], category: Optional[str] = None) -> List[Dict[str, Any]]:
    store_id = store_id or "all"
    if store_id != "all" and store_id not in {row["id"] for row in dataset["stores"]}:
        raise ValueError("门店不存在或不在当前数据范围内")
    if category and category not in {row["category"] for row in dataset["rows"]}:
        raise ValueError("品类不存在或不在当前数据范围内")
    return [row for row in dataset["rows"] if (store_id == "all" or row["store_id"] == store_id) and (not category or row["category"] == category)]


def simulation_options(dataset: Dict[str, Any]) -> Dict[str, Any]:
    return {key: dataset[key] for key in ("stores", "is_demo", "source", "as_of_date")} | {"categories": sorted({row["category"] for row in dataset["rows"]})}


def _day_history(row: Dict[str, Any], day_index: int) -> Dict[str, Decimal]:
    # 固定销量波动；同一门店和日期在不同查询窗口下保持一致。
    factor = Decimal([90, 95, 102, 97, 110, 125, 118][day_index % 7]) / 100
    units = (row["daily_demand"] * factor).to_integral_value(rounding=ROUND_HALF_UP)
    sales = units * row["unit_price"]
    cogs = units * row["unit_cost"]
    return {"sales": sales, "cogs": cogs}


def demo_overview(dataset: Dict[str, Any], period: int, store_id: Optional[str]) -> Dict[str, Any]:
    if period not in (7, 30):
        raise ValueError("经营总览仅支持 7 天或 30 天")
    selected = select_rows(dataset, store_id)
    ids = {row["store_id"] for row in selected}
    selected_stores = [item for item in dataset["stores"] if item["id"] in ids]
    # 每店一个明确标记的演示账户，流水分为收款、采购付款、经营费用。
    # 金额不由库存占用倒推，不包含调拨价值或预计释放资金。
    balances = {item["id"]: Decimal(8500 + index * 175) for index, item in enumerate(dataset["stores"]) if item["id"] in ids}
    opening_balance = sum(balances.values(), Decimal(0))
    daily = []
    store_sales = {key: Decimal(0) for key in ids}
    store_profit = {key: Decimal(0) for key in ids}
    for index in range(60):
        sales = cogs = receipts = payments = expenses = Decimal(0)
        for row in selected:
            activity = _day_history(row, index)
            sale, cost = activity["sales"], activity["cogs"]
            # 演示：当日全额结算，采购付款和营业费用按固定流水生成规则构造。
            purchase = (cost * Decimal("0.92")).quantize(Decimal("0.01"))
            expense = (sale * Decimal("0.19")).quantize(Decimal("0.01"))
            balances[row["store_id"]] += sale - purchase - expense
            sales += sale
            cogs += cost
            receipts += sale
            payments += purchase
            expenses += expense
            if index >= 60 - period:
                store_sales[row["store_id"]] += sale
                store_profit[row["store_id"]] += sale - cost
        daily.append({"date": (DEMO_DATE - timedelta(days=59 - index)).isoformat(), "sales": amount(sales),
                      "gross_profit": amount(sales - cogs), "cash_balance": amount(sum(balances.values(), Decimal(0))),
                      "cash_in": amount(receipts), "purchase_outflow": amount(payments), "operating_outflow": amount(expenses)})
    current = daily[-period:]
    previous = daily[-period * 2:-period]
    sales = sum(Decimal(str(row["sales"])) for row in current)
    sales_7d = sum(Decimal(str(row["sales"])) for row in daily[-7:])
    profit_7d = sum(Decimal(str(row["gross_profit"])) for row in daily[-7:])
    previous_sales = sum(Decimal(str(row["sales"])) for row in previous)
    profit = sum(Decimal(str(row["gross_profit"])) for row in current)
    inventory = sum(row["unit_cost"] * row["on_hand"] for row in selected)
    risk_rows = [row for row in selected if row["risk_tags"]]
    attention = sum(row["unit_cost"] * row["on_hand"] for row in risk_rows)
    confirmed_payments = [item for item in dataset.get("confirmed_payments", [])
                          if item["store_id"] in ids and item["confirmation_status"] == "confirmed"
                          and 0 < (date.fromisoformat(item["due_date"]) - DEMO_DATE).days <= 30]
    stockout_risk_count = sum(1 for row in selected
                              if row["daily_demand"] > 0 and
                              Decimal(row["on_hand"] + row["in_transit"]) < row["daily_demand"] * 7)
    performance = []
    risk_labels = {"near_expiry": "近效期", "slow": "滞销", "overpurchase": "采购过量", "mismatch": "门店错配"}
    for shop in selected_stores:
        items = [row for row in selected if row["store_id"] == shop["id"]]
        revenue = store_sales[shop["id"]]
        store_inventory = sum((row["unit_cost"] * row["on_hand"] for row in items), Decimal(0))
        at_risk = sorted((row for row in items if row["risk_tags"]), key=lambda row: row["unit_cost"] * row["on_hand"], reverse=True)
        store_risk = sum((row["unit_cost"] * row["on_hand"] for row in at_risk), Decimal(0))
        store_cogs = revenue - store_profit[shop["id"]]
        risk_items = [{"risk_id": row.get("risk_id"), "sku": row["sku"], "product": row["product"],
                       "inventory_cost": amount(row["unit_cost"] * row["on_hand"]),
                       "risk_label": "、".join(risk_labels[tag] for tag in ("near_expiry", "slow", "overpurchase", "mismatch") if tag in row["risk_tags"]) or "待核查",
                       "reason": row.get("risk_reason") or "需核查库存与销量差异"} for row in at_risk[:5]]
        performance.append({"store_id": shop["id"], "store_name": shop["name"], "sales": amount(revenue),
                            "gross_profit": amount(store_profit[shop["id"]]),
                            "gross_margin_pct": amount(store_profit[shop["id"]] / revenue * 100) if revenue else None,
                            "inventory_cost": amount(store_inventory), "risk_cost": amount(store_risk),
                            "turnover_days": amount(store_inventory / store_cogs * period) if store_cogs > 0 else None,
                            "risk_count": len(at_risk), "primary_risk": risk_items[0]["risk_label"] if risk_items else "暂无重点风险",
                            "risk_types": [risk_labels[tag] for tag in risk_labels if any(tag in row["risk_tags"] for row in at_risk)],
                            "risk_items": risk_items})
    performance.sort(key=lambda row: (row["risk_cost"], row["inventory_cost"]), reverse=True)
    cash_opening = daily[-period - 1]["cash_balance"] if period < 60 else amount(opening_balance)
    return {
        "is_demo": True, "source": DEMO_SOURCE, "as_of_date": dataset["as_of_date"],
        "scope": {"store_id": store_id or "all", "store_count": len(selected_stores), "period": period},
        "account": {"balance": amount(sum(balances.values(), Decimal(0))), "opening_balance": cash_opening,
                    "cash_in": amount(sum(Decimal(str(row["cash_in"])) for row in current)),
                    "cash_out": amount(sum(Decimal(str(row["purchase_outflow"])) + Decimal(str(row["operating_outflow"])) for row in current)),
                    "is_demo": True, "source": "独立模拟账户流水 demo_account_ledger_v1", "status": "available"},
        "sales": {"amount": amount(sales), "gross_profit": amount(profit),
                  "gross_margin_pct": amount(profit / sales * 100) if sales else None,
                  "amount_7d": amount(sales_7d),
                  "gross_margin_7d_pct": amount(profit_7d / sales_7d * 100) if sales_7d else None,
                  "change_pct": amount((sales - previous_sales) / previous_sales * 100) if previous_sales else None},
        "inventory": {"cost": amount(inventory), "risk_cost": amount(attention), "risk_count": len(risk_rows),
                      "risk_store_count": len({row["store_id"] for row in risk_rows}),
                      "stockout_risk_count": stockout_risk_count,
                      "turnover_days": amount(inventory / (sales - profit) * period) if sales > profit else None,
                      "sku_count": len({row["sku"] for row in selected}), "store_sku_count": len(selected)},
        "purchase_commitments": {"amount": amount(sum(Decimal(str(item["amount"])) for item in confirmed_payments)),
                                 "count": len(confirmed_payments), "horizon_days": 30, "status": "available",
                                 "source": "独立合成的已确认采购付款计划"},
        "trend": current, "stores": performance,
        "metadata": {"is_demo": True, "source": DEMO_SOURCE, "currency": "CNY", "missing": [],
                     "assumptions": ["演示账户由期初余额加收款减采购付款及经营费用构成，与库存估值分别计算。", "未来30天已确认采购付款来自独立合成的确认计划，不使用历史付款或采购预测代替。", "销量、售价、结算和营业费用均为固定合成数据。", "缺货风险按未来7天预计需求大于现货与在途合计的门店商品记录计数。", "风险库存按门店商品去重，多个风险标签不重复计价。"]},
    }


def _purchase_plan(row: Dict[str, Any], horizon: int, reduction: Decimal) -> Dict[str, Any]:
    demand = row["daily_demand"]
    required = max(Decimal(0), demand * (horizon + row["target_days"]) - row["on_hand"] - row["in_transit"])
    baseline_qty = int(required.to_integral_value(rounding=ROUND_CEILING))
    scenario_qty = int((Decimal(baseline_qty) * (1 - reduction / 100)).to_integral_value(rounding=ROUND_FLOOR))
    weeks = list(range(0, horizon, 7))
    def run(quantity: int) -> Dict[str, Any]:
        stock = Decimal(row["on_hand"])
        shortage = Decimal(0)
        received = 0
        weekly = []
        for start in weeks:
            end = min(start + 7, horizon)
            # 累计整件分配，最后一周收齐计划数量；保证曲线与总支出完全相等。
            allocated_total = quantity * end // horizon
            receipt = allocated_total - received
            received = allocated_total
            weekly.append(amount(receipt * row["unit_cost"]))
            stock += receipt
            if start == 0:
                stock += row["in_transit"]
            for _ in range(start, end):
                sold = min(stock, demand)
                shortage += demand - sold
                stock -= sold
        coverage = stock / demand if demand else None
        return {"quantity": quantity, "outflow": amount(quantity * row["unit_cost"]),
                "inventory_cost": amount(stock * row["unit_cost"]), "ending_qty": amount(stock),
                "days": amount(coverage) if coverage is not None else None,
                "risk": shortage > 0 or (coverage is not None and coverage < row["safety_days"]),
                "shortage": amount(shortage), "weekly": weekly}
    return {"baseline": run(baseline_qty), "scenario": run(scenario_qty)}


def simulate_purchase(dataset: Dict[str, Any], horizon_days: int, reduction_pct: Any, store_id: Optional[str] = None,
                      category: Optional[str] = None, request_text: str = "") -> Dict[str, Any]:
    reduction = Decimal(str(reduction_pct))
    if not 1 <= horizon_days <= 90 or not reduction.is_finite() or not 0 <= reduction <= 100:
        raise ValueError("周期须为 1—90 天，采购减量须为 0—100%")
    selected = select_rows(dataset, store_id, category)
    if not selected:
        raise ValueError("当前范围没有可用于模拟的商品")
    start = date.fromisoformat(dataset["as_of_date"])
    weekly = [{"label": "第%d周" % (offset // 7 + 1), "start_date": (start + timedelta(days=offset)).isoformat(),
               "end_date": (start + timedelta(days=min(offset + 6, horizon_days - 1))).isoformat(),
               "baseline": 0.0, "scenario": 0.0} for offset in range(0, horizon_days, 7)]
    totals = {key: {"purchase_outflow": Decimal(0), "ending_inventory_cost": Decimal(0), "stockout_risk_count": 0} for key in ("baseline", "scenario")}
    risks = []
    lines = []
    for row in selected:
        result = _purchase_plan(row, horizon_days, reduction)
        for key in ("baseline", "scenario"):
            totals[key]["purchase_outflow"] += Decimal(str(result[key]["outflow"]))
            totals[key]["ending_inventory_cost"] += Decimal(str(result[key]["inventory_cost"]))
            totals[key]["stockout_risk_count"] += int(result[key]["risk"])
            for index, value in enumerate(result[key]["weekly"]):
                weekly[index][key] = amount(Decimal(str(weekly[index][key])) + Decimal(str(value)))
        base, plan = result["baseline"], result["scenario"]
        if plan["risk"] or base["risk"]:
            risks.append({"sku": row["sku"], "product": row["product"], "store_id": row["store_id"], "store_name": row["store_name"],
                          "unit": row["unit"], "baseline_days": base["days"], "scenario_days": plan["days"],
                          "safety_days": row["safety_days"], "risk_level": "high" if plan["shortage"] > 0 else "watch",
                          "shortage_qty": plan["shortage"], "is_new_risk": plan["risk"] and not base["risk"]})
        lines.append({"sku": row["sku"], "store_id": row["store_id"], "unit": row["unit"], "unit_cost": amount(row["unit_cost"]),
                      "on_hand": row["on_hand"], "in_transit_qty": row["in_transit"], "daily_demand": amount(row["daily_demand"]),
                      "target_days": row["target_days"], "safety_days": row["safety_days"],
                      "baseline_purchase_qty": base["quantity"], "scenario_purchase_qty": plan["quantity"],
                      "baseline_ending_qty": base["ending_qty"], "scenario_ending_qty": plan["ending_qty"]})
    risks.sort(key=lambda row: (row["risk_level"] != "high", row["scenario_days"] or 0, row["store_id"], row["sku"]))
    metrics = {key: {"baseline": amount(totals["baseline"][key]), "scenario": amount(totals["scenario"][key]),
                     "delta": amount(totals["scenario"][key] - totals["baseline"][key])} for key in totals["baseline"]}
    metrics["stockout_risk_count"] = {key: int(value) for key, value in metrics["stockout_risk_count"].items()}
    return {"status": "completed", "is_demo": True, "source": dataset["source"],
            "scenario": {"horizon_days": horizon_days, "reduction_pct": amount(reduction), "store_id": store_id or "all",
                         "store_name": next((item["name"] for item in dataset["stores"] if item["id"] == store_id), "全部门店"),
                         "category": category, "request_text": request_text, "start_date": start.isoformat(),
                         "end_date": (start + timedelta(days=horizon_days - 1)).isoformat()},
            "metrics": metrics, "weekly": weekly, "risks": risks, "lines": lines,
            "metadata": {"is_demo": True, "source": dataset["source"], "calculation_version": CALCULATION_VERSION,
                         "units": {"money": "CNY", "coverage": "days", "risk_count": "store_sku", "quantity": "商品单位"},
                         "missing": ["actual_bank_settlement_schedule", "price_elasticity", "future_promotions"],
                         "assumptions": ["使用固定的日均需求，每周周初到货，已确认在途于第1天到货且已付款。", "基线补货目标为7—10天，按品类和门店补货节奏设置；安全下限统一为5天。仅减可调整采购，按整件向下取整。", "采购到货当日付款，曲线为分周采购支出，不是账户余额。", "按日计算库存与未满足需求；期末低于安全库存或期间发生缺货均计风险。", "风险数量按门店商品组合统计，同一商品在不同门店分别计数。", "库存成本下降不等于现金回款；未推算净现金改善，也不会修改采购或库存。"]}}
