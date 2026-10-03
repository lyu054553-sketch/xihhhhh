#!/usr/bin/env python3
"""Export reproducible v1.2 demo inputs from Wei's backend seed, never API results."""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

# These modules do not construct the API's global database.
from backend.retail import DEMO_DATE, DEMO_SOURCE, demo_dataset
from backend.store import (
    EXPIRY_WORKBENCH_DEFAULTS, PROCUREMENT_WORKBENCH_DEFAULTS,
    TRANSFER_WORKBENCH_DEFAULTS, Store,
)

TABLES = ("stores", "inventory_inputs", "confirmed_payments", "risk_inputs")
METADATA = {
    "contract_version": "v1.2", "snapshot_id": "snapshot-demo-v1",
    "as_of_date": DEMO_DATE.isoformat(), "is_demo": True, "synthetic": True,
    "source": DEMO_SOURCE, "timezone": "Asia/Shanghai",
    "generation": "deterministic_backend_seed",
    "units": {"money": "CNY", "percentage": "0..100", "quantity": "商品单位"},
    "input_origin": "backend.store.Store.seed_demo + backend.retail.demo_dataset",
    "disclaimer": "合成输入导出，不是客户数据、API响应、模型输出或真实收益；下载不会导入或重置服务。",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value).__name__)


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, default=_decimal) + "\n").encode("utf-8")


def _csv(rows):
    buffer = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
                         else str(value).lower() if isinstance(value, bool) else value
                         for key, value in row.items()})
    return buffer.getvalue().encode("utf-8")


def build_dataset():
    """Read stable inputs from an explicitly isolated, disposable seed database."""
    with tempfile.TemporaryDirectory(prefix="inventory-demo-export-") as directory:
        # The network input currently lives in api.py, whose import opens a Store.
        # Isolate that import in a child process so no caller's API Store is replaced.
        env = {**os.environ, "INVENTORY_AGENT_DB": str(Path(directory) / "api-import.db"),
               "INVENTORY_AGENT_MODE": "real", "PYTHONIOENCODING": "utf-8"}
        network = subprocess.run(
            [sys.executable, "-c", "import json; from backend import api; "
             "print(json.dumps(api.TRANSFER_NETWORK_STORES, ensure_ascii=False)); api.store.close()"],
            cwd=PROJECT, env=env, check=True, capture_output=True, text=True, encoding="utf-8",
        )
        seed = Store(str(Path(directory) / "seed.db"))
        try:
            seed.seed_demo()
            risks = seed.risks("demo")
            retail = demo_dataset(risks, json.loads(network.stdout))
        finally:
            seed.close()
    risk_fields = ("id", "sku", "product", "store", "store_id", "sales_30", "inventory_qty",
                   "unit_cost", "comparison", "tags", "observation", "missing_fields")
    modules = {"transfer": TRANSFER_WORKBENCH_DEFAULTS, "expiry-rescue": EXPIRY_WORKBENCH_DEFAULTS,
               "procurement-brake": PROCUREMENT_WORKBENCH_DEFAULTS}
    return {
        **METADATA,
        "assumptions": [
            "门店与输入取自当前后端内置种子；日期固定为2026-10-03，无随机运行时间或UUID。",
            "零售普通商品按袋、瓶或盒计，风险商品保持后端的件；不能把包装说明直接换算为数量。",
            "daily_demand、safety_days和target_days是合成需求与规则输入，不是实测预测准确率。",
            "confirmed_payments为独立合成付款计划，不能从库存估值或调拨金额倒推。",
            "工作台默认值与经营总览的输入用途不同；保留来源，不拼接为真实交易流水。",
            "当前没有安装本包的数据导入接口；后端联调直接使用隔离数据库的seed_demo。",
        ],
        "stores": retail["stores"],
        "inventory_inputs": retail["rows"],
        "confirmed_payments": retail["confirmed_payments"],
        "risk_inputs": [{key: risk[key] for key in risk_fields} for risk in sorted(risks, key=lambda row: row["id"])],
        "workbench_inputs": [{"module_type": module, "risk_id": risk_id, "input": values}
                             for module, defaults in modules.items() for risk_id, values in sorted(defaults.items())],
    }


def build_artifacts():
    dataset = build_dataset()
    requests = read_json(ROOT / "reference" / "scenario-requests.json")
    artifacts = {"dataset.json": _json(dataset)}
    artifacts.update({f"{table}.csv": _csv(dataset[table]) for table in TABLES})
    artifacts["workbench_inputs.json"] = _json(dataset["workbench_inputs"])
    artifacts["scenario_requests.json"] = _json(requests)
    return dataset, requests, artifacts


def _manifest(output_dir, dataset, requests, artifacts):
    return {
        **METADATA,
        "record_counts": {table: len(dataset[table]) for table in (*TABLES, "workbench_inputs")},
        "scenario_count": len(requests["items"]),
        "files": {Path(filename).stem: {"path": f"{output_dir.name}/{filename}",
                                       "sha256": hashlib.sha256(content).hexdigest()}
                  for filename, content in artifacts.items()},
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
        raise ValueError("导出缺失、被修改或与当前后端种子不一致：\n" + "\n".join(failures))


def main():
    parser = argparse.ArgumentParser(description="导出或校验v1.2内置合成输入，使用临时数据库")
    parser.add_argument("--output", type=Path, default=ROOT / "generated", help="输出目录；manifest写入其父目录")
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
        print(f"generated {len(manifest['files'])} input files; snapshot=snapshot-demo-v1; contract=v1.2")


if __name__ == "__main__":
    main()
