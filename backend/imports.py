"""Frozen inventory-file format; validation never invents missing facts."""
from decimal import Decimal, InvalidOperation

from .domain import money

REQUIRED_INVENTORY_FIELDS = {"sku", "store", "inventory_qty", "unit", "unit_cost"}
MAX_QUANTITY = 2**31 - 1


def inventory_rows(rows):
    normalized, errors, keys, units = [], [], {}, {}
    duplicates = 0
    for index, source in enumerate(rows, 2):
        try:
            result = {}
            for name in ("sku", "store", "unit"):
                result[name] = str(source.get(name) or "").strip()
                if not result[name]:
                    raise ValueError(name + "不能为空")
            result["store_id"] = str(source.get("store_id") or result["store"]).strip()
            result["product"] = str(source.get("product") or result["sku"]).strip()
            for name in ("inventory_qty", "sales_30", "sales_90"):
                value = source.get(name)
                if value in (None, "") and name != "inventory_qty":
                    result[name] = None
                    continue
                value = Decimal(str(value))
                if not value.is_finite() or value < 0 or value > MAX_QUANTITY or value != value.to_integral_value():
                    raise ValueError(name + "必须为 0 至 2147483647 的整数")
                result[name] = int(value)
            for name in ("unit_cost", "sales_cost_30"):
                value = source.get(name)
                if value in (None, "") and name != "unit_cost":
                    result[name] = None
                    continue
                value = Decimal(str(value))
                if not value.is_finite() or value < 0:
                    raise ValueError(name + "必须为非负有限金额")
                result[name] = money(value)
                if result[name] is None:
                    raise ValueError(name + "超出金额计算范围")
            result["cost_amount"] = money(result["inventory_qty"] * result["unit_cost"])
            if result["cost_amount"] is None:
                raise ValueError("库存金额超出计算范围")
            if source.get("cost_amount") not in (None, "") and money(source["cost_amount"]) != result["cost_amount"]:
                raise ValueError("库存金额与数量×单位成本不一致")
            for name in ("stat_class", "purchase_status"):
                result[name] = str(source.get(name)).strip() if source.get(name) not in (None, "") else None
            sku = result["sku"]
            if sku in units and units[sku] != result["unit"]:
                raise ValueError("同一SKU单位冲突，不能自动换算")
            units[sku] = result["unit"]
            key = (result["store_id"], sku)
            if key in keys:
                if keys[key] != result:
                    raise ValueError("同一门店＋SKU存在冲突记录")
                duplicates += 1
                continue
            keys[key] = result
            normalized.append(result)
        except (ValueError, InvalidOperation, TypeError) as exc:
            errors.append({"row": index, "message": str(exc) or "数值无法解析"})
    return normalized, errors, duplicates
