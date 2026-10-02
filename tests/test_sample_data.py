"""Verify synthetic fixtures against production domain functions and import schemas."""

import csv
from datetime import date, datetime
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
import unittest

from backend import domain
from backend.api import DataImportInput, _import_schemas, _read_import_rows
from tests.sample_data_generator import load_generator


ROOT = Path(__file__).resolve().parents[1] / "sample-data"


class SampleDataTests(unittest.TestCase):
    def assert_result(self, actual, expected):
        if isinstance(expected, dict):
            for key, value in expected.items():
                self.assertIn(key, actual)
                self.assert_result(actual[key], value)
        else:
            self.assertEqual(actual, expected)

    def test_checked_in_package_is_current_and_regeneration_is_identical(self):
        generator = load_generator()
        generator.verify(ROOT / "generated")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "generated"
            manifest = generator.generate(output)
            self.assertEqual(manifest["metadata"]["seed"], 20261002)
            self.assertTrue(manifest["metadata"]["is_sample"])
            for entry in manifest["files"].values():
                self.assertEqual((ROOT / entry["path"]).read_bytes(), (output.parent / entry["path"]).read_bytes())
            self.assertEqual((ROOT / "manifest.json").read_bytes(), (output.parent / "manifest.json").read_bytes())
            generator.verify(output)
            (output / "inventory.csv").write_text("modified", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inventory.csv"):
                generator.verify(output)
            generator.generate(output)
            generator.verify(output)
            (output / "sales.csv").unlink()
            with self.assertRaisesRegex(ValueError, "sales.csv"):
                generator.verify(output)

    def test_import_files_match_the_existing_api_contract(self):
        schemas = _import_schemas()
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        kinds = set()
        for entry in manifest["files"].values():
            if "data_kind" not in entry:
                continue
            kind = entry["data_kind"]
            kinds.add(kind)
            content = (ROOT / entry["path"]).read_text(encoding="utf-8")
            rows, headers, error = _read_import_rows(DataImportInput(filename=Path(entry["path"]).name, content=content, data_kind=kind))
            with self.subTest(kind=kind):
                self.assertIsNone(error)
                self.assertTrue(rows)
                self.assertTrue(set(schemas[kind]["required"]).issubset(headers))
                self.assertTrue(all(row["is_sample"] == "True" for row in rows))
        self.assertEqual(kinds, set(schemas))

    def test_every_domain_scenario_matches_independent_expected_results(self):
        cases = json.loads((ROOT / "generated/scenarios.json").read_text(encoding="utf-8"))["items"]
        expected = json.loads((ROOT / "generated/expected_results.json").read_text(encoding="utf-8"))["items"]
        expectations = {item["scenario_id"]: item["expected"] for item in expected}
        self.assertEqual({case["id"] for case in cases}, set(expectations))
        self.assertEqual(len(cases), len(expectations))
        for case in cases:
            if case["type"] != "domain":
                continue
            with self.subTest(scenario=case["id"]):
                operation = case["operation"]
                if operation == "teacher_baseline":
                    actual = domain.teacher_baseline(case["inventory"])
                elif operation in {"calculate_transfer", "calculate_expiry_rescue", "calculate_procurement_brake"}:
                    actual = getattr(domain, operation)(case["input"])
                elif operation == "solve_cash_goal":
                    actual = domain.solve_cash_goal(**{**case["input"], "target": Decimal(case["input"]["target"])})
                else:
                    actual = getattr(domain, operation)(**case["input"])
                self.assert_result(actual, expectations[case["id"]])

    def test_unknown_sales_remain_distinct_from_zero_and_stockout(self):
        rows = list(csv.DictReader(io.StringIO((ROOT / "generated/inventory.csv").read_text(encoding="utf-8"))))
        by_case = {row["scenario_id"]: row for row in rows}
        self.assertEqual(by_case["missing_fields"]["sales_30"], "")
        self.assertEqual(by_case["zero_sales"]["sales_30"], "0")
        self.assertEqual(by_case["store_shortage"]["inventory_qty"], "0")
        shortage = domain.teacher_baseline(by_case["store_shortage"])
        self.assertTrue(shortage["stockout"])
        self.assertFalse(shortage["candidate"])
        snapshot = json.loads((ROOT / "generated/snapshot.json").read_text(encoding="utf-8"))
        missing = next(row for row in snapshot["inventory"] if row["scenario_id"] == "missing_fields")
        self.assertIsNone(missing["sales_30"])

    def test_feedback_evaluation_corpus_has_grounded_annotations_without_model_scores(self):
        corpus = json.loads((ROOT / "feedback-evaluation.json").read_text(encoding="utf-8"))
        metadata, items = corpus["metadata"], corpus["items"]
        self.assertTrue(metadata["is_sample"])
        self.assertEqual(metadata["evaluation_status"], "not_run")
        self.assertEqual(metadata["annotation_status"], "reference_pending_business_review")
        self.assertIsNone(metadata["model"])
        self.assertIsNone(metadata["metrics"])
        self.assertEqual(len(items), 24)
        self.assertEqual(metadata["record_count"], len(items))
        self.assertEqual(len({item["id"] for item in items}), len(items))
        covered_tags = {tag for item in items for tag in item["tags"]}
        self.assertTrue({
            "explicit", "relative_time", "quantity", "constraint", "conflict", "missing",
            "ambiguous", "zero_sales", "stockout", "negation", "unknown_entity",
            "multiple_entities", "supplier_terms", "expiry", "unit_mismatch", "amount",
            "invalid_date", "conditional", "prompt_injection",
        }.issubset(covered_tags))
        for item in items:
            with self.subTest(case=item["id"]):
                payload, reference = item["input"], item["reference"]
                self.assertIsInstance(payload["raw_text"], str)
                self.assertTrue(payload["raw_text"].strip())
                self.assertEqual(payload["timezone"], "Asia/Shanghai")
                self.assertIsNotNone(datetime.fromisoformat(payload["submitted_at"]).utcoffset())
                self.assertTrue(reference["requires_manual_review"])
                self.assertTrue(reference["review_reasons"])
                for key in ("products", "stores", "times", "quantities", "constraints", "missing_fields", "conflicts", "ambiguities", "review_reasons"):
                    self.assertIsInstance(reference[key], list)
                for key in ("products", "stores", "times", "quantities"):
                    for mention in reference[key]:
                        self.assertIn(mention["text"], payload["raw_text"])
                for constraint in reference["constraints"]:
                    self.assertIn(constraint, payload["raw_text"])
                for quantity in reference["quantities"]:
                    self.assertTrue(quantity["unit"])
                    self.assertTrue(quantity["role"])
                    self.assertTrue(quantity["value"] is None or type(quantity["value"]) in (int, float))
                for time in reference["times"]:
                    self.assertIn(time["kind"], {"absolute_day", "relative_day", "period", "ambiguous", "invalid", "conditional_deadline"})
                    for key in ("start_date", "end_date"):
                        if time[key] is not None:
                            date.fromisoformat(time[key])
                    if time["kind"] in {"ambiguous", "invalid"}:
                        self.assertIsNone(time["start_date"])
                        self.assertIsNone(time["end_date"])


if __name__ == "__main__":
    unittest.main()
