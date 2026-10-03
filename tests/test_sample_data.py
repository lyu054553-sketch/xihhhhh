"""Verify v1.2 seed exports and independent simulation boundary references."""

import csv
from copy import deepcopy
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.retail import simulate_purchase
from tests.sample_data_generator import load_generator

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample-data"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SampleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load_generator()
        cls.dataset = read(SAMPLE / "generated/dataset.json")
        cls.manifest = read(SAMPLE / "manifest.json")
        cls.requests = read(SAMPLE / "reference/scenario-requests.json")["items"]

    def test_checked_in_export_matches_current_backend_seed(self):
        self.generator.verify(SAMPLE / "generated")

    def test_repeated_export_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "generated"
            self.generator.generate(output)
            first = {path.name: path.read_bytes() for path in output.iterdir()}
            manifest = (output.parent / "manifest.json").read_bytes()
            self.generator.generate(output)
            self.assertEqual(first, {path.name: path.read_bytes() for path in output.iterdir()})
            self.assertEqual(manifest, (output.parent / "manifest.json").read_bytes())

    def test_export_does_not_open_callers_database(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "user.db"
            sentinel.write_bytes(b"must not be opened as sqlite")
            with patch.dict(os.environ, {"INVENTORY_AGENT_DB": str(sentinel), "INVENTORY_AGENT_MODE": "real"}):
                self.assertEqual(self.generator.build_dataset()["snapshot_id"], "snapshot-demo-v1")
                self.assertEqual(os.environ["INVENTORY_AGENT_DB"], str(sentinel))
            self.assertEqual(sentinel.read_bytes(), b"must not be opened as sqlite")

    def test_manifest_hashes_and_newlines_cover_only_current_inputs(self):
        paths = set()
        for entry in self.manifest["files"].values():
            path = SAMPLE / entry["path"]
            self.assertEqual(path.parent, SAMPLE / "generated")
            content = path.read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), entry["sha256"])
            self.assertNotIn(b"\r\n", content)
            paths.add(path.name)
        self.assertEqual(paths, {path.name for path in (SAMPLE / "generated").iterdir() if path.is_file()})
        self.assertNotIn("expected-results.json", paths)
        self.assertNotIn("feedback-evaluation.json", paths)

    def test_source_units_and_counts_are_explicit(self):
        self.assertEqual(self.manifest["contract_version"], "v1.2")
        self.assertEqual(self.manifest["units"]["money"], "CNY")
        self.assertEqual(self.manifest["units"]["percentage"], "0..100")
        self.assertEqual(self.manifest["as_of_date"], "2026-10-03")
        self.assertTrue(self.manifest["synthetic"] and self.manifest["is_demo"])
        self.assertEqual(self.manifest["record_counts"], {
            "stores": 50, "inventory_inputs": 313, "confirmed_payments": 100,
            "risk_inputs": 13, "workbench_inputs": 11,
        })
        for table, count in self.manifest["record_counts"].items():
            self.assertEqual(len(self.dataset[table]), count)

    def test_store_sku_relationships_and_quantity_units_are_preserved(self):
        stores = {row["id"] for row in self.dataset["stores"]}
        pairs = set()
        for row in self.dataset["inventory_inputs"]:
            self.assertIn(row["store_id"], stores)
            self.assertNotIn((row["store_id"], row["sku"]), pairs)
            pairs.add((row["store_id"], row["sku"]))
            self.assertIn(row["unit"], {"袋", "瓶", "盒", "件"})
            self.assertGreaterEqual(row["on_hand"], 0)
            self.assertGreaterEqual(row["in_transit"], 0)
        for row in self.dataset["risk_inputs"]:
            self.assertIn((row["store_id"], row["sku"]), pairs)
        for row in self.dataset["confirmed_payments"]:
            self.assertIn(row["store_id"], stores)

    def test_money_remains_yuan_with_at_most_two_decimals(self):
        amounts = [row[key] for row in self.dataset["inventory_inputs"] for key in ("unit_cost", "unit_price")]
        amounts += [row["amount"] for row in self.dataset["confirmed_payments"]]
        for amount in amounts:
            value = Decimal(str(amount))
            self.assertGreaterEqual(value, 0)
            self.assertEqual(value, value.quantize(Decimal("0.01")))
        nuts = next(row for row in self.dataset["risk_inputs"] if row["id"] == 1)
        self.assertEqual(nuts["unit_cost"], 80)

    def test_export_has_no_api_results_or_runtime_identifiers(self):
        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertNotIn(key, {"metrics", "weekly", "run_id", "request_id", "created_at",
                                           "proposal_id", "proposal_version", "calculation", "account"})
                    self.assertFalse(key.endswith("_fen"))
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(self.dataset)

    def test_csv_rows_match_json_counts_and_identifiers(self):
        for table in self.generator.TABLES:
            rows = list(csv.DictReader(io.StringIO((SAMPLE / f"generated/{table}.csv").read_text(encoding="utf-8"))))
            expected = self.dataset[table]
            self.assertEqual(len(rows), len(expected))
            for actual, source in zip(rows, expected):
                self.assertTrue(set(source).issubset(actual))
                self.assertTrue(all(actual[key] == "" for key in set(actual) - set(source)))
                for key in ("store_id", "sku", "unit", "order_id"):
                    if key in source:
                        self.assertEqual(actual[key], str(source[key]))

    def test_requests_use_live_v12_routes_and_parameters(self):
        stores = {"all", *(row["id"] for row in self.dataset["stores"])}
        categories = {row["category"] for row in self.dataset["inventory_inputs"]}
        self.assertEqual(len(self.requests), self.manifest["scenario_count"])
        self.assertEqual(len({item["id"] for item in self.requests}), len(self.requests))
        for item in self.requests:
            self.assertNotIn("agent-runs", item["path"])
            if item["method"] == "POST":
                body = item["body"]
                self.assertEqual(item["path"], "/api/v1/retail/simulate")
                self.assertGreaterEqual(body["horizon_days"], 1)
                self.assertLessEqual(body["horizon_days"], 90)
                self.assertGreaterEqual(body["reduction_pct"], 0)
                self.assertLessEqual(body["reduction_pct"], 100)
                self.assertIn(body["store_id"], stores)
                self.assertIn(body["category"], {None, *categories})

    def _simulate(self, scenario_id):
        request = next(item["body"] for item in self.requests if item["id"] == scenario_id)
        dataset = {"stores": self.dataset["stores"], "rows": deepcopy(self.dataset["inventory_inputs"]),
                   "as_of_date": self.dataset["as_of_date"], "source": self.dataset["source"]}
        # Decimal input precision matches the backend's own input representation.
        for row in dataset["rows"]:
            for key in ("daily_demand", "unit_cost", "unit_price"):
                row[key] = Decimal(str(row[key]))
        return simulate_purchase(dataset, **request)

    def test_zero_reduction_matches_independent_identity_reference(self):
        result = self._simulate("cash-zero")
        self.assertEqual(result["status"], "completed")
        for metric in result["metrics"].values():
            self.assertEqual(metric["baseline"], metric["scenario"])
            self.assertEqual(metric["delta"], 0)
        for row in result["weekly"]:
            self.assertEqual(row["baseline"], row["scenario"])

    def test_full_reduction_has_zero_adjustable_purchase_outflow(self):
        result = self._simulate("cash-full")
        self.assertEqual(result["metrics"]["purchase_outflow"]["scenario"], 0)
        self.assertTrue(all(row["scenario"] == 0 for row in result["weekly"]))
        self.assertTrue(all(row["scenario_purchase_qty"] == 0 for row in result["lines"]))
        self.assertGreater(len(result["risks"]), 0)

    def test_language_references_preserve_unknowns_and_unmeasured_status(self):
        corpus = read(SAMPLE / "feedback-evaluation.json")
        metadata = corpus["metadata"]
        self.assertEqual(metadata["record_count"], len(corpus["items"]))
        self.assertEqual(len(corpus["items"]), 24)
        self.assertEqual(metadata["evaluation_status"], "not_run")
        self.assertIsNone(metadata["model"])
        self.assertIsNone(metadata["metrics"])
        stores = {"all", *(row["id"] for row in self.dataset["stores"])}
        for case in corpus["items"]:
            reference = case["reference"]
            self.assertTrue(reference["requires_manual_review"])
            request = reference["request"]
            if reference["outcome"] == "confirm_scenario":
                self.assertIsNotNone(request)
                self.assertEqual(request["request_text"], case["request_text"])
                self.assertIn(request["store_id"], stores)
                self.assertGreaterEqual(request["horizon_days"], 1)
                self.assertLessEqual(request["horizon_days"], 90)
                self.assertGreaterEqual(request["reduction_pct"], 0)
                self.assertLessEqual(request["reduction_pct"], 100)
            else:
                self.assertIsNone(request, "ambiguous or unsupported text must not become an API request")

    def test_tampered_or_missing_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "generated"
            self.generator.generate(output)
            (output / "stores.csv").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.generator.verify(output)
            (output / "dataset.json").unlink()
            with self.assertRaises(ValueError):
                self.generator.verify(output)


if __name__ == "__main__":
    unittest.main()
