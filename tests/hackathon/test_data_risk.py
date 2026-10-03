from copy import deepcopy
import unittest

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


if __name__ == "__main__":
    unittest.main()
