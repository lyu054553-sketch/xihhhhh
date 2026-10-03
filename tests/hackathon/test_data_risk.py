from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.hackathon_data.loader import load_scenario
from backend.hackathon_data.risk import scenario_risks


class ScenarioRiskTests(unittest.TestCase):
    def risk(self, scenario, branch=None):
        return scenario_risks(load_scenario(scenario, branch))

    def test_overlap_has_two_tags_and_one_inventory_cost(self):
        result = self.risk("S02")
        item = result["items"][0]
        self.assertEqual(item["risk_tags"], ["slow", "near_expiry"])
        self.assertEqual(item["slow"]["coverage_days"], 100)
        self.assertEqual(item["near_expiry"]["remaining_sellable_days"], 10)
        self.assertEqual(result["summary"]["known_risk_inventory_cost"], 8000)

    def test_normal_requires_independently_known_sales_and_expiry(self):
        item = self.risk("S10", "normal")["items"][0]
        self.assertEqual(item["slow"]["status"], "normal")
        self.assertEqual(item["near_expiry"]["status"], "normal")
        self.assertEqual(item["slow"]["coverage_days"], 10)
        self.assertEqual(item["risk_inventory_cost"], 0)

    def test_missing_sales_does_not_block_expiry_judgment_or_fill_zero(self):
        result = self.risk("S10", "missing_sales")
        item = result["items"][0]
        self.assertEqual(item["slow"]["status"], "unknown")
        self.assertIsNone(item["slow"]["sales_30"])
        self.assertEqual(item["near_expiry"]["status"], "normal")
        self.assertIsNone(item["risk_inventory_cost"])
        self.assertFalse(result["summary"]["risk_cost_complete"])

    def test_missing_expiry_does_not_block_sales_judgment(self):
        item = self.risk("S10", "missing_expiry")["items"][0]
        self.assertEqual(item["slow"]["status"], "normal")
        self.assertEqual(item["near_expiry"]["status"], "unknown")
        self.assertIsNone(item["near_expiry"]["remaining_sellable_days"])

    def test_short_observation_and_zero_sales_require_investigation(self):
        item = self.risk("S08", "unlisted")["items"][0]
        self.assertEqual(item["slow"]["valid_observed_days"], 5)
        self.assertIsNone(item["slow"]["coverage_days"])
        self.assertIn("sufficient_observed_days", item["slow"]["missing_fields"])
        facts = load_scenario("S10", "normal")
        facts["tables"]["risk_inputs"][0]["sales_30"] = 0
        item = scenario_risks(facts)["items"][0]
        self.assertEqual(item["slow"]["status"], "unknown")
        self.assertIn("positive_observed_sales", item["slow"]["missing_fields"])

    def test_expiry_risk_can_clear_normally_without_mandatory_promotion(self):
        item = self.risk("S03", "only_expiry")["items"][0]
        self.assertEqual(item["risk_tags"], ["near_expiry"])
        self.assertEqual(item["predicted_unsold_qty"], 0)
        self.assertNotIn("recommended_action", item)

    def test_first_unsellable_date_is_exclusive(self):
        facts = load_scenario("S02", clock_at="2026-10-13T00:00:00+08:00")
        item = scenario_risks(facts)["items"][0]
        self.assertEqual(item["near_expiry"]["status"], "unsellable")
        self.assertEqual(item["predicted_unsold_qty"], 100)

    def test_base_uses_same_sku_history_and_excludes_directory_only_stores(self):
        result = self.risk("S01")
        first = next(item for item in result["items"] if item["store_id"] == "ST-001" and item["sku_id"] == "SKU-001")
        second = next(item for item in result["items"] if item["store_id"] == "ST-002" and item["sku_id"] == "SKU-001")
        self.assertEqual(first["slow"]["sales_30"], 12)
        self.assertEqual(first["slow"]["coverage_days"], 300)
        self.assertEqual(second["slow"]["sales_30"], 120)
        self.assertEqual(result["summary"]["included_store_count"], 6)
        self.assertEqual(result["summary"]["directory_store_count"], 50)
        self.assertEqual(len(result["items"]), 72)

    def test_two_lots_share_sku_coverage_and_fefo_demand(self):
        facts = load_scenario("S03", "only_expiry")
        stock = facts["tables"]["inventory"][0]
        stock["quantity"] = 60
        stock["sellable_until"] = "2026-10-08"
        other = deepcopy(stock)
        other.update(inventory_id="another", lot_id="second", sellable_until="2026-10-13")
        facts["tables"]["inventory"].append(other)
        result = scenario_risks(facts)
        self.assertEqual([item["slow"]["coverage_days"] for item in result["items"]], [12, 12])
        self.assertEqual([item["predicted_unsold_qty"] for item in result["items"]], [10, 10])

    def test_sales_price_rows_do_not_duplicate_observation_days(self):
        facts = load_scenario("S01")
        sales = facts["tables"]["sales_daily"]
        selected = next(row for row in sales if row["store_id"] == "ST-002" and row["sku_id"] == "SKU-001" and row["date"] == "2026-10-02")
        second = deepcopy(selected)
        selected["sold_qty"] = 2
        second["sold_qty"] = 2
        sales.append(second)
        item = next(item for item in scenario_risks(facts)["items"] if item["store_id"] == "ST-002" and item["sku_id"] == "SKU-001")
        self.assertEqual(item["slow"]["valid_observed_days"], 30)
        self.assertEqual(item["slow"]["sales_30"], 120)

    def test_missing_cost_keeps_known_risk_diagnosis_but_not_a_valuation(self):
        facts = load_scenario("S02")
        expected = scenario_risks(facts)["items"][0]
        facts["tables"]["inventory"][0]["unit_cost"] = None
        result = scenario_risks(facts)
        item = result["items"][0]
        self.assertEqual(item["slow"], expected["slow"])
        self.assertEqual(item["near_expiry"], expected["near_expiry"])
        self.assertEqual(item["risk_tags"], ["slow", "near_expiry"])
        self.assertEqual(item["cost_missing_fields"], ["unit_cost_cny"])
        self.assertIsNone(item["inventory_cost"])
        self.assertIsNone(item["risk_inventory_cost"])
        for field in ("inventory_cost", "known_risk_inventory_cost", "unknown_risk_inventory_cost"):
            self.assertIsNone(result["summary"][field])
        self.assertFalse(result["summary"]["risk_cost_complete"])
        self.assertEqual(result["summary"]["risk_batch_count"], 1)
        self.assertEqual(result["summary"]["missing_fields"], [f"{item['store_id']}|{item['sku_id']}|{item['lot_id']}.unit_cost_cny"])

    def test_missing_cost_does_not_turn_normal_stock_into_a_risk(self):
        facts = load_scenario("S10", "normal")
        facts["tables"]["inventory"][0]["unit_cost"] = None
        result = scenario_risks(facts)
        item = result["items"][0]
        self.assertEqual(item["slow"]["status"], "normal")
        self.assertEqual(item["near_expiry"]["status"], "normal")
        self.assertEqual(item["risk_tags"], [])
        self.assertIsNone(item["inventory_cost"])
        self.assertIsNone(item["risk_inventory_cost"])
        self.assertEqual(result["summary"]["risk_batch_count"], 0)

    def test_missing_batch_cost_cannot_hide_inside_known_partial_total(self):
        facts = load_scenario("S02")
        known = facts["tables"]["inventory"][0]
        facts["tables"]["inventory"].append({**known, "inventory_id": "unknown-cost", "lot_id": "second", "unit_cost": None})
        result = scenario_risks(facts)
        self.assertEqual(result["items"][0]["inventory_cost"], 8000)
        self.assertIsNone(result["summary"]["inventory_cost"])
        self.assertIsNone(result["summary"]["known_risk_inventory_cost"])
        # An explicitly known zero cost is still a valuation, not a missing field.
        facts["tables"]["inventory"][1]["unit_cost"] = 0
        result = scenario_risks(facts)
        self.assertEqual(result["items"][1]["inventory_cost"], 0)
        self.assertEqual(result["items"][1]["cost_missing_fields"], [])
        self.assertEqual(result["summary"]["inventory_cost"], 8000)

    def test_service_and_legacy_mapping_preserve_null_cost_and_known_classification(self):
        from backend.hackathon_data.service import RetailFactService, migrate
        from backend.store import Store
        for scenario, branch, status in (("S02", None, "risk"), ("S10", "normal", "normal")):
            with self.subTest(scenario=scenario):
                snapshot = load_scenario(scenario, branch)
                snapshot["tables"]["inventory"][0]["unit_cost"] = None
                store = Store(":memory:")
                try:
                    with store.transaction() as tx:
                        migrate(tx)
                    service = RetailFactService(store)
                    with patch("backend.hackathon_data.service.load_scenario", return_value=snapshot):
                        context = service.import_scenario("null-cost-test", scenario, branch)["context"]
                    result = service.assess_risks({"context": context})
                    self.assertEqual(len(result["items"]), 2)
                    self.assertTrue(all(item["result"] == status for item in result["items"]))
                    self.assertTrue(all(item["amount_cny"] is None for item in result["items"]))
                    self.assertTrue(all("unit_cost_cny" in item["missing_fields"] for item in result["items"]))
                    self.assertIsNone(result["attention_inventory_cost_cny"])
                    self.assertEqual(len(result["counted_inventory_keys"]), 1 if status == "risk" else 0)
                    self.assertEqual(len(result["missing_fields"]), 1)
                    self.assertTrue(result["missing_fields"][0].endswith(".unit_cost_cny"))
                    self.assertIsNone(service.query({"context": context})["inventory"][0]["unit_cost_cny"])
                    with store.transaction() as tx:
                        row = tx.execute("SELECT unit_cost,missing_fields_json FROM risks WHERE tenant_id=?", ("null-cost-test",)).fetchone()
                    self.assertIsNone(row["unit_cost"])
                    self.assertIn("unit_cost_cny", json.loads(row["missing_fields_json"]))
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
