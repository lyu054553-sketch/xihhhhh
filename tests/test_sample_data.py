"""Check v0.3 input integrity and independent references, without running business logic."""

import csv
from datetime import date, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from tests.sample_data_generator import load_generator


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample-data"
AGENTS = {"slow_moving", "store_transfer", "near_expiry", "procurement_brake", "cashflow_simulation"}
STATUSES = {"succeeded", "partial", "no_data", "needs_input", "awaiting_confirmation", "failed"}
TABLE_FIELDS = {
    "stores": {"store_id", "store_name", "region_id", "status"},
    "skus": {"sku_id", "sku_name", "category_id", "specification", "unit", "unit_cost_fen"},
    "inventory_snapshots": {"snapshot_id", "store_id", "sku_id", "snapshot_at", "on_hand_qty", "reserved_qty", "in_transit_qty"},
    "sales_daily": {"business_date", "store_id", "sku_id", "net_sold_qty", "sales_amount_fen"},
    "purchase_orders": {"po_id", "store_id", "sku_id", "ordered_qty", "received_qty", "open_qty"},
    "inventory_lots": {"lot_id", "store_id", "sku_id", "qty", "expiry_date"},
    "policies": {"policy_id", "policy_version", "transfer_enabled"},
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class SampleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load_generator()
        cls.dataset = read(SAMPLE / "generated/dataset.json")
        cls.manifest = read(SAMPLE / "manifest.json")
        cls.requests = read(SAMPLE / "reference/scenario-requests.json")["items"]
        cls.expected = read(SAMPLE / "reference/expected-results.json")["items"]
        cls.quality = {case["id"]: case for case in read(SAMPLE / "reference/data-quality-cases.json")["items"]}

    def assert_money(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("_fen") and child is not None:
                    self.assertIs(type(child), int, key)
                    self.assertGreaterEqual(child, 0, key)
                    self.assertLessEqual(child, 2**53 - 1, key)
                self.assert_money(child)
        elif isinstance(value, list):
            for child in value:
                self.assert_money(child)

    def assert_request(self, request, data_version="snack-demo-v1"):
        self.assertEqual(str(UUID(request["request_id"])), request["request_id"])
        self.assertIn(request["agent_type"], AGENTS)
        self.assertEqual(request["scope"]["as_of"], "2026-10-02")
        self.assertEqual(request["data_version"], data_version)
        self.assertEqual(request["policy_version"], "snack-policy-v1")
        self.assertIsInstance(request["params"], dict)
        self.assert_money(request)

    def test_versions_counts_and_scope_catalog(self):
        for source in (self.dataset, self.manifest):
            self.assertEqual(source["contract_version"], "v0.3")
            self.assertEqual(source["data_version"], "snack-demo-v1")
            self.assertEqual(source["policy_version"], "snack-policy-v1")
            self.assertEqual(source["as_of"], "2026-10-02")
            self.assertEqual(source["seed"], 20261002)
            self.assertIs(source["synthetic"], True)
        self.assertEqual(self.manifest["record_counts"], {
            "stores": 3, "skus": 4, "inventory_snapshots": 5, "sales_daily": 76,
            "purchase_orders": 1, "inventory_lots": 1, "policies": 3,
        })
        self.assertEqual(self.manifest["scope_options"]["stores"], self.dataset["stores"])
        self.assertEqual(self.manifest["scope_options"]["skus"], self.dataset["skus"])
        self.assertEqual(self.manifest["scenario_count"], 5)

    def test_regeneration_is_byte_exact_and_lf(self):
        self.generator.verify(SAMPLE / "generated")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "generated"
            self.generator.generate(target)
            self.generator.verify(target)
            self.assertEqual((target.parent / "manifest.json").read_bytes(), (SAMPLE / "manifest.json").read_bytes())
            for entry in self.manifest["files"].values():
                current = (SAMPLE / entry["path"]).read_bytes()
                self.assertEqual((target / Path(entry["path"]).name).read_bytes(), current)
                self.assertNotIn(b"\r", current)
            self.generator.generate(target)
            self.generator.verify(target)

    def test_manifest_hashes_and_paths_are_inputs_only(self):
        self.assertEqual(set(self.manifest["files"]), {"dataset", "scenario_requests", *TABLE_FIELDS})
        for entry in self.manifest["files"].values():
            path = (SAMPLE / entry["path"]).resolve()
            self.assertTrue(path.is_relative_to((SAMPLE / "generated").resolve()))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
            self.assertNotIn("expected", entry["path"])
            self.assertNotIn("response", entry["path"])

    def test_verification_detects_missing_and_modified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "generated"
            self.generator.generate(target)
            (target / "sales_daily.csv").write_bytes(b"not-the-declared-input\n")
            with self.assertRaises(ValueError):
                self.generator.verify(target)
            self.generator.generate(target)
            (target / "skus.csv").unlink()
            with self.assertRaises(ValueError):
                self.generator.verify(target)
            self.generator.generate(target)
            self.generator.verify(target)

    def test_shared_models_fields_units_and_foreign_keys(self):
        stores = {row["store_id"] for row in self.dataset["stores"]}
        skus = {row["sku_id"] for row in self.dataset["skus"]}
        self.assertEqual(stores, {"STORE-HZ-001", "STORE-HZ-002", "STORE-HZ-003"})
        self.assertEqual(skus, {"SNK-001", "SNK-002", "SNK-003", "SNK-004"})
        self.assertEqual({row["sku_id"]: row["unit"] for row in self.dataset["skus"]}, {
            "SNK-001": "bag", "SNK-002": "bag", "SNK-003": "bottle", "SNK-004": "bag",
        })
        for table, fields in TABLE_FIELDS.items():
            for row in self.dataset[table]:
                self.assertTrue(fields <= row.keys(), (table, row))
                if "store_id" in row:
                    self.assertIn(row["store_id"], stores)
                if "sku_id" in row:
                    self.assertIn(row["sku_id"], skus)
                for key, value in row.items():
                    if key.endswith("_qty") or key == "qty":
                        self.assertIs(type(value), int, (table, key))
                        self.assertGreaterEqual(value, 0)
            self.assert_money(self.dataset[table])

    def test_csv_preserves_all_model_fields_and_rows(self):
        for table in TABLE_FIELDS:
            rows = list(csv.DictReader(io.StringIO((SAMPLE / f"generated/{table}.csv").read_text(encoding="utf-8"))))
            originals = self.dataset[table]
            self.assertEqual(len(rows), len(originals))
            for actual, original in zip(rows, originals):
                for key, value in original.items():
                    expected = "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
                    self.assertEqual(actual[key], expected, (table, key))

    def test_daily_sales_window_has_explicit_zero_and_no_missing_dates(self):
        end = date(2026, 10, 2)
        dates = {(end - timedelta(days=offset)).isoformat() for offset in range(14)}
        expected_totals = {("STORE-HZ-001", "SNK-001"): 28, ("STORE-HZ-002", "SNK-001"): 56,
                           ("STORE-HZ-001", "SNK-002"): 0, ("STORE-HZ-002", "SNK-004"): 14,
                           ("STORE-HZ-003", "SNK-002"): 28}
        unique = {(row["store_id"], row["sku_id"], row["business_date"]) for row in self.dataset["sales_daily"]}
        self.assertEqual(len(unique), len(self.dataset["sales_daily"]))
        for pair, total in expected_totals.items():
            rows = [row for row in self.dataset["sales_daily"] if (row["store_id"], row["sku_id"]) == pair and row["business_date"] in dates]
            self.assertEqual({row["business_date"] for row in rows}, dates)
            self.assertEqual(sum(row["net_sold_qty"] for row in rows), total)
        self.assertFalse(any(row["sku_id"] == "SNK-003" for row in self.dataset["sales_daily"]))

    def test_last_sale_has_complete_nineteen_day_evidence(self):
        rows = [row for row in self.dataset["sales_daily"] if row["store_id"] == "STORE-HZ-001" and row["sku_id"] == "SNK-002"]
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]["business_date"], "2026-09-13")
        self.assertEqual(rows[0]["net_sold_qty"], 1)
        self.assertEqual([row["business_date"] for row in rows[1:]], [(date(2026, 9, 14) + timedelta(days=i)).isoformat() for i in range(19)])
        self.assertTrue(all(row["net_sold_qty"] == 0 for row in rows[1:]))

    def test_snapshot_cutoff_po_summary_and_lot_consistency(self):
        for snapshot in self.dataset["inventory_snapshots"]:
            self.assertEqual(datetime.fromisoformat(snapshot["snapshot_at"]).isoformat(), "2026-10-02T23:59:59+08:00")
            self.assertLessEqual(snapshot["reserved_qty"], snapshot["on_hand_qty"])
            orders = [row for row in self.dataset["purchase_orders"] if row["store_id"] == snapshot["store_id"] and row["sku_id"] == snapshot["sku_id"]]
            self.assertEqual(snapshot["in_transit_qty"], sum(row["open_qty"] for row in orders))
            lots = [row for row in self.dataset["inventory_lots"] if row["store_id"] == snapshot["store_id"] and row["sku_id"] == snapshot["sku_id"]]
            if lots:
                self.assertEqual(sum(row["qty"] for row in lots), snapshot["on_hand_qty"])
        order = self.dataset["purchase_orders"][0]
        self.assertEqual(order["ordered_qty"] - order["received_qty"], order["open_qty"])
        self.assertEqual((order["open_qty"], order["expected_arrival_date"], order["cancellable_until"]), (30, "2026-10-05", "2026-10-04"))

    def test_five_requests_and_independent_golden_references(self):
        self.assertEqual({item["request"]["agent_type"] for item in self.requests}, AGENTS)
        self.assertEqual({item["id"] for item in self.requests}, {item["scenario_id"] for item in self.expected})
        for item in self.requests:
            self.assert_request(item["request"])
            if "preview_request" in item:
                self.assert_request(item["preview_request"])
                self.assertEqual(item["preview_request"]["params"]["operation"], "preview")
        values = {item["agent_type"]: item["expected"] for item in self.expected}
        self.assertIsNone(values["slow_moving"]["days_of_supply"])
        self.assertEqual(values["slow_moving"]["excess_value_at_cost_fen"], 14960)
        self.assertEqual(values["store_transfer"]["recommended_transfer_qty"], 50)
        self.assertEqual(values["near_expiry"]["risk_qty"], 24)
        self.assertEqual(values["procurement_brake"]["suggested_reduction_qty"], 6)
        self.assertEqual(values["cashflow_simulation"]["estimated_avoided_purchase_commitment_fen"], 5280)
        self.assert_money(self.expected)

    def test_isolated_quality_inputs_cover_real_defects(self):
        self.assertEqual(set(self.quality), {"normal-stock", "zero-sales", "missing-cost", "missing-policy", "missing-sales-day", "unknown-entity", "inventory-conflict", "missing-expiry", "lot-stock-conflict"})
        for case in self.quality.values():
            dataset = case["input_dataset"]
            self.assertNotEqual(dataset["data_version"], "snack-demo-v1")
            self.assertTrue(set(TABLE_FIELDS) <= dataset.keys())
            self.assert_request(case["request"], dataset["data_version"])
            self.assertTrue(case["reference"]["review_reasons"])
        self.assertIsNone(self.quality["missing-cost"]["input_dataset"]["skus"][0]["unit_cost_fen"])
        self.assertFalse(self.quality["missing-policy"]["input_dataset"]["policies"])
        missing = self.quality["missing-sales-day"]["input_dataset"]["sales_daily"]
        self.assertEqual(len(missing), 13)
        self.assertFalse(any(row["business_date"] == "2026-09-25" for row in missing))
        unknown = self.quality["unknown-entity"]["input_dataset"]
        self.assertNotIn(unknown["inventory_snapshots"][0]["sku_id"], {row["sku_id"] for row in unknown["skus"]})
        conflict = self.quality["inventory-conflict"]["input_dataset"]["inventory_snapshots"][0]
        self.assertGreater(conflict["reserved_qty"], conflict["on_hand_qty"])
        self.assertIsNone(self.quality["missing-expiry"]["input_dataset"]["inventory_lots"][0]["expiry_date"])
        lots = self.quality["lot-stock-conflict"]["input_dataset"]
        self.assertNotEqual(lots["inventory_lots"][0]["qty"], lots["inventory_snapshots"][0]["on_hand_qty"])
        self.assertFalse(self.quality["normal-stock"]["reference"]["requires_manual_review"])

    def test_six_response_fixtures_are_explicit_test_envelopes(self):
        fields = {"request_id", "run_id", "agent_type", "status", "summary", "session_id", "assistant_message", "scenario_preview", "steps", "items", "missing_fields", "follow_up_questions", "warnings", "error", "data_version", "policy_version", "created_at", "completed_at"}
        for status in STATUSES:
            response = read(ROOT / f"tests/fixtures/v03/response-{status}.json")
            self.assertTrue(fields <= response.keys())
            self.assertEqual(response["status"], status)
            self.assertEqual(response["data_version"], "snack-demo-v1")
            self.assert_money(response)
            if status != "needs_input":
                self.assertEqual(response["follow_up_questions"], [])
            if status in {"failed", "awaiting_confirmation", "no_data", "needs_input"}:
                self.assertEqual(response["items"], [])
            for item in response["items"]:
                self.assertTrue(item["evidence"])
                for evidence in item["evidence"]:
                    self.assertTrue({"source", "record_id", "field", "value", "as_of"} <= evidence.keys())

    def test_feedback_requests_and_evidence_spans(self):
        feedback = read(SAMPLE / "feedback-evaluation.json")
        self.assertEqual(feedback["metadata"]["record_count"], 24)
        self.assertEqual(len(feedback["items"]), 24)
        self.assertEqual(len({item["id"] for item in feedback["items"]}), 24)
        self.assertEqual(feedback["metadata"]["evaluation_status"], "not_run")
        self.assertIsNone(feedback["metadata"]["model"])
        self.assertIsNone(feedback["metadata"]["metrics"])
        tags = set()
        for item in feedback["items"]:
            self.assert_request(item["input"])
            raw = item["input"]["user_input"]
            reference = item["reference"]
            tags.update(item["tags"])
            self.assertTrue(reference["requires_manual_review"])
            self.assertTrue(reference["review_reasons"])
            for group in ("products", "stores", "times", "quantities"):
                for annotation in reference[group]:
                    self.assertIn(annotation["text"], raw, item["id"])
            for constraint in reference["constraints"]:
                self.assertIn(constraint, raw, item["id"])
            for quantity in reference["quantities"]:
                self.assertTrue(quantity["unit"])
                self.assertTrue(quantity["role"])
                self.assertTrue(quantity["value"] is None or type(quantity["value"]) is int)
            for time in reference["times"]:
                if time["kind"] in {"invalid", "ambiguous"}:
                    self.assertIsNone(time["start_date"])
                    self.assertIsNone(time["end_date"])
                else:
                    self.assertLessEqual(date.fromisoformat(time["start_date"]), date.fromisoformat(time["end_date"]))
        self.assertTrue({"explicit", "relative_time", "ambiguous", "missing", "unknown_entity", "conflict", "zero_sales", "negation", "multiple_entities", "supplier_terms", "unit_mismatch", "amount", "invalid_date", "prompt_injection", "conditional"} <= tags)

    def test_feedback_date_zero_unknown_and_money_annotations(self):
        items = read(SAMPLE / "feedback-evaluation.json")["items"]
        self.assertEqual(items[1]["reference"]["times"][0]["start_date"], "2026-10-01")
        self.assertEqual(items[1]["reference"]["times"][1]["start_date"], "2026-10-02")
        self.assertEqual(items[2]["reference"]["times"][0]["start_date"], "2026-09-01")
        self.assertEqual(items[2]["reference"]["times"][0]["end_date"], "2026-09-30")
        self.assertEqual(items[9]["reference"]["times"][0]["start_date"], "2026-10-03")
        self.assertEqual(items[17]["reference"]["times"][0]["start_date"], "2026-10-14")
        self.assertEqual(items[10]["reference"]["quantities"][0]["value"], 0)
        self.assertIsNone(items[11]["reference"]["quantities"][1]["value"])
        self.assertEqual([(q["value"], q["unit"]) for q in items[20]["reference"]["quantities"]], [(880, "fen/bag"), (20, "bag"), (850, "fen")])
        self.assertEqual(items[22]["reference"]["quantities"][1]["value"], 1000000)
        self.assertEqual(items[22]["reference"]["constraints"], [])


if __name__ == "__main__":
    unittest.main()
