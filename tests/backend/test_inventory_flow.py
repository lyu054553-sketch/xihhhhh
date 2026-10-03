"""Actual imported data, evidence revisions, recomputation and export."""
import base64
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend import api
from backend.store import Store


HEADER = "sku,store,store_id,product,unit,inventory_qty,unit_cost,sales_30,sales_90,sales_cost_30,stat_class,purchase_status"
ROW = "NEW-SKU,真实门店,S-REAL,真实商品,箱,100,12.50,10,30,125,C,在采"


class InventoryFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = str(Path(self.directory.name) / "test.db")
        self.store = Store(self.database)
        self.store.seed_demo()
        self.store_patch = patch.object(api, "store", self.store)
        self.store_patch.start()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        self.store_patch.stop()
        self.store.close()
        self.directory.cleanup()

    def upload(self, content=HEADER+"\n"+ROW, tenant="demo", **overrides):
        response = self.client.post("/api/v1/data-center/imports", headers={"X-Tenant-Id": tenant}, json={
            "filename": "inventory.csv", "content": content, "as_of_date": "2026-10-03", **overrides})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def feedback(self, observations):
        inv = self.store.create_investigation(1)
        feedback = self.store.add_feedback(inv["id"], "实地核查库存", "2026-10-03T12:00:00+08:00", {})
        response = self.client.post(f"/api/v1/feedback/{feedback['id']}/confirm", json={"confirmed": {
            "observed_values": observations, "evidence_ref": "manual-count-001"}})
        self.assertEqual(response.status_code, 200, response.text)
        return feedback["id"]

    def test_csv_changes_actual_inventory_and_teacher_calculation_after_restart(self):
        result = self.upload()
        self.assertEqual(result["status"], "imported")
        overview = self.client.get("/api/v1/retail/overview").json()
        self.assertEqual(overview["inventory"]["cost"], 1250)
        self.assertFalse(overview["is_demo"])
        self.assertIsNone(overview["account"]["balance"])
        self.assertIsNone(overview["purchase_commitments"]["amount"])
        risks = self.client.get("/api/v1/risks").json()["items"]
        self.assertEqual([risk["sku"] for risk in risks], ["NEW-SKU"])
        self.assertEqual(risks[0]["teacher_baseline"]["suggested_reduction_amount"], 875)
        detail = self.client.get(f"/api/v1/risks/{risks[0]['id']}").json()
        self.assertEqual(detail["risk"]["inventory_qty"], 100)
        reopened = Store(self.database)
        try:
            self.assertEqual(reopened.real_inventory_snapshot()["id"], result["summary"]["snapshot_id"])
            self.assertEqual(reopened.risks()[0]["sku"], "NEW-SKU")
        finally:
            reopened.close()
        self.upload((HEADER+"\n"+ROW).replace(",100,12.50,", ",200,12.50,"))
        self.assertEqual(self.client.get("/api/v1/retail/overview").json()["inventory"]["cost"], 2500)
        self.assertEqual(self.client.get("/api/v1/risks").json()["items"][0]["teacher_baseline"]["suggested_reduction_amount"], 2125)

    def test_exact_duplicates_are_removed_and_retry_reuses_snapshot(self):
        first = self.upload(HEADER+"\n"+ROW+"\n"+ROW)
        self.assertEqual(first["summary"]["deduplicated_rows"], 1)
        second = self.upload()
        self.assertEqual(first["summary"]["snapshot_id"], second["summary"]["snapshot_id"])
        self.assertTrue(second["summary"]["replayed"])
        self.assertEqual(len(self.store.rows("SELECT * FROM real_inventory_lines")), 1)
        self.assertEqual(len(self.store.rows("SELECT * FROM audit_events WHERE event_type='inventory_imported'")), 1)

    def test_bad_rows_do_not_replace_existing_snapshot(self):
        first = self.upload()
        invalid = [ROW.replace(",100,", ",-1,"), ROW.replace(",100,", ",1.001,"), ROW.replace("12.50", "NaN"), ROW.replace("12.50", "Infinity"), ROW.replace(",箱,", ",,"), ROW+"\n"+ROW.replace(",100,", ",101,"), ROW+"\n"+ROW.replace("S-REAL", "S-OTHER").replace(",箱,", ",件,")]
        for row in invalid:
            with self.subTest(row=row):
                result = self.upload(HEADER+"\n"+row)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result["errors"])
                self.assertEqual(self.store.real_inventory_snapshot()["id"], first["summary"]["snapshot_id"])

    def test_missing_optional_sales_remains_unknown_and_rules_block(self):
        result = self.upload("sku,store,unit,inventory_qty,unit_cost\nS,门店,箱,10,0")
        self.assertEqual(result["status"], "imported")
        risk = self.store.risks()[0]
        self.assertIsNone(risk["sales_30"])
        self.assertEqual(risk["unit_cost"], 0)
        center = self.client.get("/api/v1/data-center").json()
        self.assertEqual(center["teacher_baseline"]["status"], "blocked")
        self.assertIsInstance(center["sources"][0]["summary"]["cost_total"], (int, float))
        response = self.client.post("/api/v1/workbenches/transfer/calculate", json={"expected_version": 0, "input": {"risk_id": risk["id"]}})
        self.assertEqual(response.status_code, 409)

    def test_xlsx_sheet_selected_explicitly_and_missing_sheet_fails(self):
        workbook = Workbook()
        workbook.active.title = "blank"
        sheet = workbook.create_sheet("inventory")
        sheet.append(HEADER.split(","))
        sheet.append(ROW.split(","))
        buffer = io.BytesIO()
        workbook.save(buffer)
        options = {"filename": "inventory.xlsx", "file_base64": base64.b64encode(buffer.getvalue()).decode(), "sheet_name": "inventory", "content": ""}
        self.assertEqual(self.upload(**options)["status"], "imported")
        self.assertEqual(self.upload(**{**options, "sheet_name": "missing"})["status"], "failed")

    def test_tenant_snapshot_isolated_and_noninventory_is_only_validated(self):
        self.upload(tenant="real-tenant")
        self.assertIsNone(self.store.real_inventory_snapshot("demo"))
        self.assertEqual(self.client.get("/api/v1/retail/overview", headers={"X-Tenant-Id": "real-tenant"}).json()["inventory"]["cost"], 1250)
        result = self.upload("sku,store,sales_qty\nS,门店,10", data_kind="sales")
        self.assertEqual(result["status"], "validated_only")

    def test_audit_failure_rolls_back_import_snapshot_lines_and_risks(self):
        with patch.object(self.store, "audit", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.upload()
        self.assertIsNone(self.store.real_inventory_snapshot())
        self.assertEqual(self.store.rows("SELECT * FROM real_inventory_lines"), [])
        self.assertEqual(len(self.store.risks()), 13)

    def test_confirmed_inventory_changes_replan_quantity_and_computes_new_result(self):
        original = self.store.proposal("PROP-AC10-001")
        self.feedback({"inventory_qty": 60})
        response = self.client.post("/api/v1/risks/1/replan", json={"expected_version": 1})
        self.assertEqual(response.status_code, 200, response.text)
        replanned = response.json()
        self.assertEqual(replanned["version"]["payload"]["input"]["quantity"], 30)
        self.assertEqual(replanned["version"]["payload"]["calculation"]["cash"]["inventory_cost"], 2400)
        self.assertTrue(replanned["version"]["payload"]["diff"]["calculation_recomputed"])
        self.assertEqual(replanned["status"], "pending_approval")
        self.assertEqual(original["current_version"]+1, replanned["current_version"])
        stale = self.client.post("/api/v1/proposals/PROP-AC10-001/approve", json={"expected_version": 1})
        self.assertEqual(stale.status_code, 409)

    def test_withdrawal_restores_fact_without_losing_later_confirmations(self):
        first = self.feedback({"inventory_qty": 60})
        second = self.feedback({"inventory_qty": 50})
        self.store.revise_feedback(first, "withdrawn")
        self.assertEqual(self.store.risk(1)["inventory_qty"], 50)
        self.store.revise_feedback(second, "withdrawn")
        self.assertEqual(self.store.risk(1)["inventory_qty"], 120)
        self.assertEqual(self.store.risk(1)["investigation_status"], "pending")
        self.assertEqual(self.store.cases(), [])

    def test_bad_confirmed_observation_is_atomic_and_requires_evidence(self):
        inv = self.store.create_investigation(1)
        feedback = self.store.add_feedback(inv["id"], "库存核查", "2026-10-03T12:00:00+08:00", {})
        for confirmed in ({"observed_values": {"inventory_qty": 60}}, {"observed_values": {"inventory_qty": 60.001}, "evidence_ref": "manual"}, {"observed_values": {"unit_cost": "NaN"}, "evidence_ref": "manual"}, {"observed_values": [60], "evidence_ref": "manual"}):
            response = self.client.post(f"/api/v1/feedback/{feedback['id']}/confirm", json={"confirmed": confirmed})
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.store.risk(1)["current_fact_version"], 1)
        self.assertEqual(self.store.risk(1)["inventory_qty"], 120)

    def test_replan_failure_and_stale_failure_request_cannot_enable_old_plan(self):
        self.feedback({"inventory_qty": 10})
        response = self.client.post("/api/v1/risks/1/replan", json={"expected_version": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.proposal("PROP-AC10-001")["status"], "replan_pending")
        self.assertEqual(self.client.post("/api/v1/proposals/PROP-AC10-001/execute", json={"expected_version": 1}).status_code, 400)
        response = self.client.post("/api/v1/risks/1/replan", json={"expected_version": 2, "simulate_failure": True})
        self.assertEqual(response.status_code, 409)

    def test_export_download_keeps_original_version_after_edit(self):
        before = self.client.get("/api/v1/proposals/PROP-AC10-001/export?version=1")
        self.assertEqual(before.status_code, 200)
        self.assertIn("attachment", before.headers["content-disposition"])
        self.feedback({"inventory_qty": 60})
        self.store.replan(1, expected_version=1)
        after = self.client.get("/api/v1/proposals/PROP-AC10-001/export?version=1").json()
        self.assertEqual(after["payload"], before.json()["payload"])
        self.assertEqual(after["status"], "invalidated")
        self.assertFalse(after["external_write"])
        self.assertEqual(self.client.get("/api/v1/proposals/PROP-AC10-001/export?version=1", headers={"X-Tenant-Id": "other"}).status_code, 404)

    def test_real_work_items_and_manual_facts_reference_correct_imported_risk(self):
        self.upload()
        risk_id = self.client.get("/api/v1/risks").json()["items"][0]["id"]
        items = self.client.get("/api/v1/work-items").json()["items"]
        self.assertEqual([item["risk_id"] for item in items], [risk_id])
        self.assertIsNone(items[0]["owner"])
        overview = self.client.get("/api/v1/retail/overview").json()
        self.assertEqual(overview["stores"][0]["risk_items"][0]["risk_id"], risk_id)
        inv = self.store.create_investigation(risk_id)
        fb = self.store.add_feedback(inv["id"], "盘点确认", "2026-10-03T12:00:00+08:00", {})
        self.store.confirm_feedback(fb["id"], {"observed_values": {"inventory_qty": 90}, "evidence_ref": "count-sheet"})
        risk = self.client.get(f"/api/v1/risks/{risk_id}").json()["risk"]
        self.assertEqual(risk["inventory_qty"], 90)
        self.assertEqual(risk["source_inventory_qty"], 100)
        self.assertEqual(risk["current_fact_version"], 2)
        self.store.revise_feedback(fb["id"], "withdrawn")
        self.assertEqual(self.client.get(f"/api/v1/risks/{risk_id}").json()["risk"]["inventory_qty"], 100)

    def test_new_snapshot_invalidates_old_actions_and_reset_preserves_real_data(self):
        self.store.approve("PROP-AC10-001")
        imported = self.upload()
        proposal = self.store.proposal("PROP-AC10-001")
        self.assertEqual(proposal["status"], "needs_replan")
        self.assertEqual(self.store.rows("SELECT * FROM inventory_reservations"), [])
        self.assertEqual(self.client.post("/api/v1/proposals/PROP-AC10-001/execute", json={"expected_version": 1}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/workbenches/transfer?risk_id=1").status_code, 409)
        with patch.dict(os.environ, {"INVENTORY_AGENT_ALLOW_DEMO_RESET": "1", "INVENTORY_AGENT_MODE": "demo"}):
            self.assertEqual(self.client.post("/api/v1/demo/reset").status_code, 409)
        self.assertEqual(self.store.real_inventory_snapshot()["id"], imported["summary"]["snapshot_id"])
        self.assertEqual(self.store.risks()[0]["sku"], "NEW-SKU")

    def test_confirm_retry_rejects_changed_content_and_does_not_duplicate_facts(self):
        fb = self.feedback({"inventory_qty": 60})
        confirmed = {"observed_values": {"inventory_qty": 60}, "evidence_ref": "manual-count-001"}
        self.store.confirm_feedback(fb, confirmed)
        self.assertEqual(self.store.risk(1)["current_fact_version"], 2)
        response = self.client.post(f"/api/v1/feedback/{fb}/confirm", json={"confirmed": {**confirmed, "observed_values": {"inventory_qty": 50}}})
        self.assertEqual(response.status_code, 409)
