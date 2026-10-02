#!/usr/bin/env python3
"""把真实库存明细表导入独立 SQLite 快照，不覆盖演示数据库。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from backend.domain import TEACHER_BASELINE_VERSION, teacher_baseline  # noqa: E402
from backend.store import Store  # noqa: E402


FIELD_ALIASES = {
    "org_code": ("业务机构编码", "门店编码"),
    "org_name": ("业务机构名称", "门店名"),
    "sku": ("商品编码",),
    "product_name": ("商品名称",),
    "generic_name": ("商品通用名称", "通用名称"),
    "spec": ("规格",),
    "manufacturer": ("生产企业", "生产企业名称"),
    "origin": ("产地",),
    "unit": ("单位",),
    "inventory_qty": ("库存数量(A)", "库存数量"),
    "pending_qty": ("待出库数量(B)",),
    "available_qty": ("可用数量(A-B)",),
    "latest_cost": ("最新进价",),
    "cost_amount": ("进价金额", "库存金额"),
    "untaxed_cost_amount": ("无税进价金额",),
    "tax_amount": ("税额",),
    "lot_count": ("批号个数",),
    "sku_lot_count": ("每品批号数",),
    "amount_share": ("金额占比",),
    "company_focus": ("企业重点品标识",),
    "store_focus": ("门店重点品标识",),
    "barcode": ("条形码",),
    "purchase_status": ("采购状态",),
    "store_price": ("门店价格组售价", "最新售价"),
    "ecommerce_price": ("电商价格组售价",),
    "member_price": ("零售会员价", "最新会员价"),
    "product_status": ("商品状态",),
    "stat_class": ("统计标记类",),
    "sales_30": ("三十天销量",),
    "sales_90": ("九十天销量",),
    "sales_cost_30": ("三十天成本",),
    "source_monthly_sales": ("月均销量",),
    "source_sales_ratio": ("存销比",),
}

REQUIRED_FIELDS = ("org_code", "org_name", "sku", "product_name", "unit", "inventory_qty", "cost_amount")

NUMERIC_FIELDS = {
    "inventory_qty", "pending_qty", "available_qty", "latest_cost",
    "cost_amount", "untaxed_cost_amount", "tax_amount", "lot_count",
    "sku_lot_count", "amount_share", "store_price", "ecommerce_price", "member_price",
    "sales_30", "sales_90", "sales_cost_30", "source_monthly_sales", "source_sales_ratio",
}


def text(value: Any) -> Optional[str]:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_date(path: Path) -> str:
    match = re.search(r"(20\d{6,8})", path.name)
    if match:
        token = match.group(1)
        if len(token) == 8:
            return f"{token[:4]}-{token[4:6]}-{token[6:]}"
        if len(token) == 6:
            return f"20{token[:2]}-{token[2:4]}-{token[4:]}"
    return ""


def iter_lines(path: Path) -> Iterable[Dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    raw_header = next(rows, None)
    if not raw_header:
        raise ValueError("工作簿没有表头")
    # 该文件首列是行号，首行首格是总记录数，不属于业务字段。
    headers = [text(value) for value in raw_header[1:]]
    positions = {header: index for index, header in enumerate(headers) if header}
    source_columns = {
        target: next((name for name in aliases if name in positions), None)
        for target, aliases in FIELD_ALIASES.items()
    }
    missing = [field for field in REQUIRED_FIELDS if source_columns[field] is None]
    if missing:
        raise ValueError("缺少必要字段: " + ", ".join(sorted(missing)))
    for row in rows:
        if not row or all(value in (None, "") for value in row):
            continue
        values = row[1:]
        mapped: Dict[str, Any] = {}
        for target_name, source_name in source_columns.items():
            value = values[positions[source_name]] if source_name and positions[source_name] < len(values) else None
            mapped[target_name] = number(value) if target_name in NUMERIC_FIELDS else text(value)
        if mapped["available_qty"] is None:
            mapped["available_qty"] = mapped["inventory_qty"]
        if not mapped["org_code"] or not mapped["sku"]:
            # 跳过表尾合计行和没有业务主键的汇总记录。
            continue
        yield mapped


def import_snapshot(source: Path, database: Path, as_of_date: str) -> Dict[str, Any]:
    database.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(database))
    snapshot_id = "real-inventory-" + (as_of_date.replace("-", "") if as_of_date else "latest")
    created_at = datetime.now(timezone.utc).isoformat()

    rows: List[Dict[str, Any]] = []
    rows_by_key: Dict[tuple[str, str], Dict[str, Any]] = {}
    orgs = set()
    skus = set()
    units: Dict[str, int] = {}
    missing_latest_cost = 0
    missing_barcode = 0
    zero_cost_rows = 0
    total_cost = 0.0
    total_untaxed = 0.0
    raw_row_count = 0
    duplicate_rows = 0
    baseline_missing = set()
    baseline_calculated = 0

    for row in iter_lines(source):
        raw_row_count += 1
        key = (str(row["org_code"]), str(row["sku"]))
        existing = rows_by_key.get(key)
        if existing is not None:
            if existing == row:
                duplicate_rows += 1
                continue
            raise ValueError("同一门店＋商品编码存在字段冲突，无法确定当前快照：%s / %s" % key)
        rows_by_key[key] = dict(row)
        baseline = teacher_baseline(
            {
                "inventory_qty": row.get("inventory_qty"),
                "available_qty": row.get("available_qty"),
                "inventory_amount": row.get("cost_amount"),
                "sales_30": row.get("sales_30"),
                "sales_90": row.get("sales_90"),
                "sales_cost_30": row.get("sales_cost_30"),
                "stat_class": row.get("stat_class"),
                "purchase_status": row.get("purchase_status"),
            }
        )
        baseline_missing.update(baseline.get("missing_fields") or [])
        if baseline["status"] == "calculated":
            baseline_calculated += 1
        row.update(
            {
                "teacher_monthly_sales": baseline.get("monthly_sales"),
                "teacher_ratio": baseline.get("teacher_ratio"),
                "reduction_ratio": baseline.get("reduction_ratio"),
                "teacher_target_inventory_amount": baseline.get("target_inventory_amount"),
                "teacher_suggested_reduction_amount": baseline.get("suggested_reduction_amount"),
                "teacher_reference_reduction_qty": baseline.get("reference_reduction_quantity"),
                "teacher_priority": baseline.get("priority"),
                "teacher_trigger_reason": baseline.get("trigger_reason"),
                "teacher_candidate": int(bool(baseline.get("candidate"))),
                "teacher_eligible": int(bool(baseline.get("eligible"))),
                "teacher_stockout": None if baseline.get("stockout") is None else int(bool(baseline["stockout"])),
                "teacher_near_stockout": None if baseline.get("near_stockout") is None else int(bool(baseline["near_stockout"])),
            }
        )
        rows.append(row)
        orgs.add(row["org_code"])
        skus.add(row["sku"])
        units[row.get("unit") or "未标注"] = units.get(row.get("unit") or "未标注", 0) + 1
        if row.get("latest_cost") is None:
            missing_latest_cost += 1
        if not row.get("barcode"):
            missing_barcode += 1
        if (row.get("cost_amount") or 0) <= 0:
            zero_cost_rows += 1
        total_cost += row.get("cost_amount") or 0
        total_untaxed += row.get("untaxed_cost_amount") or 0

    columns = [
        "snapshot_id", "tenant_id", "org_code", "org_name", "sku", "product_name", "generic_name",
        "spec", "manufacturer", "origin", "unit", "inventory_qty", "pending_qty", "available_qty",
        "latest_cost", "cost_amount", "untaxed_cost_amount", "tax_amount", "lot_count", "sku_lot_count",
        "amount_share", "company_focus", "store_focus", "barcode", "purchase_status", "store_price",
        "ecommerce_price", "member_price", "product_status", "stat_class", "sales_30", "sales_90",
        "sales_cost_30", "source_monthly_sales", "source_sales_ratio", "teacher_monthly_sales",
        "teacher_ratio", "reduction_ratio", "teacher_target_inventory_amount", "teacher_suggested_reduction_amount",
        "teacher_reference_reduction_qty", "teacher_priority", "teacher_trigger_reason", "teacher_candidate",
        "teacher_eligible", "teacher_stockout", "teacher_near_stockout",
    ]
    placeholders = ",".join("?" for _ in columns)
    insert_sql = f"INSERT INTO real_inventory_lines ({','.join(columns)}) VALUES ({placeholders})"
    metadata = {
        "source_filename": source.name,
        "as_of_date_basis": "从文件名推断" if as_of_date else "源文件未提供可识别的快照日期",
        "teacher_baseline_version": TEACHER_BASELINE_VERSION,
        "teacher_baseline_target_ratio": 3,
        "teacher_baseline_missing_fields": sorted(baseline_missing) if baseline_calculated == 0 else [],
        "teacher_baseline_calculated_rows": baseline_calculated,
        "teacher_baseline_incomplete_rows": len(rows) - baseline_calculated,
        "unit_breakdown": dict(sorted(units.items(), key=lambda item: item[1], reverse=True)[:20]),
        "quality": {
            "raw_rows": raw_row_count,
            "deduplicated_rows": duplicate_rows,
            "missing_latest_cost_rows": missing_latest_cost,
            "missing_barcode_rows": missing_barcode,
            "zero_cost_rows": zero_cost_rows,
        },
        "scope_note": (
            "包含库存、30/90天销量、30天成本、采购状态和统计标记类；不包含批次效期、采购订单、在途、陈列或补货日志。"
            if baseline_calculated
            else "仅包含库存快照，不包含销量、批次效期、采购订单和门店地理位置。"
        ),
    }
    try:
        store.conn.execute("DELETE FROM real_inventory_lines WHERE snapshot_id=?", (snapshot_id,))
        store.conn.execute("DELETE FROM real_inventory_snapshots WHERE id=?", (snapshot_id,))
        store.conn.execute(
            """
            INSERT INTO real_inventory_snapshots
            (id, tenant_id, source, as_of_date, created_at, record_count, org_count, sku_count, cost_total, untaxed_cost_total, metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (snapshot_id, "demo", source.name, as_of_date, created_at, len(rows), len(orgs), len(skus), total_cost, total_untaxed, json.dumps(metadata, ensure_ascii=False)),
        )
        payload = [(snapshot_id, "demo", *(row.get(column) for column in columns[2:])) for row in rows]
        store.conn.executemany(insert_sql, payload)
        store.conn.commit()
        return {
            "snapshot_id": snapshot_id,
            "record_count": len(rows),
            "org_count": len(orgs),
            "sku_count": len(skus),
            "cost_total": round(total_cost, 2),
            "untaxed_cost_total": round(total_untaxed, 2),
            "metadata": metadata,
        }
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "inventory_cash_agent_real.db")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    as_of_date = args.as_of or infer_date(args.source)
    result = import_snapshot(args.source, args.database, as_of_date)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
