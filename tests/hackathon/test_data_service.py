"""Shared-transaction and authoritative-fact regressions using synthetic fixtures."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from backend.errors import BusinessConflict
from backend.hackathon_data.service import RetailFactService, migrate
from backend.store import Store


class FactServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="retail-facts-")
        self.store = Store(str(Path(self.directory.name) / "test.db"))
        with self.store.transaction() as tx:
            migrate(tx)
        self.facts = RetailFactService(self.store)
        self.context = self.facts.import_scenario("tenant-a", "S01")["context"]

    def tearDown(self):
        self.store.conn.close()
        self.directory.cleanup()

    def event(self, event_id="EV-1", kind="sale", **fields):
        row = {key: self.context[key] for key in ("tenant_id", "scenario_id", "branch_id")}
        row.update(event_id=event_id, event_type=kind, task_id="task-a", proposal_id="proposal-a", proposal_version=1,
                   occurred_at="2026-10-03T10:00:00+08:00", known_at="2026-10-03T10:00:00+08:00",
                   store_id="ST-001", sku_id="SKU-001", lot_id="LOT-001-001", quantity=2, base_unit="盒",
                   source="synthetic_receipt", is_demo=True, external_write=False, amount_cny=200)
        row.update(fields)
        return row

    def apply(self, *events):
        with self.store.transaction() as tx:
            result = self.facts.apply_business_events(tx, list(events), expected_fact_version=self.context["fact_version"])
        self.context = result["context"]
        return result

    def inventory(self, **filters):
        return [row for row in self.facts.query({"context": self.context})["inventory"]
                if all(row.get(key) == value for key, value in filters.items())]

    def test_import_is_idempotent_and_tenant_branch_isolated(self):
        original = self.facts.import_scenario("tenant-a", "S01")
        self.assertTrue(original["idempotent_replay"])
        self.assertEqual(original["context"], self.context)
        other = self.facts.import_scenario("tenant-b", "S01")["context"]
        self.assertNotEqual(other["snapshot_id"], self.context["snapshot_id"])
        with self.store.transaction() as tx:
            self.assertEqual(tx.execute("SELECT COUNT(*) FROM real_inventory_snapshots").fetchone()[0], 0)
        forged = {**self.context, "tenant_id": "tenant-b"}
        with self.assertRaises(BusinessConflict):
            self.facts.query({"context": forged})

    def test_public_shape_and_unknown_directory_store(self):
        result = self.facts.query({"context": self.context, "include": []})
        self.assertEqual(len(result["reference_data"]["tables"]["products"]), 12)
        self.assertEqual(result["inventory"][0]["unit_cost_cny"], 80)
        self.assertNotIn("inventory", result["reference_data"]["tables"])
        self.assertNotIn("execution_receipts", result["reference_data"]["tables"])
        incomplete = self.facts.query({"context": self.context, "store_ids": ["ST-050"]})
        self.assertEqual(incomplete["inventory"], [])
        self.assertIn("stores.ST-050.business_facts", incomplete["missing_fields"])
        risk = self.facts.assess_risks({"context": self.context, "store_ids": ["ST-050"]})
        self.assertIsNone(risk["attention_inventory_cost_cny"])
        self.assertEqual(risk["missing_fields"], ["stores.ST-050.business_facts"])
        with self.assertRaises(ValueError):
            self.facts.query({"context": self.context, "lot_ids": ["FAKE-LOT"]})

    def test_provenance_and_missing_context_cannot_be_forged(self):
        context = self.facts.import_scenario("tenant-a", "S10", "missing_sales")["context"]
        self.assertTrue(context["missing_fields"])
        fake_source = deepcopy(context["source_refs"])
        fake_source[0].update(source="customer_erp", is_demo=False)
        false_type = deepcopy(context["source_refs"])
        false_type[0]["is_demo"] = 1
        changes = ({"is_demo": False}, {"is_demo": 1}, {"source_refs": fake_source},
                   {"source_refs": false_type}, {"source_refs": []}, {"missing_fields": []})
        for change in changes:
            forged = {**context, **change}
            with self.subTest(change=change):
                with self.assertRaises(BusinessConflict):
                    self.facts.query({"context": forged})
                with self.assertRaises(BusinessConflict):
                    self.facts.assess_risks({"context": forged})
        echoed = self.facts.query({"context": {**context, "untrusted_note": "real customer facts"}})
        self.assertEqual(echoed["context"], context)
        self.assertNotIn("untrusted_note", echoed["context"])
        self.assertEqual(self.facts.get_context("tenant-a", "S10", "missing_sales"), context)

    def test_overlap_keeps_two_risk_keys_and_one_cost(self):
        context = self.facts.import_scenario("tenant-a", "S02")["context"]
        result = self.facts.assess_risks({"context": context})
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["attention_inventory_cost_cny"], 8000)
        self.assertEqual(len(result["counted_inventory_keys"]), 1)
        self.assertNotEqual(result["items"][0]["risk_key"], result["items"][1]["risk_key"])
        self.assertEqual(result["items"][0]["risk_id"], result["items"][1]["risk_id"])
        self.assertIsNone(self.facts.resolve_legacy_risk_id(context, "S01:ST-001:SKU-001:LOT-001-001:slow_moving"))

    def test_missing_values_are_unknown(self):
        context = self.facts.import_scenario("tenant-a", "S10", "missing_sales")["context"]
        result = self.facts.assess_risks({"context": context})
        self.assertIsNone(result["attention_inventory_cost_cny"])
        self.assertEqual(result["items"][0]["result"], "insufficient_data")
        self.assertIsNone(result["items"][0]["amount_cny"])

    def test_event_dedupe_stale_version_and_rollback(self):
        original_context = deepcopy(self.context)
        event = self.event()
        result = self.apply(event)
        self.assertEqual(result["applied_event_ids"], ["EV-1"])
        self.assertEqual(self.inventory(store_id="ST-001", sku_id="SKU-001", lot_id="LOT-001-001")[0]["quantity"], 118)
        with self.store.transaction() as tx:
            retry = self.facts.apply_business_events(tx, [dict(reversed(list(event.items())))], expected_fact_version=1)
        self.assertEqual(retry["duplicate_event_ids"], ["EV-1"])
        with self.assertRaises(BusinessConflict):
            self.facts.query({"context": original_context})
        with self.assertRaises(BusinessConflict):
            self.apply({**event, "quantity": 3})
        before = deepcopy(self.context)
        with self.assertRaises(ValueError):
            with self.store.transaction() as tx:
                self.facts.apply_business_events(tx, [self.event("EV-2")], expected_fact_version=2)
                raise ValueError("fail a later shared write")
        self.assertEqual(self.facts.get_context("tenant-a", "S01"), before)
        self.assertEqual(self.inventory(store_id="ST-001", sku_id="SKU-001", lot_id="LOT-001-001")[0]["quantity"], 118)

    def test_invalid_batch_publishes_no_partial_changes(self):
        for quantity in (True, -1, float("nan"), float("inf"), 121):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.apply(self.event("EV-good"), self.event("EV-bad", quantity=quantity))
            self.assertEqual(self.facts.get_context("tenant-a", "S01")["fact_version"], 1)
        with self.assertRaises(ValueError):
            self.apply(self.event("EV-other", tenant_id="tenant-b"))

    def test_transfer_updates_owned_stock_and_shipment_once(self):
        self.apply(self.event("ship", "transfer_shipped", quantity=80, target_store_id="ST-002", amount_cny=None,
                              details={"expected_arrival_at": "2026-10-04T12:00:00+08:00"}))
        inbound = self.inventory(store_id="ST-002", sku_id="SKU-001", lot_id="LOT-001-001", stock_state="in_transit")
        self.assertEqual(inbound[0]["quantity"], 80)
        self.assertEqual(inbound[0]["shipment_line_id"], "transfer:task-a")
        self.apply(self.event("receive", "transfer_received", store_id="ST-002", quantity=30, amount_cny=None))
        inbound = self.inventory(store_id="ST-002", sku_id="SKU-001", lot_id="LOT-001-001", stock_state="in_transit")
        self.assertEqual(inbound[0]["quantity"], 50)
        shipment = next(row for row in self.facts.query({"context": self.context})["procurement"] if row.get("shipment_line_id") == "transfer:task-a")
        self.assertEqual(shipment["received_qty"], 30)
        self.assertEqual(shipment["status"], "partially_received")

    def test_inbound_receipt_does_not_reappear_as_unshipped_order(self):
        self.apply(self.event("incoming", "purchase_received", store_id="ST-003", lot_id="LOT-INBOUND-001", quantity=100,
                              details={"po_line_id": "POL-FUT-001", "shipment_line_id": "SHIP-001"}))
        rows = self.facts.query({"context": self.context})["procurement"]
        order = next(row for row in rows if row.get("po_line_id") == "POL-FUT-001")
        shipment = next(row for row in rows if row.get("shipment_line_id") == "SHIP-001")
        self.assertEqual(order["received_qty"], 100)
        self.assertEqual(order["order_status"], "completed")
        self.assertEqual(shipment["received_qty"], 100)

    def test_clock_does_not_apply_future_actuals(self):
        before = self.inventory()
        with self.store.transaction() as tx:
            self.context = self.facts.advance_clock(tx, self.context, "2026-10-25T20:00:00+08:00")["context"]
        self.assertEqual(self.inventory(), before)
        self.assertEqual(self.facts.query({"context": self.context})["reference_data"]["tables"]["accounts"][0]["available_balance"], 858900)

    def test_confirmed_calendar_override_survives_later_clock(self):
        self.context = self.facts.import_scenario("tenant-a", "S08", "closed_target")["context"]
        with self.store.transaction() as tx:
            self.context = self.facts.advance_clock(tx, self.context, "2026-10-03T10:05:00+08:00", confirmed_override_ids=["OV-011", "OV-012"])["context"]
        with self.store.transaction() as tx:
            self.context = self.facts.advance_clock(tx, self.context, "2026-10-04T10:00:00+08:00")["context"]
        calendar = self.facts.query({"context": self.context})["reference_data"]["tables"]["store_calendar"]
        day = next(row for row in calendar if row["store_id"] == "ST-002" and row["date"] == "2026-10-04")
        self.assertFalse(day["is_open"])
        self.assertFalse(day["can_receive"])

    def test_material_confirmation_is_intent_not_order_and_requires_acknowledgement(self):
        fields = {"store_id": "ST-001", "sku_id": "SKU-001", "supplier_id": "SUP-001", "quantity": 20,
                  "unit": "盒", "unit_cost_cny": 80, "expected_arrival_date": "2026-10-06", "payment_date": None}
        event = self.event("material", "material_confirmed", business_ref="DRAFT-NEW", receipt_ref="MAT-NEW",
                           details={"material_kind": "purchase_intent", "fields": fields, "accepted_unresolved_fields": []})
        with self.assertRaises(ValueError):
            self.apply(event)
        event["details"]["accepted_unresolved_fields"] = ["payment_date"]
        self.apply(event)
        facts = self.facts.query({"context": self.context})
        intent = facts["reference_data"]["tables"]["purchase_intents"][0]
        self.assertIsNone(intent["payment_date"])
        self.assertTrue(intent["confirmation_required"])
        self.assertFalse(any(row.get("po_line_id") == "DRAFT-NEW" for row in facts["procurement"]))

    def test_no_internal_commit_on_import(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction() as tx:
                self.facts.import_scenario("rolled-back", "S01", tx=tx)
                raise RuntimeError("rollback caller")
        with self.assertRaises(ValueError):
            self.facts.get_context("rolled-back", "S01")

    def test_shared_reservations_and_cash_are_read_once(self):
        key = "S01:ST-001:SKU-001:LOT-001-001:slow_moving"
        risk_id = self.facts.resolve_legacy_risk_id(self.context, key)
        with self.store.transaction() as tx:
            tx.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?)", ("p", "tenant-a", risk_id, 1, "approved", self.context["snapshot_id"], 1, self.context["as_of"]))
            tx.execute("INSERT INTO inventory_reservations VALUES(?,?,?,?,?,?)", ("tenant-a", self.context["snapshot_id"], "ST-001|SKU-001|LOT-001-001|on_hand", "p", 1, 80))
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", ("cash-a", "tenant-a", self.context["snapshot_id"], "fee", "160", "out", "2026-10-03", "RT-001-002", "hackathon_execution:ACC-001", "receipt-a"))
            result = self.facts.apply_business_events(tx, [self.event("arranged", "execution_scheduled", quantity=None, amount_cny=None)], expected_fact_version=1)
        self.context = result["context"]
        for _ in range(2):
            facts = self.facts.query({"context": self.context})
            stock = next(row for row in facts["inventory"] if row["store_id"] == "ST-001" and row["sku_id"] == "SKU-001")
            self.assertEqual(stock["reserved_qty"], 80)
            self.assertEqual(stock["external_reserved_qty"], 0)
            self.assertEqual(facts["reference_data"]["tables"]["accounts"][0]["available_balance"], 858740)

    def test_credit_is_not_cash_and_settles_payable_once(self):
        self.context = self.facts.import_scenario("tenant-a", "S05", "payable_credit")["context"]
        self.apply(self.event("credit", "credit_issued", amount_cny=900,
                              details={"credit_note_id": "CN-1", "supplier_id": "SUP-002"}))
        self.apply(self.event("apply-credit", "credit_applied", amount_cny=900,
                              details={"credit_note_id": "CN-1", "payable_id": "AP-S05-001"}))
        facts = self.facts.query({"context": self.context})
        payable = next(row for row in facts["payables"] if row["payable_id"] == "AP-S05-001")
        self.assertEqual(payable["outstanding_amount"], 1100)
        self.assertEqual(facts["reference_data"]["tables"]["credit_notes"][0]["remaining_amount"], 0)
        self.assertEqual(facts["reference_data"]["tables"]["accounts"][0]["available_balance"], 858900)
        with self.assertRaises(ValueError):
            self.apply(self.event("over-credit", "credit_applied", amount_cny=1,
                                  details={"credit_note_id": "CN-1", "payable_id": "AP-S05-001"}))

    def test_purchase_cancellation_records_confirmation_without_zero_order(self):
        self.context = self.facts.import_scenario("tenant-a", "S07")["context"]
        before = self.facts.query({"context": self.context})
        intent = before["reference_data"]["tables"]["purchase_intents"][0]
        self.apply(self.event("cancel", "purchase_cancelled", quantity=0, receipt_ref="supplier-ack",
                              details={"intent_id": intent["intent_id"]}))
        after = self.facts.query({"context": self.context})
        self.assertEqual(after["procurement"], before["procurement"])
        self.assertEqual(after["reference_data"]["tables"]["purchase_intents"][0]["intent_status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
