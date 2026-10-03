"""Isolated overview checks: liabilities, stock, risk and cash remain distinct."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
import json

from backend.errors import BusinessConflict
from backend.hackathon_data.overview import commitments
from backend.hackathon_data.service import RetailFactService, migrate
from backend.serialization import dumps
from backend.store import Store


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="retail-overview-")
        self.store = Store(str(Path(self.temp.name) / "overview.db"))
        with self.store.transaction() as tx:
            migrate(tx)
        self.facts = RetailFactService(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def overview(self, scenario="S01", branch=None):
        context = self.facts.import_scenario("tenant-a", scenario, branch)["context"]
        return self.facts.get_overview({"context": context})

    def test_imported_scope_and_unconnected_stores_stay_separate(self):
        result = self.overview()
        overview = result["overview"]
        self.assertEqual(overview["account"]["balance"], 858900)
        self.assertEqual(overview["purchase_commitments"]["amount"], 8000)
        self.assertEqual(overview["purchase_commitments"]["count"], 1)
        self.assertEqual(len(overview["stores"]), 50)
        self.assertEqual(result["metadata"]["included_store_count"], 6)
        self.assertEqual(overview["inventory"]["cost"], sum(row["inventory_cost"] for row in overview["stores"] if row["inventory_cost"] is not None))
        self.assertGreater(overview["stores"][0]["turnover_days"], 0)
        absent = next(row for row in overview["stores"] if row["store_id"] == "ST-050")
        self.assertIsNone(absent["inventory_cost"])
        self.assertIsNone(absent["risk_cost"])
        self.assertIn("stores.ST-050.business_facts", absent["missing_fields"])

    def test_overlapping_risks_count_inventory_once_and_unknown_stays_unknown(self):
        overlapping = self.overview("S02")["overview"]
        self.assertEqual(overlapping["inventory"], {**overlapping["inventory"], "cost": 8000, "risk_cost": 8000})
        store = next(row for row in overlapping["stores"] if row["inventory_cost"] is not None)
        self.assertEqual(len(store["risk_types"]), 2)
        unknown = self.overview("S10", "missing_sales")
        self.assertIsNone(unknown["overview"]["inventory"]["risk_cost"])
        self.assertTrue(unknown["metadata"]["missing_fields"])

    def test_account_reads_shared_cash_once_within_same_transaction_and_scope(self):
        before = self.overview()
        context = before["context"]
        with self.assertRaisesRegex(RuntimeError, "rollback"), self.store.transaction() as tx:
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", ("cash-a", "tenant-a", context["snapshot_id"], "fee", "24", "out", "2026-10-03", "TASK-1", "hackathon_execution:ACC-001", "receipt-a"))
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", ("cash-b", "tenant-other", context["snapshot_id"], "fee", "1000", "out", "2026-10-03", "TASK-2", "hackathon_execution:ACC-001", "receipt-b"))
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", ("cash-future", "tenant-a", context["snapshot_id"], "fee", "240", "out", "2026-10-04", "TASK-1", "hackathon_execution:ACC-001", "receipt-future"))
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", ("cash-later-today", "tenant-a", context["snapshot_id"], "fee", "120", "out", "2026-10-03T10:00:00+08:00", "TASK-1", "hackathon_execution:ACC-001", "receipt-later"))
            current = self.facts.get_overview({"context": context}, tx=tx)
            self.assertEqual(current["overview"]["account"]["balance"], 858876)
            self.assertEqual(current["overview"]["inventory"], before["overview"]["inventory"])
            self.assertEqual(self.facts.get_overview({"context": context}, tx=tx), current)
            tx.execute("INSERT INTO cash_events VALUES(?,?,?,?,?,?,?,?,?,?)", ("cash-unknown", "tenant-a", context["snapshot_id"], "fee", None, "out", "2026-10-03", "TASK-1", "hackathon_execution:ACC-001", "receipt-unknown"))
            unknown = self.facts.get_overview({"context": context}, tx=tx)
            self.assertIsNone(unknown["overview"]["account"]["balance"])
            self.assertEqual(unknown["overview"]["account"]["status"], "unknown")
            self.assertIn("cash_events.cash-unknown.amount", unknown["metadata"]["missing_fields"])
            raise RuntimeError("rollback")
        self.assertEqual(self.facts.get_overview({"context": context}), before)
        with self.assertRaises(BusinessConflict):
            self.facts.get_overview({"context": {**context, "fact_version": 999}})

    def test_missing_inventory_cost_preserves_risk_and_unknown_overview(self):
        context = self.facts.import_scenario("tenant-a", "S02")["context"]
        with self.store.transaction() as tx:
            row = tx.execute("SELECT scope_key,version,state_json FROM hackathon_fact_versions").fetchone()
            state = json.loads(row["state_json"])
            state["inventory"][0]["unit_cost"] = None
            tx.execute("UPDATE hackathon_fact_versions SET state_json=? WHERE scope_key=? AND version=?",
                       (dumps(state), row["scope_key"], row["version"]))
        result = self.facts.get_overview({"context": context})
        self.assertIsNone(result["overview"]["inventory"]["cost"])
        self.assertIsNone(result["overview"]["inventory"]["risk_cost"])
        store = next(row for row in result["overview"]["stores"] if row["risk_types"])
        self.assertEqual(len(store["risk_types"]), 2)
        self.assertTrue(any(field.endswith("unit_cost_cny") for field in store["missing_fields"]))


class CommitmentsTests(unittest.TestCase):
    def test_liability_deduplication_date_boundaries_and_unknown_payment(self):
        tables = {"payables": [{"payable_id": "AP-1", "po_id": "PO-1", "due_at": "2026-10-03", "outstanding_amount": 75, "status": "unpaid"},
                               {"payable_id": "AP-2", "due_at": "2026-11-02", "outstanding_amount": 500, "status": "unpaid"}],
                  "purchase_orders": [{"po_id": "PO-1", "po_line_id": "LINE-1", "ordered_qty": 100, "unit_cost": 1,
                                       "paid_amount": 0, "due_at": "2026-10-03", "order_status": "confirmed"},
                                      {"po_id": "PO-2", "po_line_id": "LINE-2", "ordered_qty": 50, "unit_cost": 2,
                                       "paid_amount": 0, "due_at": "2026-11-01", "order_status": "confirmed"},
                                      {"po_id": "PO-3", "po_line_id": "LINE-3", "ordered_qty": 999, "unit_cost": 2,
                                       "paid_amount": 0, "due_at": "2026-10-03", "order_status": "draft"}]}
        result = commitments(tables, date(2026, 10, 3))
        self.assertEqual((result["amount"], result["count"]), (175, 2))
        tables["payables"].append({"payable_id": "AP-UNKNOWN", "due_at": None, "outstanding_amount": 90, "status": "unpaid"})
        result = commitments(tables, date(2026, 10, 3))
        self.assertIsNone(result["amount"])
        self.assertIsNone(result["count"])
        self.assertEqual(result["known_amount"], 175)
        self.assertEqual(result["missing_fields"], ["payables.AP-UNKNOWN.due_at"])

    def test_partial_line_payable_does_not_hide_other_lines_of_same_order(self):
        tables = {"payables": [{"payable_id": "AP-1", "po_id": "PO-1", "po_line_id": "LINE-1", "due_at": "2026-10-05", "outstanding_amount": 5}],
                  "purchase_orders": [{"po_id": "PO-1", "po_line_id": line, "due_at": "2026-10-05", "ordered_qty": 10,
                                       "unit_cost": 2, "paid_amount": 0, "order_status": "confirmed"} for line in ("LINE-1", "LINE-2")]}
        self.assertEqual(commitments(tables, date(2026, 10, 3))["amount"], 25)
        tables["payables"][0]["status"] = "void"
        self.assertEqual(commitments(tables, date(2026, 10, 3))["amount"], 40)
