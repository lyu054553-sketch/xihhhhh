#!/usr/bin/env python3
"""Build reproducible synthetic inputs, without reimplementing business rules."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import tempfile


ROOT = Path(__file__).resolve().parent
SEED = 20261002
AS_OF_DATE = "2026-09-30"
SOURCE_LABEL = "合成演示数据（固定种子）"


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _csv(rows, fields):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def build_artifacts():
    """Randomize synthetic identifiers only; scenario constraints stay explicit."""
    cases = json.loads((ROOT / "scenario-inputs.json").read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "expected-results.json").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    inventory = []
    for index, case in enumerate(cases, 1):
        if "inventory" not in case:
            continue
        inventory.append({
            "scenario_id": case["id"], "is_sample": True,
            "snapshot_id": "snapshot-synthetic-v1", "as_of_date": AS_OF_DATE,
            "sku": f"SYN-{rng.randrange(100000, 999999)}-{index:02d}",
            "store": f"合成门店-{index:02d}", "product_name": f"合成商品-{index:02d}",
            "unit": "盒", **case["inventory"],
        })
    sales = [{
        "scenario_id": row["scenario_id"], "is_sample": True,
        "sku": row["sku"], "store": row["store"],
        "period_start": "2026-09-01", "period_end": AS_OF_DATE,
        "sales_qty": row["sales_30"], "sales_90": row["sales_90"],
        "sales_cost_30": row["sales_cost_30"],
    } for row in inventory]
    by_scenario = {row["scenario_id"]: row for row in inventory}
    expiry_row = by_scenario["near_expiry"]
    purchase_row = by_scenario["over_purchase"]
    expiry = [{
        "scenario_id": "near_expiry", "is_sample": True,
        "sku": expiry_row["sku"], "store": expiry_row["store"],
        "batch": "LOT-SYN-EXPIRY", "expiry_date": "2026-10-12",
        "quantity": expiry_row["inventory_qty"],
    }]
    purchase = [{
        "scenario_id": "over_purchase", "is_sample": True,
        "sku": purchase_row["sku"], "store": purchase_row["store"],
        "po_number": "PO-SYN-001", "open_purchase_qty": 132,
        "in_transit_qty": 20, "payment_date": "2026-10-05", "order_status": "unexecuted",
    }]
    metadata = {
        "schema_version": "synthetic-scenarios-v1", "source_label": SOURCE_LABEL,
        "is_sample": True, "seed": SEED, "as_of_date": AS_OF_DATE,
        "timezone": "Asia/Shanghai", "scenario_count": len(cases),
        "record_count": len(inventory),
        "disclaimer": "仅用于功能演示和测试；不是客户数据，测算结果不代表真实收益。",
    }
    inventory_fields = [
        "scenario_id", "is_sample", "snapshot_id", "as_of_date", "sku", "store",
        "product_name", "unit", "inventory_qty", "inventory_amount", "unit_cost",
        "sales_30", "sales_90", "sales_cost_30", "stat_class", "purchase_status",
    ]
    artifacts = {
        "inventory.csv": _csv(inventory, inventory_fields),
        "sales.csv": _csv(sales, list(sales[0])),
        "purchase.csv": _csv(purchase, list(purchase[0])),
        "expiry.csv": _csv(expiry, list(expiry[0])),
        "snapshot.json": _json({"metadata": metadata, "inventory": inventory, "sales": sales, "purchase": purchase, "expiry": expiry}),
        "scenarios.json": _json({"metadata": metadata, "items": cases}),
        "expected_results.json": _json({"metadata": metadata, "items": expected}),
    }
    return metadata, cases, artifacts


def _manifest(output_dir, metadata, cases, artifacts):
    files = {}
    for filename, content in artifacts.items():
        kind = Path(filename).stem
        entry = {"path": f"{output_dir.name}/{filename}", "sha256": hashlib.sha256(content).hexdigest()}
        if filename.endswith(".csv"):
            entry["data_kind"] = kind
        files[kind] = entry
    return {
        "metadata": metadata,
        "scenarios": [{key: case[key] for key in ("id", "title", "description", "type")} for case in cases],
        "files": files,
    }


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def generate(output_dir):
    output_dir = Path(output_dir)
    metadata, cases, artifacts = build_artifacts()
    manifest = _manifest(output_dir, metadata, cases, artifacts)
    for filename, content in artifacts.items():
        _atomic_write(output_dir / filename, content)
    # Publishing the manifest last makes an interrupted generation detectable.
    _atomic_write(output_dir.parent / "manifest.json", _json(manifest))
    return manifest


def verify(output_dir):
    """Check both file integrity and drift from the checked-in source scenarios."""
    output_dir = Path(output_dir)
    metadata, cases, artifacts = build_artifacts()
    expected = {output_dir / name: content for name, content in artifacts.items()}
    expected[output_dir.parent / "manifest.json"] = _json(_manifest(output_dir, metadata, cases, artifacts))
    failures = [str(path) for path, content in expected.items() if not path.is_file() or path.read_bytes() != content]
    if failures:
        raise ValueError("合成数据文件缺失、被修改或未按当前场景重新生成：\n" + "\n".join(failures))


def main():
    parser = argparse.ArgumentParser(description="生成或校验固定种子的合成演示数据")
    parser.add_argument("--output", type=Path, default=ROOT / "generated", help="输出目录；manifest.json 写入其父目录")
    parser.add_argument("--check", action="store_true", help="校验当前文件与场景源定义完全一致")
    args = parser.parse_args()
    if args.check:
        try:
            verify(args.output)
        except ValueError as error:
            parser.exit(1, str(error) + "\n")
        print(f"verified {args.output}")
    else:
        manifest = generate(args.output)
        print(f"generated {len(manifest['files'])} files; seed={SEED}; {SOURCE_LABEL}")


if __name__ == "__main__":
    main()
