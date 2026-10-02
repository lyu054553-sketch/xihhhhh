"""零售经营账本、采购情景与真实数据隔离的回归。"""
import os
import json
from datetime import date
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import api
from backend.retail import demo_dataset, demo_overview, simulate_purchase
from backend.store import Store


class RetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp.close()
        self.store = Store(self.temp.name)
        self.store.seed_demo()
        self.dataset = demo_dataset(self.store.risks(), api.TRANSFER_NETWORK_STORES)
        self.client = TestClient(api.app)
        self.store_patch = patch.object(api, "store", self.store)
        self.store_patch.start()
        self.mode_patch = patch.dict(os.environ, {"INVENTORY_AGENT_MODE": "demo"})
        self.mode_patch.start()

    def tearDown(self):
        self.mode_patch.stop()
        self.store_patch.stop()
        self.store.close()
        Path(self.temp.name).unlink(missing_ok=True)

    def test_demo_dates_align_with_snapshot_without_changing_saved_drafts(self):
        snapshot = self.store.one("SELECT metadata_json FROM snapshots WHERE id='snapshot-demo-v1'")
        as_of = date.fromisoformat(json.loads(snapshot["metadata_json"])["as_of_date"])
        self.assertEqual(as_of, date(2026, 10, 3))
        for risk_id in (3, 6, 7, 8, 9, 10, 11):
            item = self.store.default_workbench_input("expiry-rescue", risk_id)
            self.assertEqual((date.fromisoformat(item["batch"]) - as_of).days, item["sellable_days"])
            self.assertGreater(date.fromisoformat(item["latest_disposal_date"]), as_of)
        procurement = self.store.default_workbench_input("procurement-brake", 4)
        self.assertEqual(procurement["arrival_date"], "2026-10-09")
        self.assertEqual((date.fromisoformat(procurement["new_payment_date"]) - date.fromisoformat(procurement["payment_date"])).days, 30)
        persisted = dict(procurement, arrival_date="2026-09-24", payment_date="2026-09-28")
        self.store.mark_workbench_dirty("procurement-brake", 4, persisted)
        self.store.seed_demo()
        self.assertEqual(self.store.workbench_draft("procurement-brake", 4)["input"], persisted)

    def test_replenishment_targets_vary_by_category_and_store(self):
        normal = [row for row in self.dataset["rows"] if not row["risk_tags"]]
        self.assertEqual({row["target_days"] for row in normal}, {7, 8, 9, 10})
        self.assertEqual({row["safety_days"] for row in normal}, {5})
        result = simulate_purchase(self.dataset, 14, 20)
        self.assertEqual(result["metrics"]["stockout_risk_count"]["baseline"], 0)
        self.assertGreater(result["metrics"]["stockout_risk_count"]["scenario"], 0)
        self.assertLess(result["metrics"]["stockout_risk_count"]["scenario"], len(normal))
        # 充分补足目标库存；每行结果仍由原始库存、在途、需求和实际整件采购构成。
        for line in result["lines"]:
            self.assertGreaterEqual(line["baseline_ending_qty"] + 0.01, line["daily_demand"] * line["target_days"])

    def test_zero_reduction_and_weekly_totals_conserve_money(self):
        result = simulate_purchase(self.dataset, 14, 0)
        for metric in result["metrics"].values():
            self.assertEqual(metric["baseline"], metric["scenario"])
            self.assertEqual(metric["delta"], 0)
        for key in ("baseline", "scenario"):
            series_total = sum(Decimal(str(row[key])) for row in result["weekly"])
            self.assertEqual(series_total, Decimal(str(result["metrics"]["purchase_outflow"][key])))

    def test_reduction_scoped_deterministic_read_only_and_risk_sensitive(self):
        changes_before = self.store.conn.total_changes
        result = simulate_purchase(self.dataset, 14, 20, "STORE-001", "膨化零食")
        self.assertEqual(result, simulate_purchase(self.dataset, 14, 20, "STORE-001", "膨化零食"))
        self.assertEqual(len(result["lines"]), 1)
        self.assertLess(result["metrics"]["purchase_outflow"]["delta"], 0)
        self.assertGreaterEqual(result["metrics"]["stockout_risk_count"]["delta"], 0)
        self.assertNotIn("estimated_net_cash_improvement", result)
        self.assertEqual(self.store.conn.total_changes, changes_before)
        extreme = simulate_purchase(self.dataset, 30, 100, "STORE-001", "膨化零食")
        self.assertEqual(extreme["metrics"]["purchase_outflow"]["scenario"], 0)
        self.assertGreater(extreme["risks"][0]["shortage_qty"], 0)

    def test_account_balance_reconciles_without_inventory_cost(self):
        result = demo_overview(self.dataset, 30, "all")
        account = result["account"]
        self.assertAlmostEqual(account["opening_balance"] + account["cash_in"] - account["cash_out"], account["balance"], places=2)
        self.assertEqual(len(result["stores"]), 50)
        self.assertEqual(len(result["trend"]), 30)
        self.assertAlmostEqual(sum(row["inventory_cost"] for row in result["stores"]), result["inventory"]["cost"], places=2)
        shorter = demo_overview(self.dataset, 7, "all")
        self.assertEqual(shorter["trend"], result["trend"][-7:])
        self.assertEqual(shorter["account"]["balance"], account["balance"])

    def test_api_rejects_bad_scope_percent_and_horizon(self):
        for data in [{"reduction_pct": -1}, {"reduction_pct": 101}, {"horizon_days": 0}, {"horizon_days": 91}, {"horizon_days": 1.2}, {"store_id": "not-a-store"}, {"category": "not-a-category"}]:
            self.assertEqual(self.client.post("/api/v1/retail/simulate", json=data).status_code, 422, data)
        self.assertEqual(self.client.get("/api/v1/retail/overview?period=5").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/retail/overview?store_id=unknown").status_code, 422)

    def test_real_snapshot_never_gets_demo_cash_or_simulation(self):
        self.store.conn.execute("INSERT INTO real_inventory_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("real-1", "demo", "customer.csv", "2026-10-01", "2026-10-01T00:00:00", 1, 1, 1, "100", "100", '{"teacher_baseline_missing_fields":["sales_30"]}'))
        self.store.conn.execute("INSERT INTO real_inventory_lines(snapshot_id, tenant_id, org_code, org_name, sku, product_name, inventory_qty, available_qty, cost_amount) VALUES(?,?,?,?,?,?,?,?,?)", ("real-1", "demo", "R001", "真实门店", "R-SKU", "用户商品", 10, 10, 100))
        self.store.conn.commit()
        before = self.store.conn.total_changes
        self.store.seed_demo()
        self.assertEqual(before, self.store.conn.total_changes)
        result = self.client.get("/api/v1/retail/overview").json()
        self.assertFalse(result["is_demo"])
        self.assertIsNone(result["account"]["balance"])
        self.assertIsNone(result["sales"]["amount"])
        self.assertEqual(result["inventory"]["cost"], 100)
        self.assertIsNone(result["inventory"]["risk_cost"])
        self.assertEqual(result["trend"], [])
        simulation = self.client.post("/api/v1/retail/simulate", json={}).json()
        self.assertEqual(simulation["status"], "unavailable")
        self.assertIsNone(simulation["metrics"])
        self.assertFalse(simulation["is_demo"])

    def test_real_mode_without_snapshot_and_other_tenants_have_no_demo(self):
        with patch.dict(os.environ, {"INVENTORY_AGENT_MODE": "real"}):
            result = self.client.get("/api/v1/retail/overview").json()
            self.assertFalse(result["is_demo"])
            self.assertIsNone(result["account"]["balance"])
        options = self.client.get("/api/v1/retail/simulation-options", headers={"X-Tenant-Id": "other"}).json()
        self.assertEqual(options["stores"], [])
        self.assertFalse(options["is_demo"])

    def test_seed_migrates_only_known_sample_names_and_preserves_facts(self):
        self.store.conn.execute("UPDATE risks SET product='钙维生素D软胶囊' WHERE id=1")
        self.store.conn.execute("UPDATE risks SET product='用户自定义商品' WHERE id=2")
        self.store.conn.commit()
        self.store.seed_demo()
        self.assertEqual(self.store.risk(1)["product"], "每日坚果礼盒 750g")
        self.assertEqual(self.store.risk(1)["inventory_qty"], 120)
        self.assertEqual(self.store.risk(2)["product"], "用户自定义商品")


if __name__ == "__main__":
    unittest.main()
