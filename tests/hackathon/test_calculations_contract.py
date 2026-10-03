"""Public calculation DTO behavior, using only decision-time input fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from backend.hackathon_calculations import CalculationService
from backend.hackathon_data.loader import load_scenario
from backend.hackathon_shared import CandidateAction, ProposalComparison


def public_facts(snapshot):
    """Test fixture adapter; production calculation never loads a workbook."""
    tables = deepcopy(snapshot["tables"])
    inventory = tables.pop("inventory")
    for row in inventory:
        row["unit_cost_cny"] = row.pop("unit_cost")
        row["base_unit"] = next(p["base_unit"] for p in tables["products"] if p["sku_id"] == row["sku_id"])
    result = {"contract_version": "hackathon.v1", "query_id": "test-query",
              "context": {"tenant_id": "test", "scenario_id": snapshot["scenario_id"],
                          "branch_id": snapshot["branch_id"], "snapshot_id": snapshot["snapshot_id"],
                          "as_of": snapshot["clock_at"], "data_version": snapshot["data_version"],
                          "fact_version": 1, "is_demo": True, "source_refs": [], "missing_fields": []},
              "inventory": inventory, "procurement": [], "policies": [], "missing_fields": [], "warnings": []}
    for public, internal in (("sales_history", "sales_daily"), ("availability_history", "availability_daily"),
                             ("demand_forecasts", "demand_forecasts"), ("routes", "routes"), ("payables", "payables")):
        result[public] = tables.pop(internal, [])
    for public, internal, kind in (("procurement", "purchase_orders", "purchase_order"),
                                   ("procurement", "in_transit", "in_transit"),
                                   ("policies", "risk_policies", "risk_policy"),
                                   ("policies", "return_terms", "return_terms")):
        result[public].extend({**row, "record_type": kind} for row in tables.pop(internal, []))
    permitted = {"stores", "products", "suppliers", "people", "store_products", "store_calendar", "lots",
                 "promotion_stages", "bundle_items", "assumptions", "materials", "purchase_intents",
                 "risk_inputs", "procurement_policy", "transfer_policy", "accounts"}
    result["reference_data"] = {"tables": {key: rows for key, rows in tables.items() if key in permitted},
                                "target": deepcopy(snapshot["target"]), "evaluation_end": snapshot["evaluation_end"]}
    return result


class CalculationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = {sid: public_facts(load_scenario(sid)) for sid in ("S01", "S05", "S06", "S07")}
        cls.service = CalculationService()

    def facts(self, scenario="S01"):
        return deepcopy(self.samples[scenario])

    def compare(self, scenario="S01", **inputs):
        return self.service.compare(self.facts(scenario), {"inputs": {"sales_settlement_days": 0, **inputs}})

    def test_public_contract_fields_cash_units_and_pure_input(self):
        facts = self.facts()
        original = deepcopy(facts)
        response = self.service.compare(facts, {"inputs": {"quantity": 80, "target_store_id": "ST-002", "sales_settlement_days": 0}})
        self.assertTrue(ProposalComparison.__required_keys__ <= response.keys())
        self.assertEqual(facts, original)
        self.assertEqual(response["context"], facts["context"])
        for candidate in response["candidates"]:
            self.assertTrue(CandidateAction.__required_keys__ <= candidate.keys())
            self.assertIn(candidate["action_type"], {"keep", "transfer", "promotion", "return", "procurement"})
            calc = candidate["calculation"]
            self.assertTrue({"planned_qty", "expected_sold_qty", "ending_qty", "execution_cost_cny", "gross_profit_cny",
                             "expected_cash_in_cny", "actual_cash_in_cny", "cash_flow", "calculation_version"} <= calc.keys())
            self.assertEqual(candidate["quantity"], calc["planned_qty"])
            self.assertEqual(candidate["base_unit"], calc["base_unit"])
            self.assertIsNone(calc["actual_cash_in_cny"])
            for event in calc["cash_flow"]:
                self.assertTrue({"direction", "amount_cny", "expected_at", "status", "source_ref"} <= event.keys())
                self.assertEqual(event["status"], "forecast")
        transfer = next(c for c in response["candidates"] if c["action_type"] == "transfer")
        self.assertEqual(transfer["quantity"], 80)
        self.assertLessEqual(transfer["calculation"]["expected_sold_qty"], 80)
        self.assertEqual(transfer["calculation"]["expected_sold_qty"] + transfer["calculation"]["ending_qty"], 80)
        self.assertEqual(transfer["calculation"]["execution_cost_cny"], 24)
        self.assertEqual(transfer["calculation"]["transfer_movement_cost_cny"], 6400)
        self.assertEqual(transfer["calculation"]["expected_sales_cost_recovered_cny"], transfer["calculation"]["expected_sold_qty"] * 80)
        self.assertEqual(transfer["calculation"]["execution_plan"]["actions"][0]["quantity"], 80)
        json.dumps(response, allow_nan=False)

    def test_identical_facts_request_have_identical_ids_independent_of_query_trace(self):
        facts = self.facts()
        request = {"inputs": {"sales_settlement_days": 0}}
        first = self.service.compare(facts, request)
        facts["query_id"] = "different-trace-only"
        second = self.service.compare(facts, request)
        self.assertEqual(first, second)

    def test_facts_policy_request_versions_change_content_ids(self):
        original = self.compare()
        variants = []
        facts = self.facts()
        facts["context"]["fact_version"] += 1
        variants.append(self.service.compare(facts, {"inputs": {"sales_settlement_days": 0}}))
        facts = self.facts()
        facts["routes"][0]["fixed_fee"] = 100
        variants.append(self.service.compare(facts, {"inputs": {"sales_settlement_days": 0}}))
        variants.append(self.compare(transport_fee=100))
        for changed in variants:
            self.assertNotEqual(original["comparison_id"], changed["comparison_id"])
            self.assertNotEqual(original["candidates"][0]["candidate_id"], changed["candidates"][0]["candidate_id"])
        self.assertNotEqual(original["policy_version"], variants[1]["policy_version"])

    def test_scope_and_clock_mismatch_rejected(self):
        facts = self.facts()
        for mutation in ({"tenant_id": "other"}, {"fact_version": 2}, {"snapshot_id": "other"}, {"as_of": "2026-10-04T09:30:00+08:00"}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.service.compare(facts, {"context": {**facts["context"], **mutation}})
        for request in ({"horizon_start": "2026-10-04"}, {"horizon_end": "2026-10-03"},
                        {"horizon_end": "2026-10-25T00:00:00"}, {"horizon_end": "2028-10-25"},
                        {"risk_keys": ["S02:ST-001:SKU-001:LOT-001-001:slow_moving"]}, {"assumption_ids": ["unknown"]}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.service.compare(facts, request)

    def test_only_declared_canonical_sources_are_accepted(self):
        facts = self.facts()
        facts["reference_data"]["tables"]["inventory"] = []
        with self.assertRaises(ValueError):
            self.service.compare(facts, {})
        facts = self.facts()
        facts["inventory"][0]["unit_cost"] = 999
        with self.assertRaises(ValueError):
            self.service.compare(facts, {})
        for request in ({"quantity": 80}, {"inputs": {"future_events": []}}, {"inputs": {"combination": [{"type": "purchase"}]}}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.service.compare(self.facts(), request)

    def test_missing_facts_never_become_success_or_known_zero(self):
        facts = self.facts()
        facts["reference_data"]["tables"].pop("store_calendar")
        response = self.service.compare(facts, {})
        self.assertIsNone(response["selected_candidate_id"])
        self.assertFalse(response["candidates"][0]["feasible"])
        self.assertIn("reference_data.tables.store_calendar", response["candidates"][0]["missing_fields"])
        self.assertIsNone(response["candidates"][0]["calculation"]["expected_cash_in_cny"])

    def test_other_store_data_notice_does_not_hide_complete_local_options(self):
        facts = self.facts()
        facts["missing_fields"] = ["stores.ST-050.business_facts"]
        response = self.service.compare(facts, {"inputs": {"quantity": 80, "target_store_id": "ST-002", "sales_settlement_days": 0}})
        self.assertTrue(next(c for c in response["candidates"] if c["action_type"] == "transfer")["feasible"])
        self.assertEqual(response["fact_notices"], ["stores.ST-050.business_facts"])

    def test_procurement_formal_enum_and_payment_separation(self):
        response = self.compare("S07")
        candidate = next(c for c in response["candidates"] if c["action_type"] == "procurement")
        self.assertTrue(candidate["feasible"])
        self.assertEqual(candidate["quantity"], 60)
        self.assertIsNone(candidate["lot_id"])
        self.assertEqual(candidate["calculation"]["quantity_payment_reduction_cny"], 1600)
        self.assertEqual(candidate["calculation"]["expected_sold_qty"] + candidate["calculation"]["ending_qty"], 60)
        self.assertEqual(candidate["calculation"]["store_sku_ending_qty"], 70)
        self.assertEqual(candidate["calculation"]["expected_cash_in_cny"], 0)
        self.assertIsNone(candidate["calculation"]["actual_cash_in_cny"])
        self.assertEqual(candidate["calculation"]["execution_plan"]["actions"][0]["type"], "purchase")

    def test_multiple_intentions_require_identity_without_breaking_other_candidates(self):
        facts = self.facts("S07")
        intents = facts["reference_data"]["tables"]["purchase_intents"]
        original = next(row for row in intents if row["intent_id"] == "INTENT-S07-001")
        intents.append({**deepcopy(original), "intent_id": "confirmed-new-intent", "quantity": 120, "unit_cost": 45})
        response = self.service.compare(facts, {"inputs": {"sales_settlement_days": 0}})
        purchase = next(row for row in response["candidates"] if row["action_type"] == "procurement")
        self.assertFalse(purchase["feasible"])
        self.assertEqual(purchase["missing_fields"], ["purchase_intent.intent_id"])
        self.assertIsNone(purchase["quantity"])
        self.assertIsNone(purchase["calculation"]["expected_cash_out_cny"])
        self.assertTrue(next(row for row in response["candidates"] if row["action_type"] == "keep")["feasible"])
        selected = self.service.compare(facts, {"inputs": {"sales_settlement_days": 0,
            "purchase_intent": {"intent_id": "confirmed-new-intent"}}})
        purchase = next(row for row in selected["candidates"] if row["action_type"] == "procurement")
        self.assertTrue(purchase["feasible"])
        self.assertEqual(purchase["quantity"], 60)
        self.assertEqual(purchase["calculation"]["details"]["original_amount"], 5400)
        self.assertEqual(purchase["calculation"]["details"]["adjusted_amount"], 2700)
        self.assertEqual(purchase["calculation"]["execution_plan"]["actions"][0]["intent_id"], "confirmed-new-intent")
        self.assertNotEqual(selected["comparison_id"], response["comparison_id"])
        self.assertEqual(original["quantity"], 100)

    def test_intention_selector_cannot_reference_unknown_or_override_published_fields(self):
        for supplied in ({"intent_id": "not-in-this-fact-scope"}, {"intent_id": ""}, {"intent_id": None},
                         {"intent_id": "INTENT-S07-001", "unit_cost": 1}, "INTENT-S07-001"):
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                self.service.compare(self.facts("S07"), {"inputs": {"purchase_intent": supplied}})

    def test_promotion_groups_have_component_units(self):
        response = self.compare("S06")
        candidate = next(c for c in response["candidates"] if c["action_type"] == "promotion")
        self.assertEqual(candidate["base_unit"], "组")
        self.assertEqual(candidate["quantity"], 40)
        self.assertEqual(candidate["calculation"]["expected_cash_in_cny"], 420)
        self.assertEqual(len(candidate["calculation"]["quantity_lines"]), 2)
        self.assertTrue(all(row["base_unit"] for row in candidate["calculation"]["quantity_lines"]))

    def test_combination_has_atomic_group_and_independent_formal_members(self):
        response = self.compare(combination=[{"type": "transfer", "target_store_id": "ST-002", "quantity": 40},
                                             {"type": "transfer", "target_store_id": "ST-004", "quantity": 10}])
        group = response["candidate_groups"][0]
        candidates = {row["candidate_id"]: row for row in response["candidates"]}
        self.assertTrue(group["feasible"])
        self.assertEqual(len(group["member_candidate_ids"]), 2)
        plan = group["calculation"]["execution_plan"]
        self.assertEqual(plan["type"], "combination")
        self.assertEqual(len(plan["children"]), 2)
        self.assertEqual(sum(row["quantity"] for row in plan["allocations"]), 50)
        for member_id in group["member_candidate_ids"]:
            self.assertEqual(candidates[member_id]["action_type"], "transfer")
            self.assertTrue(candidates[member_id]["feasible"])
        repeated = self.compare(combination=[{"type": "transfer", "target_store_id": "ST-002", "quantity": 40},
                                             {"type": "transfer", "target_store_id": "ST-004", "quantity": 10}])
        self.assertEqual(group["group_id"], repeated["candidate_groups"][0]["group_id"])

    def test_conflicting_group_does_not_invalidate_standalone_members(self):
        response = self.compare(combination=[{"type": "transfer", "target_store_id": "ST-002", "quantity": 80},
                                             {"type": "transfer", "target_store_id": "ST-002", "quantity": 80}])
        group = response["candidate_groups"][0]
        self.assertFalse(group["feasible"])
        self.assertTrue(group["exclusion_reasons"])
        self.assertTrue(all(c["feasible"] for c in response["candidates"] if c["candidate_id"] in group["member_candidate_ids"]))


class InjectedFactServiceTests(unittest.TestCase):
    def test_actual_fact_service_dto_is_calculable_and_repeatable(self):
        # Concrete integration lives in this test, never in the calculator.
        from backend.hackathon_data.service import RetailFactService, migrate
        from backend.store import Store
        with tempfile.TemporaryDirectory(prefix="calculation-contract-") as temporary:
            store = Store(str(Path(temporary) / "test.sqlite3"))
            try:
                with store.transaction() as tx:
                    migrate(tx)
                facts = RetailFactService(store)
                context = facts.import_scenario("calculation-test", "S01")["context"]
                query = {"context": context}
                request = {"context": context, "risk_keys": ["S01:ST-001:SKU-001:LOT-001-001:slow_moving"],
                           "inputs": {"quantity": 80, "target_store_id": "ST-002", "sales_settlement_days": 0}}
                calculator = CalculationService()
                first = calculator.compare(facts.query(query), request)
                second = calculator.compare(facts.query(query), request)
                self.assertEqual(first["comparison_id"], second["comparison_id"])
                transfer = next(c for c in first["candidates"] if c["action_type"] == "transfer")
                self.assertTrue(transfer["feasible"])
                self.assertEqual(transfer["calculation"]["planned_qty"], 80)
                self.assertEqual(transfer["calculation"]["execution_plan"]["allocations"][0]["quantity"], 80)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
