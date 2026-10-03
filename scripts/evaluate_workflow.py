#!/usr/bin/env python3
"""Strict descriptive summaries for manually recorded, paired workflow observations."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "sample-data/evaluation/workflow-schema.json"
ARMS = ("human_gpt", "system")
STATUSES = ("not_run", "in_progress", "completed", "failed", "abandoned")
TERMINAL = {"completed", "failed", "abandoned"}
COST_FIELDS = ("model_cost_cny", "labor_cost_cny", "other_cost_cny")
MEASUREMENTS = ("elapsed_seconds", "human_seconds", "human_edits", *COST_FIELDS)


class EvaluationInputError(ValueError):
    pass


def _value(raw, field, rule, line):
    if raw is None:
        raise EvaluationInputError(f"row {line}: missing cell for {field}")
    value = raw.strip()
    kinds = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
    if "number" in kinds or "integer" in kinds:
        if not value and "null" in kinds:
            return None
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
            raise EvaluationInputError(f"row {line}: {field} must be a nonnegative decimal or an empty unmeasured cell")
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise EvaluationInputError(f"row {line}: invalid {field}") from error
        if not parsed.is_finite() or parsed < rule.get("minimum", parsed) or parsed > rule.get("maximum", parsed):
            raise EvaluationInputError(f"row {line}: {field} is outside the allowed range")
        if "integer" in kinds and parsed != parsed.to_integral_value():
            raise EvaluationInputError(f"row {line}: {field} must be an integer")
        if "multipleOf" in rule and parsed % Decimal(str(rule["multipleOf"])) != 0:
            raise EvaluationInputError(f"row {line}: {field} uses CNY with at most six decimal places")
        return int(parsed) if "integer" in kinds else parsed
    if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", float("inf")):
        raise EvaluationInputError(f"row {line}: invalid length for {field}")
    if "enum" in rule and value not in rule["enum"]:
        raise EvaluationInputError(f"row {line}: unsupported {field}: {value!r}")
    return value


def load_observations(path):
    rules = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["items"]["properties"]
    observations, seen = [], set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)) or set(headers) != set(rules):
            raise EvaluationInputError("CSV headers must match workflow-schema.json exactly, with no duplicate or extra columns")
        try:
            for raw in reader:
                line = reader.line_num
                if None in raw:
                    raise EvaluationInputError(f"row {line}: extra cells")
                row = {field: _value(raw.get(field), field, rule, line) for field, rule in rules.items()}
                key = (row["case_id"], row["arm"])
                if key in seen:
                    raise EvaluationInputError(f"row {line}: duplicate case_id/arm {key}; aggregate retries in one row")
                seen.add(key)
                measured = any(row[field] is not None for field in MEASUREMENTS)
                if row["status"] == "not_run":
                    if measured or row["review_outcome"] != "not_assessed" or row["execution_status"] != "not_started":
                        raise EvaluationInputError(f"row {line}: not_run cannot contain measurements, a review result, or execution")
                if (measured or row["review_outcome"] != "not_assessed") and not row["evidence_ref"]:
                    raise EvaluationInputError(f"row {line}: measurements and assessments require evidence_ref")
                if row["review_outcome"] == "accepted" and row["status"] != "completed":
                    raise EvaluationInputError(f"row {line}: accepted requires a completed workflow")
                if row["execution_status"] == "performed" and not row["execution_evidence_ref"]:
                    raise EvaluationInputError(f"row {line}: performed requires actual execution_evidence_ref")
                observations.append(row)
        except csv.Error as error:
            raise EvaluationInputError(f"invalid CSV near row {reader.line_num}: {error}") from error
    return observations


def _number(value):
    return None if value is None else float(value)


def distribution(values):
    values = sorted(Decimal(str(value)) for value in values if value is not None)
    if not values:
        return {"n": 0, "min": None, "median": None, "p90": None, "max": None, "total": None}
    def percentile(fraction):
        position = Decimal(len(values) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    return {"n": len(values), "min": _number(values[0]), "median": _number(percentile(Decimal("0.5"))),
            "p90": _number(percentile(Decimal("0.9"))), "max": _number(values[-1]),
            "total": _number(sum(values))}


def _money(value):
    return None if value is None else format(value, ".6f")


def total_cost(row):
    values = [row[field] for field in COST_FIELDS]
    return sum(values, Decimal(0)) if all(value is not None for value in values) else None


def summarize(observations):
    cases = {}
    for row in observations:
        cases.setdefault(row["case_id"], {})[row["arm"]] = row
    pairs = [case for case in cases.values() if all(arm in case for arm in ARMS)]
    completed = [pair for pair in pairs if all(pair[arm]["status"] == "completed" for arm in ARMS)]
    accepted = [pair for pair in completed if all(pair[arm]["review_outcome"] == "accepted" for arm in ARMS)]
    cost_pairs = [pair for pair in pairs if all(pair[arm]["status"] in TERMINAL and total_cost(pair[arm]) is not None for arm in ARMS)]
    arm_results = {}
    for arm in ARMS:
        rows = [row for row in observations if row["arm"] == arm]
        observed = [row for row in rows if row["status"] != "not_run"]
        costs = [total_cost(row) for row in observed if row["status"] in TERMINAL]
        complete_costs = [cost for cost in costs if cost is not None]
        arm_results[arm] = {
            "rows": len(rows), "status_counts": {key: sum(row["status"] == key for row in rows) for key in STATUSES},
            "review_counts": dict(Counter(row["review_outcome"] for row in rows)),
            "execution_counts": dict(Counter(row["execution_status"] for row in rows)),
            "missing_measurements_in_observed_rows": {field: sum(row[field] is None for row in observed) for field in MEASUREMENTS},
            "elapsed_seconds_all_observed": distribution(row["elapsed_seconds"] for row in observed),
            "human_seconds_all_observed": distribution(row["human_seconds"] for row in observed),
            "human_edits_all_observed": distribution(row["human_edits"] for row in observed),
            "terminal_rows_with_complete_cost": len(complete_costs),
            "terminal_complete_cost_total_cny": _money(sum(complete_costs)) if complete_costs else None,
            "known_cost_components": {
                field: {"observed_rows": sum(row[field] is not None for row in observed),
                        "total_cny": _money(sum((row[field] for row in observed if row[field] is not None), Decimal(0)))
                        if any(row[field] is not None for row in observed) else None}
                for field in COST_FIELDS
            },
        }
    def paired_metrics(selected):
        output = {}
        for field in ("elapsed_seconds", "human_seconds", "human_edits"):
            measured = [pair for pair in selected if all(pair[arm][field] is not None for arm in ARMS)]
            output[field] = {
                "paired_cases": len(measured),
                **{arm: distribution(pair[arm][field] for pair in measured) for arm in ARMS},
                "system_minus_human_gpt": distribution(pair["system"][field] - pair["human_gpt"][field] for pair in measured),
            }
        return output
    return {
        "schema_version": "workflow-summary-v1",
        "status": "descriptive_observations" if any(row["status"] != "not_run" for row in observations) else "no_observations",
        "case_count": len(cases), "row_count": len(observations),
        "registered_pairs": len(pairs), "completed_pairs": len(completed), "accepted_pairs": len(accepted),
        "timed_completed_pairs": sum(all(pair[arm]["elapsed_seconds"] is not None for arm in ARMS) for pair in completed),
        "missing_arm_rows": [{"case_id": case_id, "missing_arm": arm} for case_id, pair in sorted(cases.items()) for arm in ARMS if arm not in pair],
        "incomplete_cases": [{"case_id": case_id, "statuses": {arm: pair[arm]["status"] if arm in pair else "missing_row" for arm in ARMS}}
                             for case_id, pair in sorted(cases.items()) if not all(arm in pair and pair[arm]["status"] == "completed" for arm in ARMS)],
        "arms": arm_results,
        "completed_pair_metrics": paired_metrics(completed),
        "accepted_pair_metrics": paired_metrics(accepted),
        "terminal_cost_comparison": {
            "paired_cases": len(cost_pairs),
            **{arm: _money(sum((total_cost(pair[arm]) for pair in cost_pairs), Decimal(0))) if cost_pairs else None for arm in ARMS},
            "includes_failed_and_abandoned": True,
        },
        "interpretation": [
            "Descriptive only: no significance, causal benefit, ROI, or annual savings are inferred.",
            "Completed does not mean accepted; report review outcomes and both denominators.",
            "Time comparisons use the same completed cases; costs include all terminal paired outcomes, including failures.",
            "Blank numeric cells remain unknown. A known partial component sum is not the full cost.",
            "Evidence references are recorded but not verified by this script.",
            "Currency totals are CNY decimal strings. Median/p90 use linear interpolation of observed values.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Optional JSON output; omitted means stdout")
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() == args.input.resolve():
            raise EvaluationInputError("Output must not overwrite the observation CSV")
        report = summarize(load_observations(args.input))
        content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
        else:
            print(content, end="")
    except (OSError, EvaluationInputError, UnicodeError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
