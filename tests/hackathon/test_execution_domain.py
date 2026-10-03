"""Domain execution checks using calculated plans and the shipped replay events."""
from copy import deepcopy
from decimal import Decimal
import unittest

from backend.errors import BusinessConflict
from backend.hackathon_calculations.calculations import compare_options, calculate_return, calculate_promotion, calculate_purchase
from backend.hackathon_data.loader import load_scenario, load_replay, parse_clock
from backend.hackathon_execution.domain import (
    initial_execution, arrange_execution, apply_return_confirmation, apply_business_receipt,
    apply_sale, apply_cash, apply_cash_allocation, project_execution, resource,
)


END = "2026-11-01T23:59:59+08:00"


class ScenarioExecutionTests(unittest.TestCase):
    def test_partial_return_cannot_receive_full_exchange_or_credit(self):
        for branch in ("exchange", "payable_credit"):
            facts, state, task_id = self.make("S05", branch)
            row = next(r for _, _, table, r in self.events(facts, task_id) if table == "return_confirmations")
            row["accepted_qty"] = 50
            with self.subTest(branch=branch), self.assertRaises(BusinessConflict):
                apply_return_confirmation(state, row)
            self.assertEqual(state["return_confirmations"], [])

    def test_later_receipt_cannot_support_an_earlier_sale(self):
        facts, state, task_id = self.make()
        events = self.events(facts, task_id)
        out = next(r for _, _, table, r in events if table == "business_receipts" and r["event_type"] == "transfer_shipped")
        incoming = next(r for _, _, table, r in events if table == "business_receipts" and r["event_type"] == "transfer_received")
        apply_business_receipt(state, out)
        apply_business_receipt(state, {**incoming, "quantity": 40})
        apply_business_receipt(state, {**incoming, "event_id": "later-receipt", "quantity": 40,
                                      "occurred_at": "2026-10-08T12:00:00+08:00", "known_at": "2026-10-08T12:00:00+08:00"})
        sale = next(r for _, _, table, r in events if table == "sales" and r.get("task_id") == task_id)
        sale.update(sale_id="backdated-sale", date="2026-10-05", sold_qty=60, sales_amount=6000, sold_cost=4800)
        with self.assertRaises(BusinessConflict):
            apply_sale(state, sale)
        self.assertEqual(state["sales"], [])

    def test_multiple_shipments_preserve_each_receipt_limit(self):
        facts = load_scenario("S07")
        incoming = next(r for r in facts["tables"]["inventory"] if r["stock_state"] == "in_transit")
        second = {**incoming, "inventory_id": "second-shipment-stock", "shipment_line_id": "second-shipment", "quantity": 20}
        facts["tables"]["inventory"].append(second)
        state = initial_execution(facts)
        position = state["positions"][resource(incoming, "in_transit")]
        self.assertEqual(position["quantity"], incoming["quantity"] + 20)
        receipt = {"event_id": "receive-too-much", "event_type": "purchase_received", "task_id": None,
                   "store_id": incoming["store_id"], "sku_id": incoming["sku_id"], "lot_id": incoming["lot_id"],
                   "shipment_line_id": incoming["shipment_line_id"], "quantity": incoming["quantity"] + 1,
                   "occurred_at": "2026-10-04T12:00:00+08:00", "known_at": "2026-10-04T12:00:00+08:00"}
        with self.assertRaises(BusinessConflict):
            apply_business_receipt(state, receipt)

    def make(self, scenario="S01", branch=None):
        facts = load_scenario(scenario, branch)
        if scenario in {"S01", "S09"}:
            options = compare_options(facts, {"quantity": 80, "target_store_id": "ST-002", "sales_settlement_days": 0})
            candidate = next(row for row in options["candidates"] if row["type"] == "transfer")
        elif scenario == "S05":
            terms = {"packaging_confirmed": True, "supplier_confirmed": True, "freight_fee": 30,
                     "acceptance_date": "2026-10-05"}
            if branch == "exchange":
                terms.update(replacement_sku_id="SKU-006", replacement_lot_id="SCLOT-S05-REPLACEMENT",
                             replacement_qty=100, replacement_unit_cost=9, cash_difference=0)
            elif branch == "payable_credit":
                terms.update(payable_id="AP-S05-001", credit_apply_date="2026-10-16")
            candidate = calculate_return(facts, {"return_terms": terms})
        elif scenario == "S06":
            candidate = calculate_promotion(facts, {"sales_settlement_days": 0})
        else:
            candidate = calculate_purchase(facts)
        self.assertEqual(candidate["feasibility"], "feasible", candidate)
        state = initial_execution(facts)
        proposal = {"id": "proposal-1", "version": 1, "candidate": candidate, "evaluation_end": facts["evaluation_end"]}
        task = arrange_execution(state, proposal, actor_id="P-001", owner_id="P-002", due_at="2026-10-04T17:00:00+08:00")
        return facts, state, task["id"]

    def task(self, state, task_id):
        return next(item for item in state["tasks"] if item["id"] == task_id)

    def events(self, facts, task_id, clock=END):
        replay = load_replay(facts["scenario_id"], facts["branch_id"], clock_at=clock)["tables"]
        order = ["return_confirmations", "business_receipts", "sales", "cash_events", "cash_allocations"]
        events = []
        for index, table in enumerate(order):
            for original in replay[table]:
                row = deepcopy(original)
                if row.get("task_id"):
                    row["task_id"] = task_id
                events.append((parse_clock(row.get("occurred_at") or row["known_at"]), index, table, row))
        return sorted(events, key=lambda item: (item[0], item[1]))

    def apply(self, state, task_id, table, row):
        row = deepcopy(row)
        if table == "cash_events" and row["direction"] == "out":
            action = self.task(state, task_id)["plan"]["actions"][0]
            if row["business_ref"] == self.task(state, task_id)["progress"].get("po_line_id"):
                row.update(task_id=task_id, category="purchase_payment")
            elif row["business_ref"] == action.get("payable_id"):
                row.update(task_id=task_id, category="payable_payment")
            else:
                row.update(task_id=task_id, category="execution_fee")
        function = {"return_confirmations": apply_return_confirmation, "business_receipts": apply_business_receipt,
                    "sales": apply_sale, "cash_events": apply_cash, "cash_allocations": apply_cash_allocation}[table]
        return function(state, row)

    def replay(self, facts, state, task_id, clock=END):
        for _, _, table, row in self.events(facts, task_id, clock):
            self.apply(state, task_id, table, row)
        return project_execution(state, clock_at=clock)

    def test_transfer_owns_only_original_lot_sales_and_allocated_cash(self):
        facts, state, task_id = self.make()
        result = self.replay(facts, state, task_id)
        task = self.task(state, task_id)
        self.assertEqual(task["result"]["sales_amount"], 6400)
        self.assertEqual(task["result"]["sales_cash_received"], 6400)
        self.assertEqual(task["result"]["sold_cost"], 5120)
        self.assertEqual(task["result"]["execution_fees_paid"], 24)
        self.assertEqual(task["result"]["realized_gross_profit_less_paid_fees"], 1256)
        self.assertEqual(result["cash_in"], 7400)
        self.assertEqual(result["net_cash_change"], 7376)
        self.assertEqual(state["positions"]["ST-002|SKU-001|LOT-001-001|on_hand"]["quantity"], 16)
        self.assertEqual(task["accounting_status"], "completed")
        before = deepcopy(state)
        self.replay(facts, state, task_id)
        self.assertEqual(state, before)

    def test_partial_transfer_keeps_unexecuted_and_unpaid_separate(self):
        facts, state, task_id = self.make("S09")
        self.replay(facts, state, task_id)
        task = self.task(state, task_id)
        self.assertEqual(task["progress"]["received_qty"], 60)
        self.assertEqual(task["result"]["remaining_execution_qty"], 20)
        self.assertEqual(task["result"]["sales_receivable"], 1000)
        self.assertEqual(task["execution_status"], "in_progress")
        self.assertEqual(task["accounting_status"], "in_progress")

    def test_transfer_accounting_waits_until_observation_period_ends(self):
        facts, state, task_id = self.make()
        self.replay(facts, state, task_id, "2026-10-04T23:00:00+08:00")
        task = self.task(state, task_id)
        self.assertEqual(task["execution_status"], "completed")
        self.assertEqual(task["result"]["sales_receivable"], 0)
        self.assertEqual(task["accounting_status"], "in_progress")

    def test_refund_is_cash_after_acceptance_and_matching_not_inventory_cost(self):
        facts, state, task_id = self.make("S05", "cash_refund")
        result = self.replay(facts, state, task_id)
        task = self.task(state, task_id)
        self.assertEqual(task["result"]["refund_cash_received"], 900)
        self.assertEqual(result["net_cash_change"], 870)
        self.assertEqual(task["result"]["sales_amount"], 0)
        self.assertEqual(task["accounting_status"], "completed")

    def test_refund_alias_cannot_match_the_same_receivable_twice(self):
        facts, state, task_id = self.make("S05", "cash_refund")
        self.replay(facts, state, task_id)
        confirmation = state["return_confirmations"][0]
        incoming = next(row for row in state["cash_events"] if row["direction"] == "in")
        extra = {**incoming, "cash_event_id": "different-cash", "receipt_ref": "different-bank-ref"}
        apply_cash(state, extra)
        allocation = {"allocation_id": "second-alias", "cash_event_id": extra["cash_event_id"],
                      "business_ref": confirmation["confirmation_ref"], "allocated_amount": 900}
        with self.assertRaises(BusinessConflict):
            apply_cash_allocation(state, allocation)

    def test_credit_changes_payable_then_records_only_actual_remainder_payment(self):
        facts, state, task_id = self.make("S05", "payable_credit")
        result = self.replay(facts, state, task_id)
        payable = next(row for row in state["payables"] if row["payable_id"] == "AP-S05-001")
        self.assertEqual(payable["applied_credit_amount"], 900)
        self.assertEqual(payable["paid_amount"], 1100)
        self.assertEqual(payable["outstanding_amount"], 0)
        self.assertEqual(result["cash_in"], 0)
        self.assertEqual(result["cash_out"], 1130)
        self.assertEqual(self.task(state, task_id)["accounting_status"], "completed")

    def test_credit_cannot_complete_at_acceptance_or_issue_extra_note(self):
        facts, state, task_id = self.make("S05", "payable_credit")
        self.replay(facts, state, task_id, "2026-10-05T23:00:00+08:00")
        self.assertEqual(self.task(state, task_id)["accounting_status"], "in_progress")
        events = self.events(facts, task_id)
        issued = next(row for _, _, table, row in events if table == "business_receipts" and row["event_type"] == "credit_issued")
        apply_business_receipt(state, issued)
        second = {**issued, "event_id": "second-credit", "credit_note_id": "CN-002"}
        before = deepcopy(state)
        with self.assertRaises(BusinessConflict):
            apply_business_receipt(state, second)
        self.assertEqual(before, state)

    def test_partial_exchange_does_not_complete_and_never_creates_cash_in(self):
        facts, state, task_id = self.make("S05", "exchange")
        events = self.events(facts, task_id)
        replacement = None
        for _, _, table, row in events:
            if table == "business_receipts" and row["event_type"] == "exchange_received":
                replacement = row
                break
            self.apply(state, task_id, table, row)
        partial = {**replacement, "event_id": "partial-replacement", "quantity": 1}
        apply_business_receipt(state, partial)
        project_execution(state, clock_at=END)
        self.assertEqual(self.task(state, task_id)["execution_status"], "in_progress")
        rest = {**replacement, "event_id": "remaining-replacement", "quantity": 99}
        apply_business_receipt(state, rest)
        result = project_execution(state, clock_at=END)
        self.assertEqual(self.task(state, task_id)["execution_status"], "completed")
        self.assertEqual(result["cash_in"], 0)
        position = state["positions"]["ST-003|SKU-006|SCLOT-S05-REPLACEMENT|on_hand"]
        self.assertEqual(position["quantity"], 100)
        self.assertEqual(position["unit_cost"], 9)

    def test_promotion_tracks_components_without_adding_units_to_bundle_count(self):
        facts, state, task_id = self.make("S06")
        self.replay(facts, state, task_id)
        task = self.task(state, task_id)
        self.assertEqual(task["result"]["sales_amount"], 420)
        self.assertEqual(task["result"]["sold_cost"], 320)
        self.assertEqual(task["result"]["execution_fees_paid"], 20)
        self.assertEqual(task["result"]["sold_components"], {"SKU-004": 40, "SKU-008": 40})
        self.assertIsNone(task["result"]["remaining_execution_qty"])
        self.assertEqual(task["accounting_status"], "completed")
        self.assertEqual(state["positions"]["ST-004|SKU-004|LOT-004-004|on_hand"]["quantity"], 20)
        self.assertEqual(state["positions"]["ST-004|SKU-008|LOT-004-008|on_hand"]["quantity"], 20)

    def test_purchase_does_not_complete_accounting_on_goods_receipt_alone(self):
        facts, state, task_id = self.make("S07")
        self.replay(facts, state, task_id, "2026-10-05T23:59:00+08:00")
        task = self.task(state, task_id)
        self.assertEqual(task["execution_status"], "completed")
        self.assertEqual(task["accounting_status"], "in_progress")
        self.assertEqual(task["result"]["outstanding_cash"], 2400)
        self.replay(facts, state, task_id)
        self.assertEqual(self.task(state, task_id)["result"]["purchase_cash_paid"], 2400)
        self.assertEqual(self.task(state, task_id)["accounting_status"], "completed")
        self.assertEqual(sum(row["quantity"] for row in state["positions"].values()
                             if row["store_id"] == "ST-004" and row["sku_id"] == "SKU-003" and row["stock_state"] == "on_hand"), 70)

    def test_event_identity_conflict_and_invalid_quantities_are_atomic(self):
        facts, state, task_id = self.make()
        shipped = next(row for _, _, table, row in self.events(facts, task_id) if table == "business_receipts" and row["event_type"] == "transfer_shipped")
        for value in (-1, True, False, "NaN", "Infinity", 121):
            before = deepcopy(state)
            with self.assertRaises((ValueError, BusinessConflict)):
                apply_business_receipt(state, {**shipped, "quantity": value})
            self.assertEqual(state, before)
        self.assertTrue(apply_business_receipt(state, shipped))
        self.assertFalse(apply_business_receipt(state, shipped))
        before = deepcopy(state)
        with self.assertRaises(BusinessConflict):
            apply_business_receipt(state, {**shipped, "quantity": 1})
        self.assertEqual(state, before)

    def test_cancellation_or_replan_stops_new_shipments_but_allows_actual_receipt(self):
        facts, state, task_id = self.make("S09")
        events = self.events(facts, task_id)
        shipped = next(row for _, _, table, row in events if table == "business_receipts" and row["event_type"] == "transfer_shipped")
        received = next(row for _, _, table, row in events if table == "business_receipts" and row["event_type"] == "transfer_received")
        apply_business_receipt(state, shipped)
        self.task(state, task_id)["cancelled"] = True
        self.task(state, task_id)["exception_flags"].append("replan_required")
        self.assertTrue(apply_business_receipt(state, received))
        with self.assertRaises(BusinessConflict):
            apply_business_receipt(state, {**shipped, "event_id": "later-shipment", "quantity": 20})

    def test_unconfirmed_or_nonexecutable_candidates_do_not_reserve_stock(self):
        facts = load_scenario("S05", "cash_refund")
        candidate = calculate_return(facts)
        state = initial_execution(facts)
        with self.assertRaises(BusinessConflict):
            arrange_execution(state, {"id": "pending", "version": 1, "candidate": candidate},
                              actor_id="P-001", owner_id="P-004", due_at=END)
        self.assertEqual(state["reservations"], [])
        facts = load_scenario("S01")
        candidate = compare_options(facts, {"sales_settlement_days": 0})["baseline"]
        with self.assertRaises(ValueError):
            arrange_execution(state, {"id": "retain", "version": 1, "candidate": candidate},
                              actor_id="P-001", owner_id="P-004", due_at=END)


if __name__ == "__main__":
    unittest.main()
