#!/usr/bin/env python3
"""Generate the v0.3 synthetic input dataset, never Agent responses or business results."""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import random
import tempfile


ROOT = Path(__file__).resolve().parent
SEED = 20261002
AS_OF = "2026-10-02"
TABLES = ("stores", "skus", "inventory_snapshots", "sales_daily", "purchase_orders", "inventory_lots", "policies")
METADATA = {
    "contract_version": "v0.3", "data_version": "snack-demo-v1", "policy_version": "snack-policy-v1",
    "as_of": AS_OF, "synthetic": True, "seed": SEED, "timezone": "Asia/Shanghai",
    "source_label": "虚构零食连锁合成演示数据",
    "disclaimer": "仅用于接口联调与测试；不是客户数据，参考结果不代表模型输出或真实收益。",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _csv(rows):
    buffer = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: (str(value).lower() if isinstance(value, bool) else value) for key, value in row.items()} for row in rows)
    return buffer.getvalue().encode("utf-8")


def build_dataset():
    definitions = read_json(ROOT / "fixture-definitions.json")
    dataset = {**METADATA, "assumptions": definitions["assumptions"]}
    for table in TABLES:
        dataset[table] = definitions.get(table, [])
    sku_by_id = {sku["sku_id"]: sku for sku in dataset["skus"]}
    rng = random.Random(SEED)
    start = date.fromisoformat(AS_OF) - timedelta(days=13)
    sales = []
    for profile in definitions["sales_profiles"]:
        # Randomize only the distribution of declared synthetic observations.
        quantities = list(profile["daily_quantities"])
        rng.shuffle(quantities)
        for offset, quantity in enumerate(quantities):
            price = sku_by_id[profile["sku_id"]]["sale_price_fen"]
            sales.append({
                "business_date": (start + timedelta(days=offset)).isoformat(),
                "store_id": profile["store_id"], "sku_id": profile["sku_id"],
                "net_sold_qty": quantity, "sales_amount_fen": quantity * price,
                "is_promotion": False, "unit_sale_price_fen": price,
            })
    sales.extend(definitions["historical_sales"])
    dataset["sales_daily"] = sorted(sales, key=lambda row: (row["store_id"], row["sku_id"], row["business_date"]))
    return dataset


def build_artifacts():
    dataset = build_dataset()
    requests = read_json(ROOT / "reference" / "scenario-requests.json")
    artifacts = {"dataset.json": _json(dataset)}
    artifacts.update({f"{table}.csv": _csv(dataset[table]) for table in TABLES})
    artifacts["scenario_requests.json"] = _json(requests)
    return dataset, requests, artifacts


def _manifest(output_dir, dataset, requests, artifacts):
    category_labels = {"SNACK-CHIPS": "脆片", "SNACK-NUTS": "坚果", "SNACK-DRINK": "饮品", "SNACK-BEAN": "豆制品"}
    return {
        **METADATA, "scenario_count": len(requests["items"]),
        "record_counts": {table: len(dataset[table]) for table in TABLES},
        "scope_options": {
            "stores": dataset["stores"], "skus": dataset["skus"],
            "categories": [{"category_id": key, "category_name": value} for key, value in category_labels.items()],
        },
        "scenarios": [{"id": item["id"], "title": item["title"], "agent_type": item["request"]["agent_type"]} for item in requests["items"]],
        "files": {
            Path(filename).stem: {
                "path": f"{output_dir.name}/{filename}", "sha256": hashlib.sha256(content).hexdigest(),
                **({"model": Path(filename).stem} if filename.endswith(".csv") else {}),
            } for filename, content in artifacts.items()
        },
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
    dataset, requests, artifacts = build_artifacts()
    manifest = _manifest(output_dir, dataset, requests, artifacts)
    for filename, content in artifacts.items():
        _atomic_write(output_dir / filename, content)
    _atomic_write(output_dir.parent / "manifest.json", _json(manifest))
    return manifest


def verify(output_dir):
    output_dir = Path(output_dir)
    dataset, requests, artifacts = build_artifacts()
    expected = {output_dir / name: content for name, content in artifacts.items()}
    expected[output_dir.parent / "manifest.json"] = _json(_manifest(output_dir, dataset, requests, artifacts))
    failures = [str(path) for path, content in expected.items() if not path.is_file() or path.read_bytes() != content]
    if failures:
        raise ValueError("合成数据缺失、被修改或未按当前定义生成：\n" + "\n".join(failures))


def main():
    parser = argparse.ArgumentParser(description="生成或校验 snack-demo-v1 合成输入")
    parser.add_argument("--output", type=Path, default=ROOT / "generated", help="输出目录；manifest 写入其父目录")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        try:
            verify(args.output)
        except ValueError as error:
            parser.exit(1, str(error) + "\n")
        print(f"verified {args.output}")
    else:
        manifest = generate(args.output)
        print(f"generated {len(manifest['files'])} files; data_version=snack-demo-v1; seed={SEED}")


if __name__ == "__main__":
    main()
