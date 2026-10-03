"""Read the shipped workbooks without importing answers or mutating BASE."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.hackathon_data import loader as scenario_data
from backend.hackathon_data.loader import load_scenario, load_replay, list_scenarios


class ScenarioDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_scenario("S01")

    def inventory(self, data, store, sku, state="on_hand"):
        return next(row for row in data["tables"]["inventory"]
                    if row["store_id"] == store and row["sku_id"] == sku and row["stock_state"] == state)

    def test_real_workbooks_normalize_dates_and_keep_complete_store_scope(self):
        data = self.base
        self.assertEqual(len(data["tables"]["stores"]), 50)
        self.assertEqual(sum(row["include_in_summary"] for row in data["tables"]["stores"]), 6)
        self.assertEqual(len(data["tables"]["sales_daily"]), 6480)
        self.assertEqual(data["tables"]["products"][0]["base_unit"], "盒")
        self.assertEqual(self.inventory(data, "ST-001", "SKU-001")["quantity"], 120)
        self.assertEqual(self.inventory(data, "ST-002", "SKU-001")["quantity"], 10)
        self.assertEqual(data["tables"]["lots"][0]["expiry_date"], "2027-06-01")

    def test_catalog_reports_branch_mapping_and_missing_declared_test_branch(self):
        catalog = {row["scenario_id"]: row for row in list_scenarios()["items"]}
        self.assertEqual(catalog["S02"]["branch_aliases"], {"risk_overlap": "overlap"})
        self.assertIn("only_slow", catalog["S10"]["branches"])
        result = load_scenario("S02", "risk_overlap")
        self.assertEqual(result["branch_id"], "overlap")
        self.assertTrue(result["warnings"])

    def test_independent_risk_never_fills_missing_sales_from_base(self):
        result = load_scenario("S10", "missing_sales")
        self.assertIsNone(result["tables"]["risk_inputs"][0]["sales_30"])
        self.assertEqual(result["tables"]["sales_daily"], [])
        self.assertEqual(result["tables"]["demand_forecasts"], [])
        self.assertEqual(len(result["tables"]["inventory"]), 1)
        self.assertEqual(result["tables"]["lots"][0]["sku_id"], result["target"]["sku_id"])
        self.assertIsNone(result["tables"]["lots"][0]["expiry_date"])

    def test_scenario_overrides_are_isolated_and_keep_paid_inbound_distinct(self):
        result = load_scenario("S07")
        self.assertEqual(self.inventory(result, "ST-004", "SKU-003")["quantity"], 120)
        inbound = self.inventory(result, "ST-004", "SKU-003", "in_transit")
        self.assertEqual(inbound["quantity"], 30)
        shipment = next(row for row in result["tables"]["in_transit"] if row["shipment_line_id"] == inbound["shipment_line_id"])
        self.assertEqual(shipment["shipped_qty"], 30)
        self.assertEqual(result["tables"]["procurement_policy"][0]["min_order_qty"], 10)
        self.assertEqual(result["tables"]["transfer_policy"][0]["available_alternative_transfer_qty"], 0)
        demand = next(row for row in result["tables"]["demand_forecasts"]
                      if row["store_id"] == "ST-004" and row["sku_id"] == "SKU-003" and row["date"] == "2026-10-03")
        self.assertEqual(demand["demand_base"], 10)
        self.assertIsNone(demand["demand_low"])
        self.assertIsNone(demand["demand_high"])
        self.assertNotEqual(self.inventory(self.base, "ST-004", "SKU-003")["quantity"], 120)
        result["tables"]["inventory"][0]["quantity"] = 999
        self.assertEqual(load_scenario("S01")["tables"]["inventory"][0]["quantity"], 120)

    def test_return_snapshot_and_credit_payable_do_not_leak_to_other_branch(self):
        cash = load_scenario("S05", "cash_refund")
        credit = load_scenario("S05", "payable_credit")
        stock = self.inventory(cash, "ST-003", "SKU-011")
        self.assertEqual((stock["quantity"], stock["unit_cost"], stock["lot_id"]), (100, 10, "SCLOT-S05"))
        self.assertNotIn("AP-S05-001", {row["payable_id"] for row in cash["tables"]["payables"]})
        self.assertIn("AP-S05-001", {row["payable_id"] for row in credit["tables"]["payables"]})

    def test_feedback_requires_both_confirmation_and_known_clock(self):
        early = load_scenario("S08", "closed_target")
        with self.assertRaises(ValueError):
            load_scenario("S08", "closed_target", confirmed_override_ids=["OV-011"])
        later = load_scenario("S08", "closed_target", clock_at="2026-10-03T10:05:00+08:00")
        self.assertEqual(len(later["pending_overrides"]), 2)
        confirmed = load_scenario("S08", "closed_target", clock_at=later["clock_at"], confirmed_override_ids=["OV-011", "OV-012"])
        day = lambda value: next(row for row in value["tables"]["store_calendar"] if row["store_id"] == "ST-002" and row["date"] == "2026-10-04")
        self.assertTrue(day(early)["is_open"])
        self.assertTrue(day(later)["is_open"])
        self.assertFalse(day(confirmed)["is_open"])
        self.assertFalse(day(confirmed)["can_receive"])
        self.assertNotEqual(later["snapshot_id"], confirmed["snapshot_id"])
        self.assertNotIn("MAT-FEEDBACK-001", {row["material_id"] for row in later["tables"]["materials"]})
        unlisted = load_scenario("S08", "unlisted")
        self.assertIn("MAT-FEEDBACK-001", {row["material_id"] for row in unlisted["tables"]["materials"]})

    def test_future_actual_lots_and_unrelated_materials_are_not_visible(self):
        early = load_scenario("S07")
        self.assertNotIn("SCLOT-S07-NEW", {row["lot_id"] for row in early["tables"]["lots"]})
        later = load_scenario("S07", clock_at="2026-10-05T12:00:00+08:00")
        self.assertIn("SCLOT-S07-NEW", {row["lot_id"] for row in later["tables"]["lots"]})
        self.assertNotIn("MAT-FEEDBACK-001", {row["material_id"] for row in self.base["tables"]["materials"]})
        self.assertNotIn("MAT-RETURN-PO", {row["material_id"] for row in self.base["tables"]["materials"]})
        self.assertNotIn("MAT-INTENT-001", {row["material_id"] for row in self.base["tables"]["materials"]})

    def test_runtime_reader_does_not_open_expected_or_future_workbook_for_facts(self):
        scenario_data._read_package.cache_clear()
        original = scenario_data.load_workbook
        opened = []
        def read(path, **kwargs):
            opened.append(Path(path).name)
            return original(path, **kwargs)
        with patch.object(scenario_data, "load_workbook", side_effect=read):
            result = load_scenario("S01", clock_at="2026-11-01T23:59:00+08:00")
        self.assertEqual(len(opened), 4)
        self.assertTrue(all(not name.startswith(("05_", "06_", "07_")) for name in opened))
        self.assertNotIn("cash_events", result["tables"])
        self.assertNotIn("scenarios", result["tables"])

    def test_replay_is_separate_scenario_branch_and_time_filtered(self):
        early = load_replay("S01", clock_at="2026-10-03T09:30:00+08:00")
        self.assertTrue(all(not rows for rows in early["tables"].values()))
        later = load_replay("S01", clock_at="2026-10-04T12:00:00+08:00")
        self.assertEqual({row["event_type"] for row in later["tables"]["business_receipts"]}, {"transfer_shipped", "transfer_received"})
        self.assertEqual(later["tables"]["sales"], [])
        self.assertEqual(sum(row["amount"] for row in later["tables"]["cash_events"]), 24)
        self.assertTrue(all(row["scenario_id"] == "S01" for rows in later["tables"].values() for row in rows))

    def test_bad_scope_branch_clock_and_cross_scenario_confirmation_fail_closed(self):
        for args in [("unknown",), ("S01", "cash_refund")]:
            with self.assertRaises(ValueError):
                load_scenario(*args)
        for clock in ("2026-10-03", "2026-10-03T09:30:00", "invalid"):
            with self.assertRaises(ValueError):
                load_scenario("S01", clock_at=clock)
        with self.assertRaises(ValueError):
            load_scenario("S01", confirmed_override_ids=["OV-001"])
        manifest, raw = scenario_data._package()
        changed = deepcopy(raw)
        changed["scenarios"][0]["input_scope"] = "allow_all"
        with self.assertRaises(ValueError):
            scenario_data._validate_references(changed)

    def test_same_instant_uses_business_date_and_stable_snapshot_across_timezones(self):
        local = load_scenario("S02", clock_at="2026-10-03T01:30:00+08:00")
        utc = load_scenario("S02", clock_at="2026-10-02T17:30:00+00:00")
        self.assertEqual(utc["clock_at"], "2026-10-03T01:30:00+08:00")
        self.assertEqual(local["snapshot_id"], utc["snapshot_id"])

    def test_broken_identity_and_inbound_quantity_fail_validation(self):
        _, raw = scenario_data._package()
        changed = deepcopy(raw)
        changed["inventory"][0]["sku_id"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            scenario_data._validate_references(changed)
        changed = deepcopy(raw)
        changed["in_transit"][0]["received_qty"] = 1
        with self.assertRaises(ValueError):
            scenario_data._validate_references(changed)

    def test_corrupted_file_is_rejected_before_xlsx_parser(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "xlsx").mkdir()
            payload = b"changed data"
            (root / "xlsx" / "facts.xlsx").write_bytes(payload)
            (root / "data_dictionary.json").write_text("[]", encoding="utf-8")
            manifest = {"files": [{"file": "facts.xlsx", "role": "facts_or_assumptions", "bytes": len(payload),
                                   "sha256": hashlib.sha256(b"original data").hexdigest(), "sheets": []}]}
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(scenario_data, "load_workbook") as read:
                with self.assertRaisesRegex(ValueError, "校验值"):
                    load_scenario("S01", root=root)
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
