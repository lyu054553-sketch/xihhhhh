"""Real isolated workbooks, public DTOs and the shared SQLite transaction."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from backend.errors import BusinessConflict
from backend.store import Store
from backend.hackathon_data import RetailFactService, migrate as migrate_data
from backend.hackathon_data.loader import load_replay
from backend.hackathon_calculations import CalculationService
from backend.hackathon_execution import ExecutionService, migrate


class ExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="retail-execution-")
        self.path = str(Path(self.directory.name) / "case.sqlite")
        self.store = Store(self.path)
        with self.store.transaction() as tx:
            migrate_data(tx)
            migrate(tx)
        self.bind()
        self.sequence = 0

    def bind(self):
        self.facts = RetailFactService(self.store)
        self.calculations = CalculationService()
        self.execution = ExecutionService(self.store, self.facts, self.calculations,
                                          replay_reader=load_replay, clock_advancer=self.facts.advance_clock)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def command(self, **fields):
        self.sequence += 1
        for item in fields.get("events", []):
            if item["record"].get("task_id"):
                item["record"].update(proposal_id=self.saved["proposal_id"], proposal_version=self.saved["proposal_version"])
        return {"context": self.context, "actor_id": "P-001", "idempotency_key": f"command-{self.sequence}", **fields}

    def confirmation(self, saved):
        return self.command(proposal_id=saved["proposal_id"], expected_proposal_version=saved["proposal_version"],
            expected_fact_version=self.context["fact_version"], expected_snapshot_id=self.context["snapshot_id"], candidate_id=saved["candidate_id"],
            task_assignments=[{"action_line_id": line["action_line_id"], "assignee_id": "P-002", "due_at": "2026-10-25T17:00:00+08:00"} for line in saved["action_lines"]])

    def save(self, scenario="S01", branch=None, inputs=None, strategy="transfer:ST-002"):
        self.context = self.facts.import_scenario("test", scenario, branch)["context"]
        self.inputs = {"quantity": 80, "sales_settlement_days": 0} if inputs is None else inputs
        query = {"context": self.context}
        facts = self.facts.query(query)
        target = facts["reference_data"]["target"]
        risks = self.facts.assess_risks(query)["items"]
        risk = next(r for r in risks if all(r[k] == target[k] for k in ("store_id", "sku_id", "lot_id")))
        comparison_request = {"context": self.context, "inputs": self.inputs, "risk_keys": [risk["risk_key"]]}
        comparison = self.calculations.compare(facts, comparison_request)
        candidates = comparison["candidates"] + comparison.get("candidate_groups", [])
        candidate = next(c for c in candidates if c["calculation"]["execution_plan"]["strategy_id"] == strategy)
        self.saved = self.execution.save_proposal(self.command(**comparison_request, expected_current_proposal_version=0,
            comparison_id=comparison["comparison_id"], candidate_id=candidate.get("candidate_id", candidate.get("group_id"))))
        return self.saved

    def approve(self, scenario="S01", branch=None, inputs=None, strategy="transfer:ST-002"):
        saved = self.save(scenario, branch, inputs, strategy)
        self.confirm_request = self.confirmation(saved)
        result = self.execution.confirm_and_schedule(self.confirm_request)
        self.context = result["context"]
        self.task_id = result["tasks"][0]["task_id"]
        return result

    def replay(self, clock="2026-10-25T23:59:00+08:00"):
        result = self.execution.advance_replay(self.command(as_of=clock, expected_fact_version=self.context["fact_version"],
            proposal_id=self.saved["proposal_id"], proposal_version=self.saved["proposal_version"]))
        self.context = result["context"]
        return result

    def accounting(self):
        return self.execution.get_accounting({"context": self.context})

    def test_confirmation_is_one_atomic_shared_task_and_idempotent_after_reopen(self):
        first = self.approve()
        repeated = self.execution.confirm_and_schedule(self.confirm_request)
        self.assertTrue(repeated["idempotent_replay"])
        self.assertEqual(first["task_group_id"], repeated["task_group_id"])
        with self.store.transaction() as tx:
            self.assertEqual(tx.execute("SELECT COUNT(*) FROM approvals").fetchone()[0], 1)
            self.assertEqual(tx.execute("SELECT quantity FROM inventory_reservations").fetchone()[0], 80)
        self.store.close()
        self.store = Store(self.path)
        self.bind()
        self.assertEqual(len(self.accounting()["tasks"]), 1)

    def test_changed_idempotency_payload_fails(self):
        self.approve()
        with self.assertRaises(BusinessConflict):
            self.execution.confirm_and_schedule({**self.confirm_request, "actor_id": "P-003"})

    def test_parallel_confirmation_creates_only_one_task(self):
        saved = self.save()
        def attempt(index):
            request = {**self.confirmation(saved), "idempotency_key": f"confirm-{index}"}
            try:
                return self.execution.confirm_and_schedule(request)
            except BusinessConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [1, 2]))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_s01_batch_cash_and_account_cash_remain_distinct(self):
        self.approve()
        result = self.replay()["accounting"]
        case = result["tasks"][0]["result"]
        self.assertEqual(case["sales_cash_received"], 6400)
        self.assertEqual(case["sold_cost"], 5120)
        self.assertEqual(case["execution_fees_paid"], 24)
        self.assertEqual(case["realized_gross_profit_less_paid_fees"], 1256)
        self.assertEqual(result["cash_in"], 7400)
        self.assertEqual(result["account_balance_cny"], 866276)
        self.assertEqual(result["tasks"][0]["accounting_status"], "completed")
        case_dto = self.execution.get_accounting({"context": self.context, "task_id": self.task_id})
        self.assertEqual(case_dto["actual_cash_in_cny"], 6400)
        self.assertEqual(case_dto["ending_qty"], 16)

    def test_repeated_replay_is_idempotent(self):
        self.approve()
        first = self.replay()
        second = self.replay()
        self.assertEqual(second["applied_event_ids"], [])
        self.assertEqual(first["accounting"], second["accounting"])

    def test_stepwise_replay_and_refresh_equal_one_batch(self):
        self.approve()
        self.replay("2026-10-04T10:00:00+08:00")
        self.store.close()
        self.store = Store(self.path)
        self.bind()
        self.assertEqual(self.accounting()["tasks"][0]["status"], "in_transit")
        self.replay("2026-10-10T23:59:00+08:00")
        result = self.replay()["accounting"]
        self.assertEqual(result["tasks"][0]["result"]["sales_cash_received"], 6400)
        self.assertEqual(result["account_balance_cny"], 866276)

    def test_s09_partial_quantities_and_cash_remain_open(self):
        self.approve("S09")
        task = self.replay()["accounting"]["tasks"][0]
        self.assertEqual(task["execution_status"], "in_progress")
        self.assertEqual(task["accounting_status"], "in_progress")
        self.assertEqual(task["result"]["remaining_execution_qty"], 20)
        self.assertEqual(task["result"]["outstanding_cash"], 1000)

    def test_changed_quantity_cannot_inherit_fixed_replay(self):
        self.approve(inputs={"quantity": 40, "sales_settlement_days": 0})
        before = self.accounting()
        with self.assertRaises(BusinessConflict):
            self.replay()
        self.assertEqual(before, self.accounting())

    def test_changed_freight_rolls_back_clock_stock_and_cash(self):
        self.approve(inputs={"quantity": 80, "sales_settlement_days": 0, "transport_fee": 40})
        before = self.accounting()
        with self.assertRaises(BusinessConflict):
            self.replay()
        self.assertEqual(before, self.accounting())

    def test_future_cash_is_unknown_before_replay(self):
        self.approve()
        result = self.replay("2026-10-03T12:00:00+08:00")["accounting"]
        self.assertIsNone(result["actual_cash_in_cny"])
        self.assertEqual(result["tasks"][0]["execution_status"], "pending")

    def test_s07_purchase_inbound_and_payment(self):
        self.approve("S07", inputs={}, strategy="purchase")
        early = self.replay("2026-10-06T23:59:00+08:00")["accounting"]
        self.assertEqual(early["tasks"][0]["execution_status"], "completed")
        self.assertNotEqual(early["tasks"][0]["accounting_status"], "completed")
        result = self.replay()["accounting"]
        stock = [r for r in result["inventory"] if r["store_id"] == "ST-004" and r["sku_id"] == "SKU-003"]
        self.assertEqual(sum(r["quantity"] for r in stock), 70)
        self.assertEqual(result["cash_out"], 2400)
        self.assertEqual(result["tasks"][0]["accounting_status"], "completed")

    def test_s06_two_stage_component_sales(self):
        self.approve("S06", inputs={"sales_settlement_days": 0}, strategy="promotion")
        result = self.replay()["accounting"]
        stocks = [r["quantity"] for r in result["inventory"] if r["store_id"] == "ST-004" and r["sku_id"] in ("SKU-004", "SKU-008") and r["stock_state"] == "on_hand"]
        self.assertEqual(stocks, [20, 20])
        self.assertEqual(result["cash_in"], 420)
        self.assertEqual(result["cash_out"], 20)

    def test_s05_refund_exchange_and_credit_are_separate(self):
        for mode in ("cash_refund", "exchange", "payable_credit"):
            terms = {"packaging_confirmed": True, "supplier_confirmed": True, "freight_fee": 30, "acceptance_date": "2026-10-05"}
            if mode == "exchange":
                terms.update(replacement_sku_id="SKU-006", replacement_lot_id="SCLOT-S05-REPLACEMENT", replacement_qty=100, replacement_unit_cost=9, cash_difference=0)
            if mode == "payable_credit":
                terms.update(payable_id="AP-S05-001", credit_apply_date="2026-10-16")
            with self.subTest(mode=mode):
                self.approve("S05", mode, inputs={"return_terms": terms}, strategy="return")
                result = self.replay()["accounting"]
                self.assertEqual(result["cash_in"], 900 if mode == "cash_refund" else 0)
                self.assertEqual(result["cash_out"], 1130 if mode == "payable_credit" else 30)
                if mode == "exchange":
                    self.assertEqual(next(r["quantity"] for r in result["inventory"] if r["lot_id"] == "SCLOT-S05-REPLACEMENT"), 100)
                if mode == "payable_credit":
                    self.assertEqual(next(p["outstanding_amount"] for p in result["payables"] if p["payable_id"] == "AP-S05-001"), 0)

    def test_local_channel_never_creates_business_receipts(self):
        self.approve()
        for channel in ("feishu", "wecom", "email"):
            for status in ("draft_saved", "sent", "accepted", "completed"):
                result = self.execution.record_channel_action(self.command(task_id=self.task_id, channel=channel,
                         status=status, content_snapshot={"text": "Confirmed action"}, target_ref="local-person",
                         proposal_id=self.saved["proposal_id"], proposal_version=self.saved["proposal_version"]))
                self.assertFalse(result["external_write"])
        result = self.accounting()
        self.assertEqual(result["cash_in"], 0)
        self.assertEqual(result["timeline"], [])
        self.assertEqual(result["tasks"][0]["execution_status"], "pending")

    def test_cancel_releases_remaining_reservation_and_preserves_followup(self):
        self.approve("S09")
        self.replay()
        result = self.execution.cancel_task(self.command(task_id=self.task_id, reason="Remaining stock needs a new plan"))
        self.context = result["context"]
        self.assertTrue(result["task"]["cancelled"])
        with self.store.transaction() as tx:
            self.assertEqual(tx.execute("SELECT COUNT(*) FROM inventory_reservations").fetchone()[0], 0)
        self.assertEqual(self.accounting()["tasks"][0]["result"]["outstanding_cash"], 1000)

    def test_combination_confirmation_is_atomic(self):
        self.approve(inputs={"sales_settlement_days": 0, "combination": [
            {"type": "transfer", "target_store_id": "ST-002", "quantity": 40},
            {"type": "transfer", "target_store_id": "ST-004", "quantity": 10}]}, strategy="combination")
        self.assertEqual(len(self.accounting()["tasks"]), 2)
        with self.store.transaction() as tx:
            self.assertEqual(tx.execute("SELECT SUM(quantity) FROM inventory_reservations").fetchone()[0], 50)

    def test_other_tenant_cannot_read_or_confirm_proposal(self):
        self.approve()
        with self.assertRaises((ValueError, BusinessConflict)):
            self.execution.get_accounting({"context": {**self.context, "tenant_id": "other"}})

    def test_fact_publication_failure_rolls_back_approval_and_reservation(self):
        saved = self.save()
        request = self.confirmation(saved)
        with patch.object(self.facts, "apply_business_events", side_effect=ValueError("Publication failed")):
            with self.assertRaises(ValueError):
                self.execution.confirm_and_schedule(request)
        with self.store.transaction() as tx:
            for table in ("approvals", "execution_tasks", "inventory_reservations"):
                self.assertEqual(tx.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)
        self.assertEqual(self.facts.get_context("test", "S01"), self.context)
        self.assertEqual(self.execution.confirm_and_schedule(request)["status"], "approved")

    def test_late_cash_allocation_error_rolls_back_entire_replay(self):
        self.approve()
        before = self.accounting()
        def invalid_reader(*args, **kwargs):
            replay = load_replay(*args, **kwargs)
            replay["tables"]["cash_allocations"][-1]["allocated_amount"] = 999999
            return replay
        self.execution.replay_reader = invalid_reader
        with self.assertRaises(BusinessConflict):
            self.replay()
        self.assertEqual(self.accounting(), before)
        self.assertEqual(self.facts.get_context("test", "S01"), self.context)
        with self.store.transaction() as tx:
            self.assertEqual(tx.execute("SELECT COUNT(*) FROM cash_events").fetchone()[0], 0)
            self.assertEqual(tx.execute("SELECT quantity FROM inventory_reservations").fetchone()[0], 80)

    def test_zero_purchase_requires_explicit_supplier_confirmation(self):
        self.context = self.facts.import_scenario("test", "S07")["context"]
        dto = self.facts.query({"context": self.context})
        target = dto["reference_data"]["target"]
        risk_key = "S07:" + ":".join(target[k] for k in ("store_id", "sku_id", "lot_id")) + ":slow_moving"
        comparison_request = {"context": self.context, "horizon_end": "2026-10-10", "inputs": {"sales_settlement_days": 0}, "risk_keys": [risk_key]}
        comparison = self.calculations.compare(dto, comparison_request)
        candidate = next(c for c in comparison["candidates"] if c["action_type"] == "procurement")
        self.assertEqual(candidate["quantity"], 0)
        self.saved = self.execution.save_proposal(self.command(**comparison_request, expected_current_proposal_version=0,
            comparison_id=comparison["comparison_id"], candidate_id=candidate["candidate_id"]))
        confirmed = self.execution.confirm_and_schedule(self.confirmation(self.saved))
        self.context = confirmed["context"]
        task = confirmed["tasks"][0]
        self.assertEqual(task["execution_status"], "pending")
        action = candidate["calculation"]["execution_plan"]["actions"][0]
        record = {**{k: action[k] for k in ("intent_id", "store_id", "sku_id", "supplier_id")},
            "task_id": task["task_id"], "event_id": "supplier-cancel", "event_type": "purchase_cancelled", "quantity": 0,
            "known_at": self.context["as_of"], "occurred_at": self.context["as_of"], "receipt_ref": "supplier-reply"}
        result = self.execution.record_business_events(self.command(events=[{"kind": "business", "record": record}]))
        self.context = result["context"]
        self.assertEqual(self.accounting()["tasks"][0]["execution_status"], "completed")
        self.assertEqual(self.accounting()["cash_out"], 0)

    def test_purchase_receipt_cannot_replace_approved_supplier_or_intent(self):
        self.approve("S07", inputs={}, strategy="purchase")
        action = self.accounting()["tasks"][0]["plan"]["actions"][0]
        for field in ("supplier_id", "intent_id", "expected_arrival_date"):
            record = {"task_id": self.task_id, "event_id": "invalid-order", "event_type": "order_confirmed",
                      "known_at": self.context["as_of"], "occurred_at": self.context["as_of"],
                      "quantity": 60, "unit_cost": 40, "store_id": "ST-004", "sku_id": "SKU-003",
                      "po_line_id": "NEW-ORDER", "payment_due": action["payment_date"], field: "unapproved"}
            with self.subTest(field=field), self.assertRaises(BusinessConflict):
                self.execution.record_business_events(self.command(events=[{"kind": "business", "record": record}]))
        self.assertEqual(self.accounting()["timeline"], [])


if __name__ == "__main__":
    unittest.main()
