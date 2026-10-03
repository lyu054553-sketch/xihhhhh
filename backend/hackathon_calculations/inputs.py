"""Validate public action inputs without changing the underlying fact snapshot."""
from copy import deepcopy

from .calculations import _date, _number


FIELDS = {
    "transfer": {"origin_store_id", "target_store_id", "sku_id", "lot_id", "quantity", "base_unit", "route_id", "route_fee_cny"},
    "promotion": {"products", "price_stages"},
    "return": {"supplier_id", "sku_id", "lot_id", "quantity", "base_unit", "settlement_method", "fee_cny"},
    "procurement": {"supplier_id", "purchase_order_id", "sku_id", "quantity", "base_unit", "unit_cost_cny", "expected_arrival_date", "payment_date"},
}
LEGACY_FIELDS = {
    "transfer": {"quantity", "target_store_id", "transport_fee", "eta_days"},
    "promotion": {"quantity", "promotion_id", "stage_prices"},
    "return": {"quantity", "settlement_mode", "return_terms"},
    "procurement": {"purchase_intent", "recommended_quantity", "new_payment_date"},
}


def _object(value, fields, path):
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError(f"{path} 必须为对象且只能包含约定字段")


def _unknowns(value, path):
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in _unknowns(child, f"{path}.{key}")]
    if isinstance(value, list):
        return [item for index, child in enumerate(value) for item in _unknowns(child, f"{path}[{index}]")]
    return []


def action_inputs(value, legacy, facts, target):
    """Translate only declared action fields; explicit unknowns remain local.

    Legacy flat input semantics remain available when no new input for that
    action is given. Overlapping input dialects are rejected, even when equal,
    so there is no undocumented priority between two sources of intent.
    """
    _object(value, FIELDS.keys(), "business_inputs")
    if value and "combination" in legacy:
        raise ValueError("business_inputs 与 inputs.combination 不能同时提供；组合子动作需独立明确条件")
    tables = facts["tables"]
    products = {row["sku_id"]: row for row in tables.get("products", [])}
    normalized = {}
    for public_kind, supplied in value.items():
        path = f"business_inputs.{public_kind}"
        _object(supplied, FIELDS[public_kind], path)
        if LEGACY_FIELDS[public_kind] & legacy.keys():
            raise ValueError(f"{path} 与同一动作的 inputs 字段不能混用")
        raw = deepcopy(supplied)
        missing = _unknowns(raw, path)
        kind = "purchase" if public_kind == "procurement" else public_kind
        current = {"input_missing_fields": missing, "input_source": path}
        normalized[kind] = current
        for field, target_field in (("origin_store_id", "store_id"), ("sku_id", "sku_id"), ("lot_id", "lot_id")):
            if field in raw and raw[field] is not None and raw[field] != target[target_field]:
                raise ValueError(f"{path}.{field} 与当前比较范围不一致")
        product = products.get(target["sku_id"], {})
        if "base_unit" in raw and raw["base_unit"] is not None and raw["base_unit"] != product.get("base_unit"):
            raise ValueError(f"{path}.base_unit 与商品基础单位不一致")
        if "quantity" in raw:
            if "base_unit" not in raw:
                raise ValueError(f"{path}.quantity 必须同时提供 base_unit")
            if raw["quantity"] is not None:
                _number(raw["quantity"], path + ".quantity", integer=True)
        if "supplier_id" in raw and raw["supplier_id"] is not None:
            if raw["supplier_id"] != product.get("supplier_id"):
                raise ValueError(f"{path}.supplier_id 与商品供应商不一致")
        if public_kind == "transfer":
            for public, internal in (("target_store_id", "target_store_id"), ("route_id", "route_id"),
                                     ("route_fee_cny", "transport_fee"), ("quantity", "quantity")):
                if public in raw:
                    current[internal] = raw[public]
            if raw.get("target_store_id") is not None and not any(row["store_id"] == raw["target_store_id"] for row in tables.get("stores", [])):
                raise ValueError("调拨接收门店不在当前事实范围")
            if raw.get("route_fee_cny") is not None:
                _number(raw["route_fee_cny"], path + ".route_fee_cny")
            if raw.get("route_id") is not None:
                routes = [row for row in tables["routes"] if row.get("route_id") == raw["route_id"]
                          and row.get("from_store_id") == target["store_id"]]
                if len(routes) != 1 or raw.get("target_store_id") not in (None, routes[0]["to_store_id"]):
                    raise ValueError("调拨路线与来源、接收门店不一致或不唯一")
        elif public_kind == "return":
            if raw.get("settlement_method") is not None and raw["settlement_method"] not in {"refund", "exchange", "offset"}:
                raise ValueError("settlement_method 必须为 refund/exchange/offset")
            for public, internal in (("quantity", "quantity"), ("fee_cny", "return_total_fee")):
                if public in raw:
                    current[internal] = raw[public]
            if "settlement_method" in raw:
                current["settlement_mode"] = {"refund": "cash_refund", "exchange": "exchange", "offset": "payable_credit"}.get(raw["settlement_method"])
            if raw.get("fee_cny") is not None:
                _number(raw["fee_cny"], path + ".fee_cny")
        elif public_kind == "promotion":
            for key, fields in (("products", {"sku_id", "quantity_per_bundle", "base_unit"}),
                                ("price_stages", {"label", "price_cny", "start_date", "end_date_exclusive"})):
                if key not in raw or raw[key] is None:
                    continue
                if not isinstance(raw[key], list) or not raw[key]:
                    raise ValueError(f"{path}.{key} 必须为非空列表")
                for index, row in enumerate(raw[key]):
                    label = f"{path}.{key}[{index}]"
                    _object(row, fields, label)
                    for field in fields - ({"label"} if key == "price_stages" else set()):
                        if field not in row:
                            missing.append(f"{label}.{field}")
                    if key == "products":
                        sku = row.get("sku_id")
                        if sku is not None and sku not in products:
                            raise ValueError(f"{label}.sku_id 不在商品事实中")
                        if sku is not None and row.get("base_unit") is not None and row["base_unit"] != products[sku]["base_unit"]:
                            raise ValueError(f"{label}.base_unit 与商品基础单位不一致")
                        if row.get("quantity_per_bundle") is not None and _number(row["quantity_per_bundle"], label + ".quantity_per_bundle", integer=True) <= 0:
                            raise ValueError("组合商品用量必须大于零")
                    else:
                        if row.get("price_cny") is not None:
                            _number(row["price_cny"], label + ".price_cny")
                        for field in ("start_date", "end_date_exclusive"):
                            if row.get(field) is not None:
                                _date(row[field], label + "." + field)
                current["promotion_" + key] = raw[key]
            if raw.get("products") is not None:
                skus = [row.get("sku_id") for row in raw["products"]]
                if len(skus) != len(set(skus)):
                    raise ValueError("促销商品不能重复")
        else:
            intent = {}
            current["purchase_input_unit"] = product.get("base_unit")
            for public, internal in (("supplier_id", "supplier_id"), ("sku_id", "sku_id"), ("quantity", "quantity"),
                                     ("base_unit", "unit"), ("unit_cost_cny", "unit_cost"),
                                     ("expected_arrival_date", "expected_arrival_date"), ("payment_date", "payment_date")):
                if public in raw:
                    intent[internal] = raw[public]
            if raw.get("unit_cost_cny") is not None:
                _number(raw["unit_cost_cny"], path + ".unit_cost_cny")
            for field in ("expected_arrival_date", "payment_date"):
                if raw.get(field) is not None:
                    _date(raw[field], path + "." + field)
            if raw.get("purchase_order_id") is not None:
                orders = [row for row in tables["purchase_orders"] if raw["purchase_order_id"] in (row.get("po_id"), row.get("po_line_id"))
                          and row.get("store_id") == target["store_id"] and row.get("sku_id") == target["sku_id"]]
                if len(orders) != 1:
                    raise ValueError("purchase_order_id 必须唯一匹配当前门店、商品的采购订单")
                current["purchase_order_id"] = raw["purchase_order_id"]
                missing.append("confirmed_order_change_permission_and_fee")
            current["purchase_intent"] = intent
    return normalized
