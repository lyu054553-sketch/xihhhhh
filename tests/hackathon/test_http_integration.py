"""S01 integration through the registered router and the four real services.

The empty model configuration is deliberate: Agent/material routes must return
their persisted unavailable/manual-review state without invoking a provider.
"""
from __future__ import annotations

import json
from base64 import b64encode
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.hackathon_routes import initialize_hackathon, router
from backend.model_config import ModelConfig
from backend.store import Store


TENANT = "integration-test"
BASE = "/api/v1/hackathon"


def one_pixel_png() -> bytes:
    # Minimal structurally valid PNG. CRC values are not interpreted by the
    # upload boundary; the material service checks signature and PNG chunks.
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" +
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00" +
            b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


class HackathonHttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.app = FastAPI()
        cls.app.state.store = cls.store
        cls.app.state.model_config = ModelConfig(text_provider="", vision_provider="", providers={})
        cls.app.include_router(router)
        initialize_hackathon(cls.app, demo_tenant=TENANT)
        cls.client = TestClient(cls.app)
        cls.headers = {"X-Tenant-Id": TENANT}

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def test_s01_decision_execution_followup_and_safe_ai_routes(self):
        response = self.client.get(BASE + "/context", params={"scenario_id": "S01", "branch_id": "transfer_80"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        context = response.json()["context"]
        self.assertEqual(context["tenant_id"], TENANT)

        facts_response = self.client.post(BASE + "/facts/query", json={"context": context}, headers=self.headers)
        self.assertEqual(facts_response.status_code, 200, facts_response.text)
        facts = facts_response.json()
        target = facts["reference_data"]["target"]
        self.assertIn("people", facts["reference_data"]["tables"])

        risks_response = self.client.post(BASE + "/risks/assess", json={"context": context}, headers=self.headers)
        self.assertEqual(risks_response.status_code, 200, risks_response.text)
        risk = next(item for item in risks_response.json()["items"]
                    if all(item[key] == target[key] for key in ("store_id", "sku_id", "lot_id")))
        compare_request = {
            "context": context,
            "risk_keys": [risk["risk_key"]],
            "objective": "核验 S01 调拨主线",
            "horizon_start": context["as_of"][:10],
            "horizon_end": "2026-10-25",
            "business_inputs": {"transfer": {
                "origin_store_id": target["store_id"], "target_store_id": "ST-002",
                "sku_id": target["sku_id"], "lot_id": target["lot_id"],
                "quantity": 80, "base_unit": "盒", "sales_settlement_days": 0,
            }},
        }
        comparison_response = self.client.post(BASE + "/proposals/compare", json=compare_request, headers=self.headers)
        self.assertEqual(comparison_response.status_code, 200, comparison_response.text)
        comparison = comparison_response.json()
        candidate = next(item for item in comparison["candidates"] if item["action_type"] == "transfer" and item["feasible"])
        self.assertTrue(candidate["inventory_changes"])
        self.assertTrue({"quantity_before", "quantity_after", "quantity_delta", "base_unit"} <= candidate["inventory_changes"][0].keys())
        source_change = next(item for item in candidate["inventory_changes"] if item["store_id"] == "ST-001")
        target_change = next(item for item in candidate["inventory_changes"] if item["store_id"] == "ST-002")
        self.assertEqual((source_change["quantity_before"], source_change["quantity_after"]), (120, 40))
        self.assertEqual((target_change["quantity_before"], target_change["quantity_after"]), (0, 80))

        save_response = self.client.post(BASE + "/proposals", json={
            **compare_request,
            "comparison_id": comparison["comparison_id"],
            "candidate_id": candidate["candidate_id"],
            "expected_current_proposal_version": 0,
            "actor_id": "P-001",
        }, headers={**self.headers, "Idempotency-Key": "integration-save-s01"})
        self.assertEqual(save_response.status_code, 200, save_response.text)
        saved = save_response.json()
        pending_response = self.client.get(BASE + "/proposals", params={
            "scenario_id": "S01", "branch_id": "transfer_80", "status": "pending_approval",
        }, headers=self.headers)
        self.assertEqual(pending_response.status_code, 200, pending_response.text)
        self.assertEqual(pending_response.json()["proposals"][0]["proposal_id"], saved["proposal_id"])
        overview = self.client.get(BASE + "/overview", params={"scenario_id": "S01", "branch_id": "transfer_80"}, headers=self.headers)
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(overview.json()["overview"]["pending_approvals"]["count"], 1)
        self.assertIn("purchase_commitments", overview.json()["overview"])

        assignments = [{"action_line_id": line["action_line_id"], "assignee_id": "P-003",
                        "due_at": "2026-10-25T18:00:00+08:00"} for line in saved["action_lines"]]
        confirmation = {
            "expected_proposal_version": saved["proposal_version"],
            "expected_fact_version": saved["fact_version"],
            "expected_snapshot_id": saved["snapshot_id"],
            "actor_id": "P-001", "candidate_id": candidate["candidate_id"],
            "task_assignments": assignments,
        }
        confirm_headers = {**self.headers, "Idempotency-Key": "integration-confirm-s01"}
        confirm_response = self.client.post(f"{BASE}/proposals/{saved['proposal_id']}/confirm", json=confirmation, headers=confirm_headers)
        self.assertEqual(confirm_response.status_code, 200, confirm_response.text)
        confirmed = confirm_response.json()
        self.assertEqual(len(confirmed["tasks"]), 1)
        self.assertEqual(confirmed["context"]["fact_version"], context["fact_version"] + 1)
        replay_confirm = self.client.post(f"{BASE}/proposals/{saved['proposal_id']}/confirm", json=confirmation, headers=confirm_headers)
        self.assertEqual(replay_confirm.status_code, 200, replay_confirm.text)
        self.assertTrue(replay_confirm.json()["idempotent_replay"])

        task_id = confirmed["tasks"][0]["task_id"]
        task_detail = self.client.get(f"{BASE}/tasks/{task_id}", headers=self.headers)
        self.assertEqual(task_detail.status_code, 200, task_detail.text)
        self.assertEqual(task_detail.json()["task"]["task_id"], task_id)
        tasks = self.client.get(BASE + "/tasks", params={"scenario_id": "S01", "branch_id": "transfer_80"}, headers=self.headers)
        self.assertEqual(tasks.status_code, 200, tasks.text)
        self.assertEqual(tasks.json()["tasks"][0]["task_id"], task_id)

        replay_response = self.client.post(BASE + "/replays/advance", json={
            "scenario_id": "S01", "branch_id": "transfer_80", "as_of": "2026-10-25T23:59:00+08:00",
            "expected_fact_version": confirmed["context"]["fact_version"],
            "proposal_id": saved["proposal_id"], "proposal_version": saved["proposal_version"], "actor_id": "P-001",
        }, headers={**self.headers, "Idempotency-Key": "integration-replay-s01"})
        self.assertEqual(replay_response.status_code, 200, replay_response.text)
        replay_case = replay_response.json()["accounting"]["case_results"][0]
        self.assertTrue(replay_case["is_demo"])
        self.assertFalse(replay_case["external_write"])
        accounting = self.client.get(BASE + "/accounting", params={
            "scenario_id": "S01", "branch_id": "transfer_80", "task_id": task_id,
        }, headers=self.headers)
        self.assertEqual(accounting.status_code, 200, accounting.text)
        self.assertEqual(accounting.json()["actual_cash_in_cny"], 6400)
        self.assertTrue(accounting.json()["is_demo"])
        self.assertFalse(accounting.json()["external_write"])

        # Exercise the AI module through the registered endpoints with an
        # intentionally empty provider config: no network or paid model call.
        current = replay_response.json()["context"]
        run_response = self.client.post(BASE + "/agent-runs", json={
            "context": current, "actor_id": "P-001", "goal": "读取当前库存并给出确定性比较",
            "feedback_material_ids": [],
        }, headers={**self.headers, "Idempotency-Key": "integration-agent-s01"})
        self.assertEqual(run_response.status_code, 200, run_response.text)
        self.assertEqual(run_response.json()["status"], "unavailable")
        run_id = run_response.json()["run_id"]
        run_read = self.client.get(f"{BASE}/agent-runs/{run_id}", headers=self.headers)
        self.assertEqual(run_read.status_code, 200, run_read.text)
        self.assertEqual(run_read.json()["run_id"], run_id)

        image = one_pixel_png()
        upload_response = self.client.post(BASE + "/materials/extract", data={
            "context": json.dumps(current), "actor_id": "P-001", "kind": "return_terms",
            "text": "", "source_name": "terms.png",
        }, files={"file": ("terms.png", image, "image/png")}, headers={
            **self.headers, "Idempotency-Key": "integration-image-s01",
        })
        self.assertEqual(upload_response.status_code, 200, upload_response.text)
        draft = upload_response.json()
        self.assertEqual(draft["source"], "manager_image")
        self.assertEqual(draft["status"], "failed")
        self.assertEqual(draft["context"]["fact_version"], current["fact_version"])
        self.assertFalse(draft["external_write"])
        image_response = self.client.get(f"{BASE}/materials/{draft['material_id']}/image", headers=self.headers)
        self.assertEqual(image_response.status_code, 200, image_response.text)
        self.assertEqual(image_response.content, image)

    def test_explicit_hackathon_write_requires_idempotency(self):
        response = self.client.post(BASE + "/agent-runs", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "idempotency_key_required")

    def test_s05_s06_s07_public_business_inputs_preserve_constraints(self):
        def compare(scenario_id, branch_id, horizon_end, business_inputs):
            context_response = self.client.get(BASE + "/context", params={
                "scenario_id": scenario_id, "branch_id": branch_id,
            }, headers=self.headers)
            self.assertEqual(context_response.status_code, 200, context_response.text)
            context = context_response.json()["context"]
            response = self.client.post(BASE + "/proposals/compare", json={
                "context": context, "risk_keys": [], "objective": "验证公共动作输入",
                "horizon_start": context["as_of"][:10], "horizon_end": horizon_end,
                "assumption_ids": [], "business_inputs": business_inputs,
            }, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        purchase = compare("S07", "reduce_to_60", "2026-10-17", {
            "procurement": {"intent_id": "INTENT-S07-001", "new_payment_date": "2026-10-25"},
        })
        purchase_candidate = next(row for row in purchase["candidates"] if row["action_type"] == "procurement")
        self.assertTrue(purchase_candidate["feasible"], purchase_candidate["exclusion_reasons"])
        self.assertEqual(purchase_candidate["quantity"], 60)
        self.assertEqual(purchase_candidate["calculation"]["quantity_payment_reduction_cny"], 1600)
        self.assertIsNone(purchase_candidate["calculation"]["actual_cash_in_cny"])

        promotion = compare("S06", "promotion", "2026-10-13", {
            "promotion": {
                "promotion_id": "PROMO-S06", "sales_settlement_days": 0,
                "price_stages": [
                    {"stage_id": "PROMO-S06-1", "price_cny": 11},
                    {"stage_id": "PROMO-S06-2", "price_cny": 10},
                ],
                "products": [
                    {"sku_id": "SKU-004", "quantity_per_bundle": 1, "base_unit": "袋"},
                    {"sku_id": "SKU-008", "quantity_per_bundle": 1, "base_unit": "瓶"},
                ],
            },
        })
        promotion_candidate = next(row for row in promotion["candidates"] if row["action_type"] == "promotion")
        self.assertTrue(promotion_candidate["feasible"], promotion_candidate["missing_fields"])
        self.assertEqual(promotion_candidate["calculation"]["expected_cash_in_cny"], 420)
        self.assertEqual(len(promotion_candidate["calculation"]["quantity_lines"]), 2)

        returned = compare("S05", "cash_refund", "2026-10-18", {
            "return": {"supplier_id": "SUP-002", "sku_id": "SKU-011", "lot_id": "SCLOT-S05",
                       "quantity": 100, "base_unit": "桶", "settlement_method": "refund", "fee_cny": 0},
        })
        return_candidate = next(row for row in returned["candidates"] if row["action_type"] == "return")
        self.assertFalse(return_candidate["feasible"])
        self.assertIn("supplier_confirmed", return_candidate["missing_fields"])
        self.assertIn("acceptance_date", return_candidate["missing_fields"])
        self.assertIsNone(return_candidate["calculation"]["expected_cash_in_cny"])


if __name__ == "__main__":
    unittest.main()
