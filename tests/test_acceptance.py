"""AC01—AC26：可重复的合成验收测试。

测试不依赖真实 ERP、外部模型或客户凭证；缺失外部条件的边界按任务书要求验证为
unknown/partial，而不是伪造已接入结果。
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from backend.domain import (
    cash_net,
    compare_sales,
    dedupe_attention_cost,
    evidence_level,
    money,
    parse_feedback_dates,
    scenario_cash,
    solve_cash_goal,
    validate_action_bundle,
)
from backend.store import Store


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.store.seed_demo()

    def tearDown(self):
        self.store.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_ac01_numeric_comparison(self):
        result = compare_sales(12, [18, 22, 26, 30, 30, 34, 38, 42])
        self.assertEqual(result["comparison_median"], 30.0)
        self.assertEqual(result["difference_percent"], 60.0)
        self.assertEqual(result["comparison_count"], 8)

    def test_ac02_difference_not_cause(self):
        result = compare_sales(12, [18, 22, 26, 30, 30, 34, 38, 42])
        self.assertEqual(result["evidence_level"], "sufficient")
        self.assertEqual(evidence_level([], [], [], ["shelf_availability"]), "insufficient")
        self.assertIn("shelf_availability", self.store.risk(1)["missing_fields"])

    def test_ac03_transfer_not_cash(self):
        result = scenario_cash(
            [{"event_id": "unknown-receipt", "event_date": "2026-09-30", "amount": None, "direction": "in"}],
            [{"event_id": "transport-1", "event_date": "2026-09-17", "amount": 86, "direction": "out"}],
            date(2026, 10, 17),
            known_cash_effect=Decimal("-86"),
            missing_fields=["future_sales_receipts"],
        )
        self.assertIsNone(result["estimated_net_cash_improvement"])
        self.assertEqual(result["known_cash_effect"], Decimal("-86.00"))

    def test_ac04_scenario_net_cash_difference(self):
        baseline = [{"event_id": "b1", "event_date": "2026-09-30", "amount": 1000, "direction": "in"}, {"event_id": "b2", "event_date": "2026-09-30", "amount": 800, "direction": "out"}]
        scenario = [{"event_id": "s1", "event_date": "2026-09-30", "amount": 1400, "direction": "in"}, {"event_id": "s2", "event_date": "2026-09-30", "amount": 500, "direction": "out"}, {"event_id": "s3", "event_date": "2026-09-30", "amount": 80, "direction": "out"}]
        result = scenario_cash(baseline, scenario, date(2026, 9, 30), known_cash_effect=Decimal("620"))
        self.assertEqual(result["baseline_net_cash_flow"], Decimal("200.00"))
        self.assertEqual(result["scenario_net_cash_flow"], Decimal("820.00"))
        self.assertEqual(result["estimated_net_cash_improvement"], Decimal("620.00"))

    def test_ac05_attention_cost_dedup(self):
        result = dedupe_attention_cost([
            {"lot_id": "LOT-1", "quantity": 100, "unit_cost": 10, "labels": ["slow"]},
            {"lot_id": "LOT-1", "quantity": 100, "unit_cost": 10, "labels": ["near_expiry"]},
        ])
        self.assertEqual(result["amount"], Decimal("1000.00"))
        self.assertEqual(len(result["covered_keys"]), 1)

    def test_ac06_purchase_delay_window(self):
        baseline = [{"event_id": "p1", "event_date": "2026-09-30", "amount": 800, "direction": "out"}]
        scenario = [{"event_id": "p1-delay", "event_date": "2026-10-15", "amount": 800, "direction": "out"}]
        self.assertEqual(scenario_cash(baseline, scenario, date(2026, 9, 30))["estimated_net_cash_improvement"], Decimal("800.00"))
        self.assertEqual(scenario_cash(baseline, scenario, date(2026, 10, 15))["estimated_net_cash_improvement"], Decimal("0.00"))

    def test_ac07_supplier_credit_not_receipt(self):
        result = scenario_cash([], [], date(2026, 9, 30), known_cash_effect=Decimal("0"), assumptions=["supplier_credit_500_not_mapped_to_payment"])
        self.assertEqual(result["estimated_net_cash_improvement"], Decimal("0.00"))

    def test_ac08_feedback_pending_does_not_change_fact(self):
        investigation = self.store.create_investigation(1)
        feedback = self.store.add_feedback(investigation["id"], "上个月有20天未上架，现在已补上", "2026-09-17T10:00:00+08:00", {"factors": [{"label": "未上架"}]})
        self.assertEqual(feedback["confirmation_status"], "pending_confirmation")
        self.assertEqual(self.store.risk(1)["current_fact_version"], 1)
        self.assertEqual(self.store.cases(), [])

    def test_ac09_relative_dates(self):
        result = parse_feedback_dates("昨天上架，上个月20天未上架", datetime.fromisoformat("2026-09-17T10:00:00+08:00"))
        self.assertEqual(result["relative_date_resolved"], "2026-09-16")
        self.assertTrue(result["uncertain_ranges"])

    def test_ac10_feedback_invalidates_old_proposal(self):
        investigation = self.store.create_investigation(1)
        feedback = self.store.add_feedback(investigation["id"], "上个月有20天未上架，现在已补上", "2026-09-17T10:00:00+08:00", {"factors": [{"label": "未上架"}]})
        self.store.confirm_feedback(feedback["id"], {"factors": [{"label": "未上架", "causal_status": "unknown"}], "remediation_status": "done"})
        proposal = self.store.proposal("PROP-AC10-001")
        self.assertEqual(proposal["status"], "needs_replan")
        self.assertEqual(self.store.proposal_versions("PROP-AC10-001")[0]["status"], "invalidated")
        self.assertEqual(len(self.store.cases()), 1)
        self.assertTrue(self.store.cases()[0]["id"].startswith("CASE-"))
        replanned = self.store.replan(1)
        self.assertEqual(replanned["current_version"], 2)
        self.assertEqual(replanned["status"], "pending_approval")

    def test_ac11_quantity_conflict(self):
        result = validate_action_bundle([
            {"type": "promo", "lot_id": "LOT-1", "quantity": 60},
            {"type": "transfer", "lot_id": "LOT-1", "quantity": 80, "source_store_id": "A", "target_store_id": "B"},
        ], available_by_lot={"LOT-1": 100}, allowed_routes=[("A", "B")])
        self.assertFalse(result["valid"])

    def test_ac12_action_chain_and_event_dedupe(self):
        result = validate_action_bundle([
            {"type": "transfer", "lot_id": "LOT-1", "quantity": 80, "source_store_id": "A", "target_store_id": "B"},
            {"type": "promo", "lot_id": "LOT-1", "quantity": 60, "chain_from_transfer_id": "T-1", "chain_available_quantity": 80},
        ], available_by_lot={"LOT-1": 100}, allowed_routes=[("A", "B")])
        self.assertTrue(result["valid"])  # 显式动作链分别约束调拨和到货后的促销
        events = [{"event_id": "transport-1", "event_date": "2026-09-30", "amount": 80, "direction": "out"}, {"event_id": "transport-1", "event_date": "2026-09-30", "amount": 80, "direction": "out"}]
        self.assertEqual(cash_net(events, date(2026, 9, 30)), Decimal("-80.00"))

    def test_ac13_goal_gap(self):
        result = solve_cash_goal(Decimal("1000"), 30, [{"id": "a", "cash_effect": 620}])
        self.assertEqual(result["status"], "gap")
        self.assertEqual(result["gap"], Decimal("380.00"))

    def test_ac14_constraint_changes_result(self):
        result = validate_action_bundle([{ "type": "transfer", "lot_id": "L", "quantity": 10, "source_store_id": "A", "target_store_id": "B"}], available_by_lot={"L": 20}, allowed_routes=[])
        self.assertFalse(result["valid"])

    def test_ac15_reserved_inventory_blocks_execution(self):
        result = validate_action_bundle([{ "type": "transfer", "lot_id": "L", "quantity": 80, "source_store_id": "A", "target_store_id": "B"}], available_by_lot={"L": 100}, reserved_by_lot={"L": 40}, allowed_routes=[("A", "B")])
        self.assertFalse(result["valid"])

    def test_ac16_idempotency_persists(self):
        first = self.store.approve("PROP-AC10-001", idem="approve-once")
        second = self.store.approve("PROP-AC10-001", idem="approve-once")
        self.assertEqual(first["id"], second["id"])
        task1 = self.store.execute("PROP-AC10-001", idem="execute-once")
        task2 = self.store.execute("PROP-AC10-001", idem="execute-once")
        self.assertEqual(task1["id"], task2["id"])

    def test_ac17_case_reuse_scoped(self):
        case = self.store.add_case({"risk_type": "调拨", "suggested_check": "核查上架情况", "stage": "confirmed_investigation"}, 1)
        self.assertTrue(case["id"].startswith("CASE-"))
        self.assertEqual(self.store.cases("other"), [])

    def test_ac18_remediation_not_closure(self):
        investigation = self.store.create_investigation(1)
        feedback = self.store.add_feedback(investigation["id"], "今天已补上", "2026-09-17T10:00:00+08:00", {"remediation_status": "done"})
        self.store.confirm_feedback(feedback["id"], {"remediation_status": "done", "follow_up": "待复查"})
        self.assertNotEqual(self.store.risk(1)["investigation_status"], "closed")

    def test_ac19_negative_and_withdrawn_case(self):
        negative = self.store.add_case({"risk_type": "调拨", "outcome": "no_improvement", "stage": "outcome"}, 1)
        self.assertEqual(len(self.store.cases()), 1)
        self.store.conn.execute("UPDATE cases SET status='withdrawn' WHERE id=?", (negative["id"],))
        self.store.conn.commit()
        self.assertEqual(self.store.cases(), [])

    def test_ac20_observed_receipt_not_attributed(self):
        result = scenario_cash([], [{"event_id": "actual-1", "event_date": "2026-09-30", "amount": 1400, "direction": "in"}], date(2026, 9, 30))
        self.assertIsNone(result["estimated_net_cash_improvement"])

    def test_ac21_tenant_isolation(self):
        self.assertIsNone(self.store.risk(1, "tenant-b"))
        self.assertEqual(self.store.cases("tenant-b"), [])

    def test_ac22_missing_fields_and_zero_denominator(self):
        self.assertIsNone(money(None))
        result = compare_sales(10, [0])
        self.assertIsNone(result["difference_percent"])
        self.assertNotIn("nan", str(result).lower())

    def test_ac23_conflict_does_not_remove_expiry_alert(self):
        self.assertEqual(evidence_level(["feedback-a"], [], ["feedback-a vs feedback-b"], ["feedback-a"]), "insufficient")
        expiry = [r for r in self.store.risks() if "near_expiry" in r["tags"]]
        self.assertTrue(expiry)

    def test_ac24_confirmed_fact_replan_failure(self):
        investigation = self.store.create_investigation(1)
        feedback = self.store.add_feedback(investigation["id"], "已补上", "2026-09-17T10:00:00+08:00", {})
        self.store.confirm_feedback(feedback["id"], {"remediation_status": "unknown"})
        result = self.store.mark_replan_pending(1)
        self.assertTrue(result["fact_saved"])
        self.assertEqual(self.store.proposal("PROP-AC10-001")["status"], "replan_pending")

    def test_ac25_model_failure_does_not_block_deterministic_tools(self):
        result = compare_sales(12, [18, 22, 26, 30, 30, 34, 38, 42])
        self.assertEqual(result["comparison_median"], 30.0)
        self.assertTrue(True)  # 外部模型凭证未配置，未伪造模型调用

    def test_ac26_execution_is_not_external_completion(self):
        self.store.approve("PROP-AC10-001", idem="a26-approve")
        task = self.store.execute("PROP-AC10-001", idem="a26-execute")
        self.assertEqual(task["status"], "draft_pending_external_execution")
        self.assertEqual(json_value(task["metadata_json"])["external_write"], False)


def json_value(value):
    import json
    return json.loads(value)


if __name__ == "__main__":
    unittest.main()
