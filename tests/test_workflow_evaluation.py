"""Exercise observation validation, honest denominators, and empty reference templates."""

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.evaluate_workflow import EvaluationInputError, distribution, load_observations, summarize

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "sample-data/evaluation"
FIELDS = list(json.loads((EVALUATION / "workflow-schema.json").read_text(encoding="utf-8"))["items"]["properties"])


def observation(case="case-1", arm="human_gpt", **changes):
    row = {field: "" for field in FIELDS}
    row.update(case_id=case, arm=arm, status="completed", review_outcome="accepted",
               elapsed_seconds="120", human_seconds="60", human_edits="2",
               execution_status="draft_only", evidence_ref="synthetic-unit-test-evidence")
    row.update(changes)
    return row


class WorkflowEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "observations.csv"

    def write(self, rows, fields=FIELDS):
        with self.path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return self.path

    def report(self, rows):
        return summarize(load_observations(self.write(rows)))

    def test_empty_template_reports_no_observations_without_invented_zeros(self):
        result = summarize(load_observations(EVALUATION / "workflow-comparison.csv"))
        self.assertEqual(result["status"], "no_observations")
        self.assertEqual(result["completed_pairs"], 0)
        self.assertIsNone(result["arms"]["system"]["elapsed_seconds_all_observed"]["median"])
        self.assertIsNone(result["arms"]["system"]["terminal_complete_cost_total_cny"])
        self.assertIsNone(result["terminal_cost_comparison"]["system"])

    def test_same_cases_are_paired_and_deltas_keep_their_sign(self):
        result = self.report([observation(), observation(arm="system", elapsed_seconds="90", human_seconds="20", human_edits="0")])
        self.assertEqual(result["completed_pairs"], 1)
        self.assertEqual(result["accepted_pairs"], 1)
        measured = result["completed_pair_metrics"]
        self.assertEqual(measured["elapsed_seconds"]["system_minus_human_gpt"]["median"], -30)
        self.assertEqual(measured["human_edits"]["system"]["total"], 0)

    def test_percentiles_use_the_documented_linear_interpolation(self):
        result = distribution([100, 0, 20, 10, None])
        self.assertEqual(result, {"n": 4, "min": 0, "median": 15, "p90": 76, "max": 100, "total": 130})

    def test_unpaired_cases_do_not_enter_comparisons(self):
        result = self.report([observation(), observation(case="other", arm="system", elapsed_seconds="1")])
        self.assertEqual(result["completed_pairs"], 0)
        self.assertEqual(len(result["missing_arm_rows"]), 2)
        self.assertEqual(result["arms"]["system"]["rows"], 1)
        self.assertEqual(result["completed_pair_metrics"]["elapsed_seconds"]["paired_cases"], 0)

    def test_failures_remain_in_denominators_and_terminal_costs(self):
        costs = {"model_cost_cny": "0.100000", "labor_cost_cny": "2", "other_cost_cny": "0"}
        result = self.report([observation(**costs), observation(arm="system", status="failed", review_outcome="not_assessed", **costs)])
        self.assertEqual(result["completed_pairs"], 0)
        self.assertEqual(result["arms"]["system"]["status_counts"]["failed"], 1)
        self.assertEqual(result["terminal_cost_comparison"]["paired_cases"], 1)
        self.assertEqual(result["terminal_cost_comparison"]["system"], "2.100000")
        self.assertEqual(result["incomplete_cases"][0]["statuses"]["system"], "failed")

    def test_missing_costs_are_not_zero_or_a_complete_total(self):
        result = self.report([observation(model_cost_cny="0.12", labor_cost_cny="", other_cost_cny="0")])
        arm = result["arms"]["human_gpt"]
        self.assertEqual(arm["known_cost_components"]["model_cost_cny"]["total_cny"], "0.120000")
        self.assertIsNone(arm["known_cost_components"]["labor_cost_cny"]["total_cny"])
        self.assertIsNone(arm["terminal_complete_cost_total_cny"])
        self.assertEqual(arm["missing_measurements_in_observed_rows"]["labor_cost_cny"], 1)

    def test_sub_cent_model_costs_are_preserved_exactly(self):
        result = self.report([observation(model_cost_cny="0.000123", labor_cost_cny="0", other_cost_cny="0.000234")])
        self.assertEqual(result["arms"]["human_gpt"]["terminal_complete_cost_total_cny"], "0.000357")

    def test_unmeasured_human_time_has_its_own_pair_denominator(self):
        result = self.report([observation(), observation(arm="system", human_seconds="")])
        self.assertEqual(result["completed_pair_metrics"]["elapsed_seconds"]["paired_cases"], 1)
        self.assertEqual(result["completed_pair_metrics"]["human_seconds"]["paired_cases"], 0)
        self.assertIsNone(result["completed_pair_metrics"]["human_seconds"]["system"]["median"])

    def test_completed_and_accepted_are_separate(self):
        rows = [observation(), observation(arm="system"),
                observation(case="case-2"), observation(case="case-2", arm="system", review_outcome="rejected")]
        result = self.report(rows)
        self.assertEqual(result["completed_pairs"], 2)
        self.assertEqual(result["accepted_pairs"], 1)
        self.assertEqual(result["arms"]["system"]["review_counts"]["rejected"], 1)

    def test_in_progress_costs_are_not_reported_as_terminal_full_cost(self):
        result = self.report([observation(status="in_progress", review_outcome="not_assessed",
                                          model_cost_cny="1", labor_cost_cny="0", other_cost_cny="0")])
        arm = result["arms"]["human_gpt"]
        self.assertIsNone(arm["terminal_complete_cost_total_cny"])
        self.assertEqual(arm["known_cost_components"]["model_cost_cny"]["total_cny"], "1.000000")

    def test_duplicate_case_arm_is_rejected(self):
        with self.assertRaisesRegex(EvaluationInputError, "duplicate"):
            load_observations(self.write([observation(), observation()]))

    def test_invalid_numbers_and_fractional_edit_counts_are_rejected(self):
        for field, value in [("elapsed_seconds", "-1"), ("elapsed_seconds", "NaN"), ("human_seconds", "Infinity"),
                             ("model_cost_cny", "0.0000001"), ("model_cost_cny", "1e3"), ("human_edits", "1.5")]:
            with self.subTest(field=field, value=value), self.assertRaises(EvaluationInputError):
                load_observations(self.write([observation(**{field: value})]))

    def test_completed_but_untimed_rows_remain_completed_and_unmeasured(self):
        result = self.report([observation(), observation(arm="system", elapsed_seconds="")])
        self.assertEqual(result["completed_pairs"], 1)
        self.assertEqual(result["timed_completed_pairs"], 0)
        self.assertEqual(result["arms"]["system"]["missing_measurements_in_observed_rows"]["elapsed_seconds"], 1)
        self.assertEqual(result["completed_pair_metrics"]["elapsed_seconds"]["paired_cases"], 0)

    def test_measurement_or_assessment_without_evidence_is_rejected(self):
        with self.assertRaises(EvaluationInputError):
            load_observations(self.write([observation(evidence_ref="")]))

    def test_not_run_can_be_registered_but_cannot_contain_measurements(self):
        row = {field: "" for field in FIELDS}
        row.update(case_id="pending", arm="system", status="not_run", review_outcome="not_assessed", execution_status="not_started")
        self.assertEqual(self.report([row])["status"], "no_observations")
        row["model_cost_cny"] = "0"
        with self.assertRaises(EvaluationInputError):
            load_observations(self.write([row]))

    def test_actual_execution_needs_a_distinct_receipt_reference(self):
        with self.assertRaisesRegex(EvaluationInputError, "execution_evidence_ref"):
            load_observations(self.write([observation(execution_status="performed")]))
        report = self.report([observation(execution_status="performed", execution_evidence_ref="synthetic-test-receipt")])
        self.assertEqual(report["arms"]["human_gpt"]["execution_counts"]["performed"], 1)

    def test_accepted_cannot_hide_a_failed_workflow(self):
        with self.assertRaisesRegex(EvaluationInputError, "accepted"):
            load_observations(self.write([observation(status="failed")]))

    def test_duplicate_headers_and_ragged_rows_are_rejected(self):
        self.path.write_text(",".join(FIELDS + ["arm"]) + "\n", encoding="utf-8")
        with self.assertRaises(EvaluationInputError):
            load_observations(self.path)
        self.path.write_text(",".join(FIELDS) + "\ncase-1,system,completed\n", encoding="utf-8")
        with self.assertRaises(EvaluationInputError):
            load_observations(self.path)

    def test_cli_rejects_bad_input_before_creating_report(self):
        self.write([observation(elapsed_seconds="bad")])
        output = Path(self.temporary.name) / "report.json"
        run = subprocess.run([sys.executable, str(ROOT / "scripts/evaluate_workflow.py"),
                              "--input", str(self.path), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertFalse(output.exists())
        self.assertIn("elapsed_seconds", run.stderr)

    def test_reference_corpus_is_synthetic_unrun_and_quotes_actual_source(self):
        corpus = json.loads((EVALUATION / "store-feedback-reference.json").read_text(encoding="utf-8"))
        metadata = corpus["metadata"]
        self.assertTrue(metadata["synthetic"])
        self.assertEqual(metadata["evaluation_status"], "not_run")
        self.assertIsNone(metadata["model"])
        self.assertIsNone(metadata["metrics"])
        self.assertEqual(len(corpus["items"]), 24)
        self.assertEqual(len({case["case_id"] for case in corpus["items"]}), 24)
        tags = set()
        for case in corpus["items"]:
            tags.update(case["tags"])
            reference = case["reference"]
            self.assertTrue(reference["uncertainties"])
            self.assertTrue(reference["follow_up_questions"])
            self.assertTrue(reference["do_not_infer"])
            for fact in reference["facts"]:
                self.assertIn(fact["evidence"], case["raw_text"])
        self.assertTrue({"negation", "invalid_date", "multiple_factors", "unit_ambiguity", "unknown_entity"}.issubset(tags))


if __name__ == "__main__":
    unittest.main()
