"""Public hackathon.v1 calculation boundary over injected fact DTOs.

This module owns no IO. The small reference_data extension supplies master data
and calendars absent from the initial shared DTO; canonical fact fields remain
the sole source for inventory, forecasts, routes, procurement and policies.
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json

from ..domain import money, parse_date
from ..hackathon_shared import CONTRACT_VERSION, FactQueryResult, ProposalComparison
from ..serialization import json_value
from .calculations import compare_options, simulate_cash


CALCULATION_VERSION = "retail-comparison-v2.1"
ACTION_TYPES = {"retain": "keep", "transfer": "transfer", "promotion": "promotion", "return": "return", "purchase": "procurement"}
REQUEST_FIELDS = {"context", "risk_keys", "objective", "horizon_start", "horizon_end", "assumption_ids", "inputs"}
INPUT_FIELDS = {"store_id", "sku_id", "lot_id", "quantity", "target_store_id", "transport_fee", "eta_days",
                "sales_settlement_days", "promotion_id", "stage_prices", "settlement_mode", "return_terms",
                "purchase_intent", "recommended_quantity", "new_payment_date", "combination"}
REFERENCE_TABLES = {"stores", "products", "suppliers", "people", "store_products", "store_calendar", "lots",
                    "promotion_stages", "bundle_items", "assumptions", "materials", "purchase_intents",
                    "risk_inputs", "procurement_policy", "transfer_policy", "accounts", "credit_notes"}
CANONICAL_TABLES = {"sales_history": "sales_daily", "availability_history": "availability_daily",
                    "demand_forecasts": "demand_forecasts", "routes": "routes", "payables": "payables"}
CONTEXT_KEYS = {"tenant_id", "scenario_id", "branch_id", "snapshot_id", "as_of", "data_version", "fact_version", "is_demo"}


def _content_id(prefix, content):
    encoded = json.dumps(json_value(content), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return prefix + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须为对象")
    return value


def _list(value, label):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} 必须为对象列表")
    return value


def _context(facts, request):
    if facts.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("计算事实必须使用 hackathon.v1 契约")
    context = _object(facts.get("context"), "facts.context")
    if CONTEXT_KEYS - context.keys():
        raise ValueError("事实缺少租户、场景、快照或版本上下文")
    if type(context["fact_version"]) is not int or context["fact_version"] < 1:
        raise ValueError("fact_version 必须为正整数")
    if type(context["is_demo"]) is not bool or context["branch_id"] is not None and not isinstance(context["branch_id"], str):
        raise ValueError("context.is_demo 与 branch_id 类型无效")
    for field in ("tenant_id", "scenario_id", "snapshot_id", "data_version"):
        if not isinstance(context[field], str) or not context[field]:
            raise ValueError(f"context.{field} 不能为空")
    try:
        when = datetime.fromisoformat(context["as_of"])
        if when.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("context.as_of 必须为带时区的 ISO 时点") from None
    if "context" in request:
        supplied = _object(request["context"], "request.context")
        if any(supplied.get(key) != context[key] for key in CONTEXT_KEYS):
            raise ValueError("请求与事实的租户、场景、快照或版本不一致")
    return deepcopy(context)


def _canonical(facts):
    reference = _object(facts.get("reference_data", {}), "reference_data")
    extra = _object(reference.get("tables", {}), "reference_data.tables")
    if set(extra) - REFERENCE_TABLES:
        raise ValueError("reference_data 只能补充主数据和业务规则，不能重复覆盖正式事实或包含回放")
    tables = {key: deepcopy(_list(rows, f"reference_data.tables.{key}")) for key, rows in extra.items()}
    inventory = []
    for raw in _list(facts.get("inventory", []), "inventory"):
        if "unit_cost" in raw or "tables" in raw:
            raise ValueError("库存 DTO 必须使用 unit_cost_cny，不能夹带另一套原始库存")
        row = deepcopy(raw)
        row["unit_cost"] = row.pop("unit_cost_cny", None)
        inventory.append(row)
    tables["inventory"] = inventory
    for public, internal in CANONICAL_TABLES.items():
        tables[internal] = deepcopy(_list(facts.get(public, []), public))
    tables.update(purchase_orders=[], in_transit=[], risk_policies=[], return_terms=[])
    for field, types in (("procurement", {"purchase_order": "purchase_orders", "in_transit": "in_transit"}),
                         ("policies", {"risk_policy": "risk_policies", "return_terms": "return_terms"})):
        for raw in _list(facts.get(field, []), field):
            row = deepcopy(raw)
            kind = row.pop("record_type", None)
            if kind not in types:
                raise ValueError(f"{field} 缺少已约定的 record_type")
            tables[types[kind]].append(row)
    context = facts["context"]
    return {"dataset_id": context["data_version"], "scenario_id": context["scenario_id"],
            "branch_id": context["branch_id"], "clock_at": context["as_of"], "snapshot_id": context["snapshot_id"],
            "data_version": context["data_version"], "tables": tables, "is_demo": context["is_demo"],
            "target": deepcopy(reference.get("target", {})), "evaluation_end": reference.get("evaluation_end")}


def _inputs(request, context, canonical):
    if set(request) - REQUEST_FIELDS:
        raise ValueError("未知比较请求字段；可变业务条件统一放在 inputs 中")
    inputs = deepcopy(_object(request.get("inputs", {}), "inputs"))
    if set(inputs) - INPUT_FIELDS:
        raise ValueError("inputs 包含未声明的计算字段")
    start = request.get("horizon_start", context["as_of"][:10])
    end = request.get("horizon_end", canonical["evaluation_end"])
    if start != context["as_of"][:10]:
        raise ValueError("horizon_start 必须对应当前事实时点；改变起点应先查询该时点事实")
    try:
        if not isinstance(end, str) or date.fromisoformat(end).isoformat() != end:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("缺少有效 horizon_end")
    if not 0 < (date.fromisoformat(end) - date.fromisoformat(start)).days <= 366:
        raise ValueError("观察期必须为 1 至 366 天，结束日期不包含在内")
    inputs["evaluation_end"] = end
    for key in ("risk_keys", "assumption_ids"):
        values = request.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values) or len(values) != len(set(values)):
            raise ValueError(f"{key} 必须为不重复的字符串列表")
    known_assumptions = {row.get("assumption_id") for row in canonical["tables"].get("assumptions", [])}
    if set(request.get("assumption_ids", [])) - known_assumptions:
        raise ValueError("请求包含当前事实范围外的需求假设")
    target = {**canonical["target"], **{k: inputs[k] for k in ("store_id", "sku_id", "lot_id") if k in inputs}}
    if any(not isinstance(target.get(key), str) or not target[key] for key in ("store_id", "sku_id", "lot_id")):
        raise ValueError("必须指定当前比较的门店、商品和批次")
    for risk in request.get("risk_keys", []):
        parts = risk.split(":")
        expected = [context["scenario_id"], target["store_id"], target["sku_id"], target["lot_id"]]
        if len(parts) != 5 or parts[:4] != expected or parts[-1] not in {"slow_moving", "near_expiry"}:
            raise ValueError("风险键与当前单批次比较范围不匹配")
    if "combination" in inputs:
        specs = inputs["combination"]
        _list(specs, "combination")
        for spec in specs:
            if set(spec) - (INPUT_FIELDS - {"combination"}) - {"type"}:
                raise ValueError("组合动作包含未声明字段")
            if spec.get("type") not in {"transfer", "promotion", "return", "procurement"}:
                raise ValueError("组合动作必须使用正式 transfer/promotion/return/procurement 枚举")
            if spec["type"] == "procurement":
                spec["type"] = "purchase"
    return inputs, target, start, end


def _cash_flow(events):
    return [{"event_id": event["event_id"], "event_type": event["event_type"], "direction": event["direction"],
             "amount_cny": money(event.get("amount")), "expected_at": event.get("event_date"), "status": "forecast",
             "source_ref": deepcopy(event.get("evidence_ref"))} for event in events]


class CalculationService:
    """Implements hackathon_shared.CalculationService without concrete services."""

    def compare(self, facts: FactQueryResult, request: dict) -> ProposalComparison:
        facts, request = _object(facts, "facts"), deepcopy(_object(request, "request"))
        context = _context(facts, request)
        canonical = _canonical(facts)
        inputs, target, start, end = _inputs(request, context, canonical)
        objective = request.get("objective", "比较同批库存的处置方案与同周期现金影响")
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 10000:
            raise ValueError("objective 必须为非空且不超过 10000 字的文字")
        policy = {name: canonical["tables"].get(name, []) for name in
                  ("risk_policies", "return_terms", "store_products", "procurement_policy", "transfer_policy", "promotion_stages", "routes")}
        policy_version = _content_id("POL-", policy)
        # Query-level data-quality notices can concern other products. Each
        # calculation validates its own dependencies; unrelated notices cannot
        # turn a complete local plan into a globally unavailable calculation.
        missing = []
        for name in ("products", "store_products", "store_calendar"):
            if not canonical["tables"].get(name):
                missing.append(f"reference_data.tables.{name}")
        inventory = [row for row in canonical["tables"]["inventory"]
                     if all(row.get(k) == target[k] for k in ("store_id", "sku_id", "lot_id")) and row.get("stock_state") == "on_hand"]
        if len(inventory) != 1:
            missing.append("target_inventory")
        elif any(inventory[0].get(k) is None for k in ("quantity", "unit_cost", "blocked_qty", "reserved_qty")):
            missing.append("target_inventory.quantity_cost_or_allocations")
        if missing:
            internal = self._unavailable(missing)
        else:
            internal = compare_options(canonical, inputs)
        # query_id is a query trace, not a business version. It must not make an
        # otherwise identical recomputation produce a different comparison ID.
        seed = {"contract_version": CONTRACT_VERSION, "calculation_version": CALCULATION_VERSION,
                "context": context, "facts": canonical, "request": request, "result": internal, "policy_version": policy_version}
        comparison_id = _content_id("CMP-", seed)
        baseline_id = _content_id("BASE-", {"context": context, "facts": canonical, "start": start, "end": end,
                                             "calculation_version": CALCULATION_VERSION, "baseline": internal["baseline"]})
        candidates, groups, ids = [], [], {}
        for raw in internal["candidates"]:
            if raw["type"] == "combination":
                members = []
                for child in raw["children"]:
                    public = self._candidate(child, canonical, target, start, end, comparison_id)
                    candidates.append(public)
                    members.append(public["candidate_id"])
                group_id = _content_id("GROUP-", {"comparison_id": comparison_id, "calculation": raw, "members": members})
                groups.append({"group_id": group_id, "member_candidate_ids": members, "feasible": raw["feasibility"] == "feasible",
                               "exclusion_reasons": raw["blocking_reasons"], "missing_fields": raw["missing_fields"],
                               "calculation": {"calculation_version": CALCULATION_VERSION, "execution_plan": deepcopy(raw),
                                               "planned_qty": None, "expected_sold_qty": None, "ending_qty": None,
                                               "base_unit": None, "execution_cost_cny": raw["execution_cost"],
                                               "gross_profit_cny": raw["expected_gross_profit"],
                                               "expected_cash_in_cny": raw["expected_cash_in"],
                                               "expected_cash_out_cny": raw["expected_cash_out"], "actual_cash_in_cny": None,
                                               "expected_net_cash_cny": raw["expected_net_cash"],
                                               "incremental_net_cash_cny": raw["incremental_net_cash_vs_baseline"],
                                               "cash_flow": _cash_flow(raw["settlement_timeline"]),
                                               "quantity_lines": self._quantity_lines(raw, canonical)}})
            else:
                public = self._candidate(raw, canonical, target, start, end, comparison_id)
                candidates.append(public)
                ids[raw["strategy_id"]] = public["candidate_id"]
        response = {"contract_version": CONTRACT_VERSION, "comparison_id": comparison_id, "context": context,
                    "calculation_version": CALCULATION_VERSION, "policy_version": policy_version, "objective": objective,
                    "horizon_start": start, "horizon_end": end, "baseline_id": baseline_id, "candidates": candidates,
                    "selected_candidate_id": ids.get(internal.get("recommended_strategy_id"))}
        response["fact_notices"] = list(dict.fromkeys(facts.get("missing_fields", []) + context.get("missing_fields", [])))
        if groups:
            response["candidate_groups"] = groups
        return json_value(response)

    @staticmethod
    def _quantity_lines(raw, canonical):
        units = {row["sku_id"]: row.get("base_unit") for row in canonical["tables"].get("products", [])}
        units.update({row["sku_id"]: row["base_unit"] for row in canonical["tables"]["inventory"] if row.get("base_unit")})
        return [{**deepcopy(line), "base_unit": units.get(line["sku_id"])} for line in raw["allocations"]]

    @staticmethod
    def _unavailable(missing):
        candidate = {"strategy_id": "retain", "type": "retain", "feasibility": "needs_confirmation",
                     "blocking_reasons": [], "missing_fields": missing, "assumptions": [], "allocations": [], "actions": [],
                     "allocated_qty": None, "expected_sold_qty": None, "expected_unsold_qty": None,
                     "expected_sales_revenue": None, "expected_gross_profit": None, "execution_cost": None,
                     "expected_cash_in": None, "expected_cash_out": None, "expected_net_cash": None,
                     "incremental_net_cash_vs_baseline": None, "settlement_timeline": [], "details": {}, "evidence_refs": []}
        return {"baseline": candidate, "candidates": [candidate], "recommended_strategy_id": None}

    def _candidate(self, raw, canonical, target, start, end, comparison_id):
        kind = raw["type"]
        action = raw["actions"][0] if raw["actions"] else {}
        scope = {key: action.get(key, target[key]) for key in ("store_id", "sku_id", "lot_id")}
        rows = [row for row in canonical["tables"]["inventory"] if all(row.get(key) == scope[key] for key in scope)]
        product = next((row for row in canonical["tables"].get("products", []) if row.get("sku_id") == scope["sku_id"]), {})
        unit = "组" if kind == "promotion" else product.get("base_unit") or (rows[0].get("base_unit") if rows else None)
        if unit is None:
            raise ValueError("比较对象缺少明确基础单位")
        planned = raw["allocated_qty"]
        if kind == "retain" and rows and rows[0].get("quantity") is not None:
            planned = Decimal(str(rows[0]["quantity"]))
            for field in ("blocked_qty", "reserved_qty"):
                if rows[0].get(field) is None:
                    planned = None
                    break
                planned -= Decimal(str(rows[0][field]))
        sold, ending = raw["expected_sold_qty"], raw["expected_unsold_qty"]
        cash_events, cash_in, cash_out, cash_net = (raw["settlement_timeline"], raw["expected_cash_in"],
                                                 raw["expected_cash_out"], raw["expected_net_cash"])
        gross = raw["expected_gross_profit"]
        if kind == "purchase":
            sold = raw["details"].get("new_purchase_expected_sold_qty")
            ending = raw["details"].get("new_purchase_ending_qty")
        if kind == "transfer" and raw["actions"]:
            sold = raw["details"].get("target_expected_sold_qty")
            ending = planned - sold if sold is not None and planned is not None else None
            cash_events = raw["details"].get("target_settlement_timeline", []) + [e for e in cash_events if e["event_type"] == "transport_fee"]
            cash = simulate_cash([], cash_events, start_date=start, end_date=end)["proposed"]
            cash_in, cash_out, cash_net = (cash["expected_cash_in"], cash["expected_cash_out"], cash["expected_net_cash"])
            if raw["feasibility"] != "feasible":
                sold = ending = cash_in = cash_out = cash_net = None
            gross = money(sold * (Decimal(str(product["regular_unit_price"])) - action["unit_cost"])) if sold is not None else None
        calculation = {"planned_qty": planned, "expected_sold_qty": sold, "ending_qty": ending, "base_unit": unit,
                       "execution_cost_cny": raw["execution_cost"], "gross_profit_cny": gross,
                       "expected_cash_in_cny": cash_in, "expected_cash_out_cny": cash_out, "expected_net_cash_cny": cash_net,
                       "actual_cash_in_cny": None, "cash_flow": _cash_flow(cash_events), "calculation_version": CALCULATION_VERSION,
                       "incremental_net_cash_cny": raw["incremental_net_cash_vs_baseline"],
                       "comparison_scope": deepcopy(raw["details"].get("cash_comparison_scope")),
                       "details": deepcopy(raw["details"]), "execution_plan": deepcopy(raw),
                       "quantity_lines": self._quantity_lines(raw, canonical)}
        cost = action.get("unit_cost", rows[0].get("unit_cost") if rows else None)
        allocated_cost = money(planned * Decimal(str(cost))) if planned is not None and cost is not None else None
        cost_recovery = money(sold * Decimal(str(cost))) if sold is not None and cost is not None and kind in {"retain", "transfer", "promotion"} else None
        reduction = None
        if raw["feasibility"] == "feasible":
            if kind in {"retain", "transfer", "promotion"}:
                reduction = cost_recovery
            elif kind == "return":
                replacement = Decimal(str(action["replacement_qty"])) * Decimal(str(action["replacement_unit_cost"])) if action.get("settlement_mode") == "exchange" else Decimal(0)
                reduction = money(allocated_cost - replacement) if allocated_cost is not None else None
            elif kind == "purchase" and ending is not None and cost is not None:
                reduction = money(-ending * Decimal(str(cost)))
        calculation.update(planned_stock_cost_cny=allocated_cost, expected_sales_cost_recovered_cny=cost_recovery,
                           inventory_cost_reduction_cny=reduction,
                           inventory_effect_scope="allocated_action_stock_including_replacement_or_new_purchase",
                           transfer_movement_cost_cny=allocated_cost if kind == "transfer" else None)
        if kind == "purchase":
            calculation["quantity_payment_reduction_cny"] = raw["details"].get("quantity_payment_reduction")
            calculation["deferred_payment_cny"] = raw["details"].get("deferred_payment_amount")
            calculation["quantity_scope"] = "new_purchase_only"
            calculation["store_sku_ending_qty"] = raw["details"].get("projected_store_ending_qty")
        candidate = {"action_type": ACTION_TYPES[kind], "feasible": raw["feasibility"] == "feasible",
                     "exclusion_reasons": deepcopy(raw["blocking_reasons"]), "store_id": scope["store_id"],
                     "target_store_id": action.get("target_store_id", raw["details"].get("target_store_id")),
                     "sku_id": scope["sku_id"], "lot_id": None if kind == "purchase" else scope["lot_id"],
                     "quantity": planned, "base_unit": unit, "calculation": calculation,
                     "assumptions": deepcopy(raw["assumptions"]), "missing_fields": deepcopy(raw["missing_fields"])}
        candidate["candidate_id"] = _content_id("CAND-", {"comparison_id": comparison_id, "candidate": candidate})
        return candidate
