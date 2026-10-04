"""HTTP/version, transactional rollback and allocation regressions."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import api
from backend.errors import BusinessConflict
from backend.store import Store


class StateSafetyTests(unittest.TestCase):
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

    def save(self, quantity, target="STORE-002"):
        current = self.store.workbench_draft("transfer", 1)
        previous = self.store.one("SELECT current_version FROM proposals WHERE risk_id=1 ORDER BY created_at DESC LIMIT 1")
        response = self.client.post("/api/v1/workbenches/transfer/save", json={
            "expected_version": current["version"] if current else 0,
            "expected_proposal_version": previous["current_version"] if previous else 0,
            "input": {"risk_id": 1, "quantity": quantity, "target_store_id": target},
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_transfer_read_normalizes_legacy_string_quantity(self):
        data = self.store.default_workbench_input("transfer", 1)
        data["quantity"] = "40"
        self.store.save_workbench_draft("transfer", 1, data, None, "needs_recalculation")

        response = self.client.get("/api/v1/workbenches/transfer?risk_id=1")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["input"]["quantity"], 40)
        self.assertIs(type(response.json()["input"]["quantity"]), int)

    def submit(self, proposal):
        response = self.client.post(f"/api/v1/proposals/{proposal['id']}/submit", json={"expected_version": proposal["current_version"]})
        self.assertEqual(response.status_code, 200, response.text)

    def approve(self, proposal, key=None):
        return self.client.post(f"/api/v1/proposals/{proposal['id']}/approve", json={"expected_version": proposal["current_version"]}, headers={"Idempotency-Key": key} if key else {})

    def test_missing_or_stale_version_cannot_approve_new_content(self):
        old = self.save(20)["proposal"]
        self.submit(old)
        new = self.save(30)["proposal"]
        self.submit(new)
        self.assertEqual(self.client.post(f"/api/v1/proposals/{old['id']}/approve").status_code, 422)
        response = self.approve(old)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["current_version"], new["current_version"])
        self.assertEqual(self.store.rows("SELECT * FROM approvals"), [])

    def test_two_writers_same_version_only_one_saves(self):
        initial = self.save(20)
        barrier = threading.Barrier(8)
        def save(i):
            barrier.wait(timeout=10)
            return self.client.post("/api/v1/workbenches/transfer/save", json={"expected_version": initial["draft"]["version"], "expected_proposal_version": initial["proposal"]["current_version"], "input": {"risk_id": 1, "quantity": 21+i}}).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(save, range(8)))
        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(409), 7)

    def test_conflicting_proposal_version_rolls_back_draft_change(self):
        initial = self.save(20)
        response = self.client.post("/api/v1/workbenches/transfer/save", json={"expected_version": initial["draft"]["version"], "expected_proposal_version": 1, "input": {"risk_id": 1, "quantity": 30}})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.workbench_draft("transfer", 1), initial["draft"])

    def test_approval_and_audit_are_atomic(self):
        with patch.object(self.store, "audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.store.approve("PROP-AC10-001")
        self.assertEqual(self.store.proposal("PROP-AC10-001")["status"], "pending_approval")
        self.assertEqual(self.store.rows("SELECT * FROM approvals"), [])
        self.assertEqual(self.store.rows("SELECT * FROM inventory_reservations"), [])

    def test_shared_inventory_and_receiving_capacity_are_reserved(self):
        first = self.save(50)["proposal"]
        self.submit(first)
        self.assertEqual(self.approve(first).status_code, 200)
        task = self.client.post(f"/api/v1/proposals/{first['id']}/execute", json={"expected_version": first["current_version"]})
        self.assertEqual(task.status_code, 200)
        second = self.save(50, "STORE-005")["proposal"]
        self.submit(second)
        self.assertEqual(self.approve(second).status_code, 409)
        self.assertEqual(len(self.store.execution_tasks()), 1)

    def test_execute_rechecks_current_inventory(self):
        self.store.approve("PROP-AC10-001")
        self.store.conn.execute("UPDATE risks SET inventory_qty=50 WHERE id=1")
        self.store.conn.commit()
        with self.assertRaises(BusinessConflict):
            self.store.execute("PROP-AC10-001")
        self.assertEqual(self.store.execution_tasks(), [])

    def test_idempotency_key_cannot_be_reused_on_new_version(self):
        first = self.save(20)["proposal"]
        self.submit(first)
        self.assertEqual(self.approve(first, "same").status_code, 200)
        second = self.save(25)["proposal"]
        self.submit(second)
        response = self.approve(second, "same")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "idempotency_conflict")

    def test_separate_connections_cannot_race_approval(self):
        other = Store(self.database)
        barrier = threading.Barrier(2)
        def approve(store):
            barrier.wait(timeout=10)
            return store.approve("PROP-AC10-001", idem="cross-connection")["id"]
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(approve, (self.store, other)))
            self.assertEqual(results[0], results[1])
            self.assertEqual(len(self.store.rows("SELECT * FROM approvals")), 1)
        finally:
            other.close()

    def test_concurrent_calculate_reports_conflicts_instead_of_500(self):
        barrier = threading.Barrier(16)
        def calculate(i):
            barrier.wait(timeout=10)
            return self.client.post("/api/v1/workbenches/transfer/calculate", json={"expected_version": 0, "input": {"risk_id": 1, "quantity": 20+i}}).status_code
        with ThreadPoolExecutor(max_workers=16) as pool:
            statuses = list(pool.map(calculate, range(16)))
        self.assertEqual(statuses.count(200), 1)
        self.assertEqual(statuses.count(409), 15)

    def test_manual_receipt_cash_is_numeric_and_survives_restart(self):
        self.store.approve("PROP-AC10-001")
        task = self.store.execute("PROP-AC10-001")
        response = self.client.post(f"/api/v1/execution-tasks/{task['id']}/status", json={"expected_version": 1, "status": "completed", "receipt_ref": "manual-123", "actual_cash": 1400, "confirmation_method": "manual"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["metadata"]["actual_cash"], 1400)
        self.assertEqual(response.json()["metadata"]["confirmation_method"], "manual")
        reopened = Store(self.database)
        try:
            self.assertEqual(reopened.execution_tasks()[0]["metadata"]["actual_cash"], 1400)
        finally:
            reopened.close()
        stale = self.client.post(f"/api/v1/execution-tasks/{task['id']}/status", json={"expected_version": 1, "status": "pending_dispatch"})
        self.assertEqual(stale.status_code, 409)

    def test_readonly_facts_and_unknown_cost_cannot_be_forged(self):
        response = self.client.post("/api/v1/workbenches/transfer/calculate", json={"expected_version": 0, "input": {"risk_id": 1, "source_on_hand": 10000}})
        self.assertEqual(response.status_code, 400)
        self.store.conn.execute("UPDATE risks SET unit_cost=NULL WHERE id=1")
        self.store.conn.commit()
        response = self.client.post("/api/v1/workbenches/transfer/calculate", json={"expected_version": 0, "input": {"risk_id": 1}})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.workbench_draft("transfer", 1), None)

    def test_amount_contract_uses_numbers_both_live_and_saved(self):
        saved = self.save(40)
        for amount in (saved["calculation"]["cash"]["inventory_cost"], saved["proposal"]["version"]["payload"]["calculation"]["cash"]["inventory_cost"]):
            self.assertIsInstance(amount, (int, float))
        for field in ("unit_cost", "transport_fee"):
            self.assertIsInstance(saved["draft"]["input"][field], (int, float))

    def test_withdrawn_feedback_removes_its_case(self):
        investigation = self.store.create_investigation(1)
        feedback = self.store.add_feedback(investigation["id"], "需核查价格", "2026-10-03T10:00:00+08:00", {})
        self.store.confirm_feedback(feedback["id"], {"factor": "价格高"})
        self.assertEqual(len(self.store.cases()), 1)
        # A pre-upgrade derived case lacks its feedback_id; still retire it using
        # the preserved source text and confirmed content.
        self.store.conn.execute("UPDATE cases SET content_json=json_remove(content_json,'$.feedback_id')")
        self.store.conn.commit()
        self.store.revise_feedback(feedback["id"], "withdrawn")
        self.assertEqual(self.store.cases(), [])

    def test_feedback_draft_does_not_invent_factors_without_model(self):
        inv = self.client.post("/api/v1/risks/1/investigations", json={}).json()
        feedback = self.client.post(f"/api/v1/investigations/{inv['id']}/feedback", json={"raw_text": "价格太高，正常上架"}).json()
        self.assertEqual(feedback["draft"]["factors"], [])
        self.assertEqual(feedback["draft"]["current_status"], "unknown")
        self.assertEqual(feedback["draft"]["extraction_status"], "manual_required")

    def test_static_root_does_not_serve_database_or_source(self):
        for path in ("/backend/api.py", "/inventory_cash_agent.db", "/.git/config", "/.env", "/output/test.zip"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/app.js").status_code, 200)
        self.assertNotIn("database", self.client.get("/api/v1/health").json())

    def test_reset_disabled_and_opt_in_does_not_delete_other_tenant(self):
        self.store.add_case({"note": "keep"}, None, tenant_id="other")
        with patch.dict(os.environ, {"INVENTORY_AGENT_ALLOW_DEMO_RESET": "0", "INVENTORY_AGENT_MODE": "demo"}):
            self.assertEqual(self.client.post("/api/v1/demo/reset").status_code, 403)
        with patch.dict(os.environ, {"INVENTORY_AGENT_ALLOW_DEMO_RESET": "1", "INVENTORY_AGENT_MODE": "demo"}):
            self.assertEqual(self.client.post("/api/v1/demo/reset").status_code, 200)
        self.assertEqual(len(self.store.cases("other")), 1)

    def test_legacy_execution_still_consumes_inventory_without_reservation_rows(self):
        first = self.save(50)["proposal"]
        self.submit(first)
        self.assertEqual(self.approve(first).status_code, 200)
        self.store.execute(first["id"])
        self.store.conn.execute("DELETE FROM inventory_reservations")
        self.store.conn.commit()
        second = self.save(50, "STORE-005")["proposal"]
        self.submit(second)
        self.assertEqual(self.approve(second).status_code, 409)
        self.assertEqual(len(self.store.execution_tasks()), 1)

    def test_terminal_receipt_cannot_be_overwritten_and_amount_rounds_to_cents(self):
        self.store.approve("PROP-AC10-001")
        task = self.store.execute("PROP-AC10-001")
        path = f"/api/v1/execution-tasks/{task['id']}/status"
        self.assertEqual(self.client.post(path, json={"expected_version": 1, "status": "in_transit"}).status_code, 409)
        self.assertEqual(self.client.post(path, json={"expected_version": 1, "status": "pending_dispatch", "actual_cash": 1}).status_code, 400)
        completed = self.client.post(path, json={"expected_version": 1, "status": "completed", "receipt_ref": "manual", "actual_cash": 1400.001}).json()
        self.assertEqual(completed["metadata"]["actual_cash"], 1400)
        for status, amount in (("completed", 1500), ("in_transit", 1400)):
            self.assertEqual(self.client.post(path, json={"expected_version": 2, "status": status, "receipt_ref": "manual", "actual_cash": amount}).status_code, 409)
        replay = self.client.post(path, json={"expected_version": 2, "status": "completed", "receipt_ref": "manual", "actual_cash": 1400}).json()
        self.assertEqual(replay["version"], 2)

    def test_additive_migration_preserves_existing_execution_and_is_repeatable(self):
        self.store.approve("PROP-AC10-001")
        task = self.store.execute("PROP-AC10-001")
        self.store.conn.execute("ALTER TABLE execution_tasks DROP COLUMN version")
        self.store.conn.commit()
        for _ in range(2):
            reopened = Store(self.database)
            try:
                restored = reopened.execution_tasks()[0]
                self.assertEqual(restored["id"], task["id"])
                self.assertEqual(restored["version"], 1)
                self.assertEqual(restored["metadata"]["external_write"], False)
            finally:
                reopened.close()

    def test_multiple_expiry_plans_keep_room_for_normal_sales_once(self):
        def save():
            draft = self.store.workbench_draft("expiry-rescue", 3)
            prior = self.store.risk(3)
            return self.store.save_workbench("expiry-rescue", 3, {}, draft["version"] if draft else 0, prior["proposal_version"] or 0)["proposal"]
        first = save()
        self.store.submit_proposal(first["id"])
        self.store.approve(first["id"])
        self.store.execute(first["id"])
        second = save()
        self.store.submit_proposal(second["id"])
        with self.assertRaises(BusinessConflict):
            self.store.approve(second["id"])
