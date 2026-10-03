"""Action-level inputs preserve scope, unknowns and physical stock semantics."""
from copy import deepcopy
import unittest

from backend.hackathon_calculations import CalculationService
from backend.hackathon_data.loader import load_scenario
from tests.hackathon.test_calculations_contract import public_facts


class BusinessInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = {sid: public_facts(load_scenario(sid)) for sid in ("S01", "S05", "S06", "S07")}
        cls.service = CalculationService()

    def compare(self, scenario="S01", business=None, legacy=None, facts=None):
        request = {"inputs": {"sales_settlement_days": 0, **(legacy or {})}}
        if business is not None:
            request["business_inputs"] = business
        return self.service.compare(facts or self.samples[scenario], request)

    def candidate(self, result, kind):
        return next(row for row in result["candidates"] if row["action_type"] == kind)

    def transfer(self, **changes):
        route = next(row for row in self.samples["S01"]["routes"] if row["from_store_id"] == "ST-001" and row["to_store_id"] == "ST-002")
        unit = next(row["base_unit"] for row in self.samples["S01"]["inventory"] if row["sku_id"] == "SKU-001")
        return {"origin_store_id": "ST-001", "target_store_id": "ST-002", "sku_id": "SKU-001", "lot_id": "LOT-001-001",
                "quantity": 80, "base_unit": unit, "route_id": route["route_id"], "route_fee_cny": 24, **changes}

    def promotion(self):
        tables = self.samples["S06"]["reference_data"]["tables"]
        return {"products": [{"sku_id": row["sku_id"], "quantity_per_bundle": row["qty_per_bundle"], "base_unit": row["base_unit"]}
                             for row in tables["bundle_items"]],
                "price_stages": [{"label": row["stage_id"], "price_cny": row["bundle_price"], "start_date": row["start_date"],
                                  "end_date_exclusive": row["end_date_exclusive"]} for row in tables["promotion_stages"]]}

    def procurement(self, **changes):
        intent = self.samples["S07"]["reference_data"]["tables"]["purchase_intents"][0]
        return {"sku_id": intent["sku_id"], "supplier_id": intent["supplier_id"], "quantity": intent["quantity"],
                "base_unit": intent["unit"], "unit_cost_cny": intent["unit_cost"],
                "expected_arrival_date": intent["expected_arrival_date"], "payment_date": intent["payment_date"], **changes}

    def test_transfer_is_local_and_does_not_mutate_facts_or_baseline(self):
        original = deepcopy(self.samples["S01"])
        baseline = self.compare()
        changed = self.compare(business={"transfer": self.transfer(quantity=40, route_fee_cny=50)})
        self.assertEqual(self.samples["S01"], original)
        self.assertEqual(baseline["baseline_id"], changed["baseline_id"])
        for kind in ("keep", "return", "promotion"):
            self.assertEqual(self.candidate(baseline, kind)["calculation"], self.candidate(changed, kind)["calculation"])
        transfer = self.candidate(changed, "transfer")
        self.assertTrue(transfer["feasible"])
        self.assertEqual(transfer["quantity"], 40)
        self.assertEqual(transfer["calculation"]["execution_cost_cny"], 50)
        self.assertEqual(changed, self.compare(business={"transfer": self.transfer(quantity=40, route_fee_cny=50)}))

    def test_transfer_stock_changes_use_same_lot_not_destination_sku_total(self):
        result = self.compare(business={"transfer": self.transfer()})
        candidate = self.candidate(result, "transfer")
        changes = {row["store_id"]: row for row in candidate["inventory_changes"]}
        self.assertEqual((changes["ST-001"]["quantity_before"], changes["ST-001"]["quantity_after"]), (120, 40))
        # The destination's existing 10 belong to LOT-002-001, not the moved lot.
        self.assertEqual((changes["ST-002"]["quantity_before"], changes["ST-002"]["quantity_after"]), (0, 80))
        self.assertEqual(sum(row["quantity_delta"] for row in changes.values()), 0)
        self.assertTrue(all(row["lot_id"] == "LOT-001-001" and row["source_ref"] for row in changes.values()))
        self.assertNotEqual(candidate["calculation"]["ending_qty"], changes["ST-002"]["quantity_after"])
        self.assertEqual(self.candidate(result, "keep")["inventory_changes"], [])

    def test_explicit_unknowns_never_fall_back_to_routes_or_inventory(self):
        for field in ("quantity", "route_fee_cny", "target_store_id", "route_id", "base_unit"):
            with self.subTest(field=field):
                result = self.compare(business={"transfer": self.transfer(**{field: None})})
                candidate = self.candidate(result, "transfer")
                self.assertFalse(candidate["feasible"])
                self.assertIn("business_inputs.transfer." + field, candidate["missing_fields"])
                self.assertIsNone(candidate["quantity"])
                self.assertIsNone(candidate["calculation"]["expected_cash_in_cny"])
                self.assertEqual(candidate["inventory_changes"], [])
                self.assertTrue(self.candidate(result, "keep")["feasible"])

    def test_identity_units_routes_and_invalid_numbers_are_checked(self):
        for patch in ({"origin_store_id": "ST-004"}, {"lot_id": "LOT-002-001"}, {"sku_id": "SKU-004"},
                      {"base_unit": "wrong"}, {"target_store_id": "missing"}, {"target_store_id": "ST-004"},
                      {"quantity": -1}, {"quantity": True}, {"route_fee_cny": float("inf")}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.compare(business={"transfer": self.transfer(**patch)})
        values = self.transfer()
        values.pop("base_unit")
        with self.assertRaises(ValueError):
            self.compare(business={"transfer": values})

    def test_omission_uses_facts_while_explicit_null_is_unknown(self):
        omitted = self.transfer()
        omitted.pop("route_fee_cny")
        self.assertEqual(self.candidate(self.compare(business={"transfer": omitted}), "transfer")["calculation"]["execution_cost_cny"], 24)
        unknown = self.candidate(self.compare(business={"transfer": self.transfer(route_fee_cny=None)}), "transfer")
        self.assertIsNone(unknown["calculation"]["execution_cost_cny"])

    def test_new_and_legacy_input_conflicts_are_explicit(self):
        for business, legacy in (({"transfer": self.transfer()}, {"quantity": 80}),
                                  ({"transfer": self.transfer()}, {"transport_fee": 24}),
                                  ({"promotion": {}}, {"stage_prices": {}}),
                                  ({"return": {}}, {"return_terms": {}}),
                                  ({"procurement": {}}, {"purchase_intent": {}}),
                                  ({"transfer": self.transfer()}, {"combination": [{"type": "transfer", "quantity": 1}]})):
            with self.subTest(business=business, legacy=legacy), self.assertRaises(ValueError):
                self.compare(business=business, legacy=legacy)
        for business in (None, [], {"unsupported": {}}, {"transfer": None}, {"transfer": {"supplier_confirmed": True}}):
            with self.subTest(business=business), self.assertRaises(ValueError):
                self.service.compare(self.samples["S01"], {"business_inputs": business})

    def test_promotion_prices_recalculate_shared_inventory_and_margin(self):
        inputs = self.promotion()
        inputs["price_stages"][0]["price_cny"] = 12
        result = self.compare("S06", business={"promotion": inputs})
        candidate = self.candidate(result, "promotion")
        self.assertTrue(candidate["feasible"])
        self.assertEqual(candidate["quantity"], 40)
        self.assertEqual(candidate["calculation"]["expected_cash_in_cny"], 440)
        self.assertEqual(candidate["inventory_changes"], [])
        inputs["price_stages"][0]["price_cny"] = 9
        candidate = self.candidate(self.compare("S06", business={"promotion": inputs}), "promotion")
        self.assertFalse(candidate["feasible"])
        self.assertTrue(candidate["exclusion_reasons"])

    def test_documented_promotion_scope_and_stage_ids_use_the_same_validator(self):
        facts = self.samples["S06"]
        target = facts["reference_data"]["target"]
        product = next(row for row in facts["reference_data"]["tables"]["products"]
                       if row["sku_id"] == target["sku_id"])
        stages = facts["reference_data"]["tables"]["promotion_stages"]
        supplied = {"promotion_id": stages[0]["promotion_id"], "store_id": target["store_id"],
                    "sku_id": target["sku_id"], "lot_id": target["lot_id"],
                    "base_unit": product["base_unit"], "quantity": 20, "sales_settlement_days": 0,
                    "products": self.promotion()["products"],
                    "price_stages": [{"stage_id": row["stage_id"], "price_cny": row["bundle_price"]} for row in stages]}
        candidate = self.candidate(self.compare("S06", business={"promotion": supplied}), "promotion")
        self.assertTrue(candidate["feasible"], candidate["missing_fields"])
        self.assertEqual(candidate["quantity"], 20)
        self.assertEqual(candidate["calculation"]["details"]["input_source"], "business_inputs.promotion")

    def test_promotion_changes_cannot_reuse_unrelated_demand_or_skip_fees(self):
        for mutation in ("products", "dates", "subset", "null"):
            inputs = self.promotion()
            if mutation == "products":
                inputs["products"][0]["quantity_per_bundle"] = 2
            elif mutation == "dates":
                inputs["price_stages"][0]["start_date"] = "2026-10-04"
            elif mutation == "subset":
                inputs["price_stages"] = inputs["price_stages"][1:]
            else:
                inputs["price_stages"][0]["price_cny"] = None
            with self.subTest(mutation=mutation):
                candidate = self.candidate(self.compare("S06", business={"promotion": inputs}), "promotion")
                self.assertFalse(candidate["feasible"])
                self.assertTrue(candidate["missing_fields"])
                self.assertIsNone(candidate["calculation"]["expected_cash_in_cny"])

    def test_return_user_fee_and_mode_do_not_confirm_supplier(self):
        unit = next(row["base_unit"] for row in self.samples["S05"]["inventory"] if row["sku_id"] == "SKU-011")
        inputs = {"supplier_id": "SUP-002", "sku_id": "SKU-011", "lot_id": "SCLOT-S05", "quantity": 50,
                  "base_unit": unit, "settlement_method": "refund", "fee_cny": 30}
        result = self.compare("S05", business={"return": inputs})
        candidate = self.candidate(result, "return")
        self.assertFalse(candidate["feasible"])
        self.assertEqual(candidate["quantity"], 50)
        self.assertEqual(candidate["calculation"]["execution_cost_cny"], 30)
        self.assertIn("supplier_confirmed", candidate["missing_fields"])
        self.assertFalse(candidate["calculation"]["details"]["supplier_confirmed"])
        self.assertEqual(candidate["inventory_changes"][0]["quantity_after"], 50)
        inputs["fee_cny"] = None
        candidate = self.candidate(self.compare("S05", business={"return": inputs}), "return")
        self.assertIn("business_inputs.return.fee_cny", candidate["missing_fields"])
        self.assertIsNone(candidate["calculation"]["execution_cost_cny"])

    def test_procurement_intention_recalculates_without_changing_supply(self):
        facts = deepcopy(self.samples["S07"])
        result = self.compare("S07", business={"procurement": self.procurement(quantity=120, unit_cost_cny=50)})
        candidate = self.candidate(result, "procurement")
        self.assertTrue(candidate["feasible"])
        self.assertEqual(candidate["quantity"], 60)
        self.assertEqual(candidate["calculation"]["details"]["original_amount"], 6000)
        self.assertEqual(candidate["calculation"]["expected_cash_out_cny"], 3000)
        self.assertEqual(candidate["inventory_changes"], [])
        self.assertIsNone(candidate["calculation"]["actual_cash_in_cny"])
        self.assertEqual(facts, self.samples["S07"])

    def test_procurement_unknown_payment_and_existing_order_are_not_promoted(self):
        candidate = self.candidate(self.compare("S07", business={"procurement": self.procurement(payment_date=None)}), "procurement")
        self.assertFalse(candidate["feasible"])
        self.assertIn("business_inputs.procurement.payment_date", candidate["missing_fields"])
        self.assertIsNone(candidate["calculation"]["expected_cash_out_cny"])
        candidate = self.candidate(self.compare("S07", business={"procurement": self.procurement(purchase_order_id="PO-FUT-002")}), "procurement")
        self.assertFalse(candidate["feasible"])
        self.assertIn("confirmed_order_change_permission_and_fee", candidate["missing_fields"])
        with self.assertRaises(ValueError):
            self.compare("S07", business={"procurement": self.procurement(purchase_order_id="PO-FUT-001")})

    def test_procurement_zero_intention_is_not_treated_as_omitted(self):
        candidate = self.candidate(self.compare("S07", business={"procurement": self.procurement(quantity=0)}), "procurement")
        self.assertEqual(candidate["calculation"]["details"]["original_quantity"], 0)
        self.assertEqual(candidate["calculation"]["details"]["original_amount"], 0)
        self.assertEqual(candidate["calculation"]["details"]["recommended_quantity"], 60)

    def test_procurement_partial_base_unit_edit_converts_existing_case_intention(self):
        facts = deepcopy(self.samples["S07"])
        tables = facts["reference_data"]["tables"]
        product = next(row for row in tables["products"] if row["sku_id"] == "SKU-003")
        product.update(purchase_unit="case", units_per_purchase_unit=10)
        tables["purchase_intents"][0].update(quantity=10, unit="case", unit_cost=400)
        result = self.compare("S07", facts=facts, business={"procurement": {"unit_cost_cny": 50}})
        candidate = self.candidate(result, "procurement")
        self.assertTrue(candidate["feasible"])
        self.assertEqual(candidate["calculation"]["details"]["original_quantity"], 100)
        self.assertEqual(candidate["calculation"]["details"]["original_amount"], 5000)
        self.assertEqual(candidate["calculation"]["expected_cash_out_cny"], 3000)

    def test_unknown_inventory_quantity_is_not_reported_as_zero(self):
        # Test the projection independently: an unavailable target quantity must
        # not acquire a fictitious before/after, even though the move is known.
        from backend.hackathon_calculations.service import _canonical
        canonical = _canonical(self.samples["S01"])
        for row in canonical["tables"]["inventory"]:
            if row["store_id"] == "ST-001" and row["lot_id"] == "LOT-001-001":
                row["quantity"] = None
        raw = {"actions": [{"type": "transfer", "store_id": "ST-001", "target_store_id": "ST-002",
                            "sku_id": "SKU-001", "lot_id": "LOT-001-001", "quantity": 80}]}
        changes = self.service._inventory_changes(raw, canonical)
        self.assertIsNone(changes[0]["quantity_before"])
        self.assertIsNone(changes[0]["quantity_after"])
        self.assertEqual(changes[0]["quantity_delta"], -80)


if __name__ == "__main__":
    unittest.main()
