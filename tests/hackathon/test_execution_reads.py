"""Saved-version reads, strict scope and nonduplicating cash projections."""
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch
import unittest

from backend.errors import BusinessConflict
from backend.hackathon_execution import reads
from tests.hackathon.test_execution_service import ExecutionTestCase


class ExecutionReadTests(ExecutionTestCase):
    def test_unknown_account_balance_does_not_hide_execution_reads(self):
        self.approve()
        facts = self.facts.query({"context": self.context})
        facts["reference_data"]["tables"]["accounts"][0]["available_balance"] = None
        with patch.object(self.facts, "query", return_value=facts):
            result = self.accounting()
        self.assertIsNone(result["account_balance_cny"])
        self.assertEqual(result["tasks"][0]["task_id"], self.task_id)

    def test_business_inputs_survive_save_confirm_and_overview_refresh(self):
        self.context = self.facts.import_scenario("test", "S01")["context"]
        facts = self.facts.query({"context": self.context})
        target = facts["reference_data"]["target"]
        risk_key = "S01:" + ":".join(target[key] for key in ("store_id", "sku_id", "lot_id")) + ":slow_moving"
        business = {"transfer": {"origin_store_id": "ST-001", "target_store_id": "ST-002", "sku_id": "SKU-001",
                                  "lot_id": "LOT-001-001", "quantity": 80, "base_unit": "盒", "route_fee_cny": 24}}
        request = {"context": self.context, "risk_keys": [risk_key], "business_inputs": business, "inputs": {"sales_settlement_days": 0}}
        comparison = self.calculations.compare(facts, request)
        selected = next(row for row in comparison["candidates"] if row["action_type"] == "transfer" and row["target_store_id"] == "ST-002")
        self.saved = self.execution.save_proposal(self.command(**request, expected_current_proposal_version=0,
            comparison_id=comparison["comparison_id"], candidate_id=selected["candidate_id"]))
        stored = self.execution.list_proposals({"context": self.context})["proposals"][0]
        self.assertEqual(stored["comparison_request"]["business_inputs"], business)
        self.assertEqual(self.execution.get_overview({"context": self.context})["overview"]["pending_approvals"]["amount"], 6400)
        confirmed = self.execution.confirm_and_schedule(self.confirmation(self.saved))
        self.context = confirmed["context"]
        self.store.close()
        from backend.store import Store
        self.store = Store(self.path)
        self.bind()
        overview = self.execution.get_overview({"context": self.context})
        self.assertEqual(overview["overview"]["account"]["balance"], 858900)
        self.assertEqual(overview["overview"]["pending_approvals"]["count"], 0)
        self.assertEqual(overview["overview"]["task_links"][0]["task_id"], confirmed["tasks"][0]["task_id"])

    def test_pending_list_reads_saved_candidate_without_recalculating(self):
        saved = self.save()
        with patch.object(self.calculations, "compare", side_effect=AssertionError("Read must not recalculate")):
            result = self.execution.list_proposals({"context": self.context, "status": "pending_approval"})
        self.assertEqual(len(result["proposals"]), 1)
        proposal = result["proposals"][0]
        self.assertEqual(proposal["proposal_id"], saved["proposal_id"])
        self.assertEqual(proposal["inventory_cost_cny"], 6400)
        self.assertEqual(proposal["risk_keys"], [saved["risk_key"]])
        self.assertEqual(proposal["action_type"], "transfer")
        self.assertFalse(proposal["requires_recalculation"])
        for field in ("title", "context", "created_at", "updated_at", "missing_fields", "action_lines"):
            self.assertIn(field, proposal)
        approved = self.execution.confirm_and_schedule(self.confirmation(saved))
        self.context = approved["context"]
        self.assertEqual(self.execution.list_proposals({"context": self.context, "status": "pending_approval"})["proposals"], [])

    def test_revisions_have_current_list_and_immutable_case_history(self):
        saved = self.save()
        original = self.execution.list_proposals({"context": self.context})["proposals"][0]
        request = self.command(**original["comparison_request"], proposal_id=saved["proposal_id"],
            comparison_id=original["comparison_id"], candidate_id=original["candidate_id"], expected_current_proposal_version=1)
        updated = self.execution.save_proposal(request)
        self.assertEqual(updated["proposal_version"], 2)
        case = self.execution.get_case({"context": self.context, "case_id": saved["proposal_id"]})["case"]
        self.assertEqual([v["proposal_version"] for v in case["versions"]], [1, 2])
        self.assertEqual(case["versions"][0]["invalid_reason"], "superseded")
        self.assertIsNone(case["accounting"])
        self.assertEqual(len(case["events"]), 2)
        with self.assertRaises(BusinessConflict):
            self.execution.list_proposals({"context": self.context, "proposal_id": saved["proposal_id"], "proposal_version": 1})

    def test_read_scope_and_versions_are_validated(self):
        self.approve()
        for context in ({**self.context, "tenant_id": "other"}, {**self.context, "branch_id": "other"},
                        {**self.context, "snapshot_id": "other"}, {**self.context, "fact_version": self.context["fact_version"] + 1}):
            with self.subTest(context=context), self.assertRaises((ValueError, BusinessConflict)):
                self.execution.list_proposals({"context": context})
        self.assertEqual(self.execution.get_task({"context": self.context, "task_id": self.task_id})["task"]["task_id"], self.task_id)
        with self.assertRaises(BusinessConflict):
            self.execution.get_task({"context": self.context, "task_id": self.task_id, "task_version": 999})
        with self.assertRaises(ValueError):
            self.execution.get_task({"context": self.context, "task_id": self.task_id, "proposal_id": "unrelated"})
        with self.assertRaises(ValueError):
            self.execution.get_case({"context": self.context, "case_id": self.saved["proposal_id"], "proposal_id": "other"})

    def test_proposal_accounting_and_case_exclude_other_batch_cash_and_events(self):
        self.approve()
        self.replay()
        global_result = self.accounting()
        scoped = self.execution.get_accounting({"context": self.context, "proposal_id": self.saved["proposal_id"]})
        self.assertEqual(global_result["cash_in"], 7400)
        self.assertEqual(scoped["cash_in"], 6400)
        self.assertEqual(scoped["cash_out"], 24)
        self.assertNotIn("account_balance_cny", scoped)
        self.assertNotIn("inventory", scoped)
        for event in scoped["timeline"]:
            if event["kind"] != "cash":
                self.assertEqual(event["record"].get("task_id"), self.task_id)
        self.assertLess(len(scoped["timeline"]), len(global_result["timeline"]))
        cash = [event["record"] for event in scoped["timeline"] if event["kind"] == "cash"]
        self.assertEqual(sum(row["amount"] for row in cash if row["direction"] == "in"), 6400)
        case = self.execution.get_case({"context": self.context, "case_id": self.saved["proposal_id"]})["case"]
        self.assertEqual(case["accounting"]["cash_in"], 6400)
        self.assertEqual(case["events"][0]["kind"], "proposal_saved")
        self.assertEqual({event["kind"] for event in case["events"]} & {"proposal_saved", "proposal_confirmed"}, {"proposal_saved", "proposal_confirmed"})

    def test_task_detail_channels_and_events_are_selected_together(self):
        approved = self.approve(inputs={"sales_settlement_days": 0, "combination": [
            {"type": "transfer", "target_store_id": "ST-002", "quantity": 40},
            {"type": "transfer", "target_store_id": "ST-004", "quantity": 10}]}, strategy="combination")
        for task in approved["tasks"]:
            self.execution.record_channel_action(self.command(task_id=task["task_id"], channel="feishu", status="draft_saved",
                proposal_id=self.saved["proposal_id"], proposal_version=1, content_snapshot={"text": task["task_id"]}, target_ref="P-002"))
        detail = self.execution.get_task({"context": self.context, "task_id": self.task_id})
        self.assertEqual(len(detail["channels"]), 1)
        self.assertEqual(detail["channels"][0]["task_id"], self.task_id)
        case = self.execution.get_case({"context": self.context, "case_id": self.saved["proposal_id"]})["case"]
        self.assertEqual(len(case["channels"]), 2)
        self.assertEqual(len([event for event in case["events"] if event["kind"] == "channel_action"]), 2)

    def test_overview_uses_data_service_and_saved_proposal_cost(self):
        self.save()
        authority = {"contract_version": "hackathon.v1", "context": deepcopy(self.context), "metadata": {"source": "authoritative"},
            "overview": {"account": {"balance": None}, "inventory": {"cost": 123, "risk_cost": None},
                "purchase_commitments": {"amount": 456}, "stores": [{"store_id": "ST-001", "missing_fields": ["risk_cost"]}]}}
        with patch.object(self.facts, "get_overview", create=True, return_value=authority) as overview:
            result = self.execution.get_overview({"context": self.context})
        self.assertIs(overview.call_args.kwargs["tx"], self.store.conn)
        self.assertEqual(result["overview"]["account"], authority["overview"]["account"])
        self.assertEqual(result["overview"]["inventory"], authority["overview"]["inventory"])
        self.assertEqual(result["overview"]["purchase_commitments"], authority["overview"]["purchase_commitments"])
        self.assertEqual(result["overview"]["pending_approvals"], {"count": 1, "amount": 6400, "known_amount": 6400, "missing_count": 0})
        self.assertEqual(result["overview"]["stores"][0]["work_item_id"], self.saved["proposal_id"])
        self.assertEqual(result["metadata"], authority["metadata"])


class CashReadProjectionTests(unittest.TestCase):
    def test_shared_cash_event_is_limited_to_selected_allocations(self):
        state = {"cash_events": [{"cash_event_id": "shared", "amount": 1000, "direction": "in", "task_id": None}],
                 "cash_allocations": [{"allocation_id": "a", "cash_event_id": "shared", "task_id": "A", "allocated_amount": 100},
                                      {"allocation_id": "b", "cash_event_id": "shared", "task_id": "B", "allocated_amount": 900}]}
        result = reads.scoped_cash(state, {"A"})["shared"]
        self.assertEqual(result["amount"], Decimal(100))
        self.assertEqual(result["allocation_ids"], ["a"])
        self.assertEqual(result["amount_scope"], "allocated_to_selected_tasks")

    def test_pending_unknown_cost_is_not_zero_or_expected_cash(self):
        self.assertEqual(reads.pending_summary([{"inventory_cost_cny": None}, {"inventory_cost_cny": Decimal(200)}]),
                         {"count": 2, "amount": None, "known_amount": 200, "missing_count": 1})
        self.assertEqual(reads.pending_summary([]), {"count": 0, "amount": 0, "known_amount": 0, "missing_count": 0})
