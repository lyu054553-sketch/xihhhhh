"""Business invariants checked against input facts, never replay/answer sheets."""
from copy import deepcopy
from decimal import Decimal
import unittest

from backend.hackathon_calculations.calculations import (
    calculate_combination, calculate_promotion, calculate_purchase, calculate_return, compare_options,
    simulate_cash, validate_combination,
)
from backend.hackathon_data.loader import load_scenario
from backend.serialization import dumps


class ScenarioCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = {sid: load_scenario(sid) for sid in ("S01", "S05", "S06", "S07")}

    def facts(self, scenario="S01"):
        return deepcopy(self.scenarios[scenario])

    def transfer(self, facts=None, **request):
        values = {"quantity": 80, "target_store_id": "ST-002", "sales_settlement_days": 0, **request}
        return compare_options(facts or self.facts(), values)["candidates"][1]

    def test_structured_confirmed_return_fields_use_numeric_ratio_and_fees(self):
        facts = self.facts("S05")
        for term in facts["tables"]["return_terms"]:
            term.pop("refund_price_rule", None)
            term.update(refund_pct=90, freight_fee_cny=30, restocking_fee_cny=0)
        result = calculate_return(facts, {"quantity": 100, "return_terms": {
            "supplier_confirmed": True, "packaging_confirmed": True, "acceptance_date": "2026-10-06"}})
        self.assertEqual(result["feasibility"], "feasible")
        self.assertEqual(result["expected_cash_in"], 900)
        self.assertEqual(result["expected_net_cash"], 870)

    def test_incomplete_structured_return_terms_report_missing_constraints(self):
        facts = self.facts("S05")
        term = next(row for row in facts["tables"]["return_terms"] if facts["target"]["sku_id"] in row["sku_scope"])
        for key in ("effective_from", "effective_to", "min_remaining_shelf_life_days", "max_return_ratio", "settlement_days"):
            term.pop(key, None)
        term.update(refund_pct=90, return_deadline="2026-10-20", freight_fee_cny=30)
        result = calculate_return(facts)
        self.assertEqual(result["feasibility"], "needs_confirmation")
        self.assertIn("return_terms.effective_dates", result["missing_fields"])
        self.assertIn("min_remaining_shelf_life_days", result["missing_fields"])
        self.assertIn("settlement_days", result["missing_fields"])
        self.assertIsNone(result["expected_net_cash"])

    def test_transfer_computes_from_facts_and_preserves_input(self):
        facts = self.facts()
        original = dumps(facts)
        candidate = self.transfer(facts)
        self.assertEqual(candidate["feasibility"], "feasible")
        self.assertEqual(candidate["allocations"][0]["quantity"], 80)
        self.assertEqual(candidate["execution_cost"], 24)
        self.assertGreater(candidate["details"]["target_expected_sold_qty"], 0)
        self.assertNotEqual(candidate["details"]["target_expected_sold_qty"], 64)
        self.assertEqual(dumps(facts), original)
        self.assertEqual(candidate["actions"][0]["unit_cost"], 80)

    def test_transfer_inbound_supply_does_not_get_counted_twice(self):
        candidate = self.transfer(target_store_id="ST-003")
        self.assertEqual(candidate["details"]["target_net_demand"], 0)
        self.assertEqual(candidate["feasibility"], "blocked")
        # Lower that store's initial stock; supply is 100 incoming, not 200.
        facts = self.facts()
        for row in facts["tables"]["inventory"]:
            if row["store_id"] == "ST-003" and row["sku_id"] == "SKU-001" and row["stock_state"] == "on_hand":
                row["quantity"] = 0
        changed = self.transfer(facts, target_store_id="ST-003", quantity=10)
        self.assertGreater(changed["details"]["target_net_demand"], 0)

    def test_higher_freight_changes_amount_and_recommendation(self):
        small = self.transfer()
        high = self.transfer(transport_fee=10000)
        self.assertEqual(small["expected_net_cash"] - high["expected_net_cash"], Decimal("9976"))
        comparison = compare_options(self.facts(), {"quantity": 80, "target_store_id": "ST-002", "sales_settlement_days": 0, "transport_fee": 10000})
        self.assertEqual(comparison["recommended_strategy_id"], "retain")

    def test_calendar_closure_blocks_transfer(self):
        facts = self.facts()
        for day in facts["tables"]["store_calendar"]:
            if day["store_id"] == "ST-002" and day["date"] >= "2026-10-04":
                day.update(is_open=False, can_receive=False)
        candidate = self.transfer(facts)
        self.assertEqual(candidate["feasibility"], "blocked")
        self.assertIsNone(candidate["expected_net_cash"])

    def test_requested_quantity_is_not_silently_clamped(self):
        for quantity in (0, 111, 1000):
            with self.subTest(quantity=quantity):
                self.assertEqual(self.transfer(quantity=quantity)["feasibility"], "blocked")

    def test_expiry_boundary_is_exclusive(self):
        facts = self.facts()
        row = next(r for r in facts["tables"]["inventory"] if r["lot_id"] == facts["target"]["lot_id"])
        row["sellable_until"] = "2026-10-04"
        self.assertEqual(self.transfer(facts)["feasibility"], "blocked")

    def test_missing_forecast_is_not_zero_demand_or_success(self):
        facts = self.facts()
        facts["tables"]["demand_forecasts"] = [r for r in facts["tables"]["demand_forecasts"]
                                               if not (r["store_id"] == "ST-002" and r["sku_id"] == "SKU-001" and r["date"] == "2026-10-10")]
        candidate = self.transfer(facts, quantity=10)
        self.assertEqual(candidate["feasibility"], "needs_confirmation")
        self.assertIsNone(candidate["expected_net_cash"])
        self.assertTrue(any("demand_base" in field for field in candidate["missing_fields"]))

    def test_cash_settlement_is_not_assumed_same_day(self):
        comparison = compare_options(self.facts(), {"quantity": 80, "target_store_id": "ST-002"})
        self.assertIsNone(comparison["recommended_strategy_id"])
        self.assertIsNone(comparison["candidates"][1]["expected_net_cash"])
        self.assertGreater(comparison["candidates"][1]["expected_sales_revenue"], 0)

    def test_nonfinite_negative_boolean_and_fractional_quantity_rejected(self):
        for value in (float("nan"), float("inf"), -1, True, "1.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.transfer(quantity=value)
        for value in ("NaN", "Infinity", -0.01, False):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.transfer(transport_fee=value)

    def test_purchase_demand_safety_inbound_and_period_payment(self):
        result = calculate_purchase(self.facts("S07"))
        self.assertEqual(result["feasibility"], "feasible")
        self.assertEqual(result["details"]["recommended_quantity"], 60)
        self.assertEqual(result["details"]["original_amount"], 4000)
        self.assertEqual(result["details"]["adjusted_amount"], 2400)
        self.assertEqual(result["incremental_net_cash_vs_baseline"], 1600)
        self.assertEqual(result["expected_unsold_qty"], 70)
        self.assertEqual(len(result["settlement_timeline"]), 1)

    def test_purchase_demand_change_and_moq_rounding(self):
        facts = self.facts("S07")
        row = next(r for r in facts["tables"]["demand_forecasts"] if r["store_id"] == "ST-004" and r["sku_id"] == "SKU-003" and r["date"] == "2026-10-03")
        row["demand_base"] += 1
        result = calculate_purchase(facts)
        self.assertEqual(result["details"]["recommended_quantity"], 70)
        self.assertEqual(result["expected_unsold_qty"], 79)

    def test_purchase_dated_stockout_blocks_late_delivery(self):
        result = calculate_purchase(self.facts("S07"), {"purchase_intent": {"expected_arrival_date": "2026-10-18"}})
        self.assertEqual(result["feasibility"], "blocked")

    def test_purchase_qty_and_delay_cash_are_distinct(self):
        result = calculate_purchase(self.facts("S07"), {"new_payment_date": "2026-10-25"})
        self.assertEqual(result["details"]["quantity_payment_reduction"], 1600)
        self.assertEqual(result["details"]["deferred_payment_amount"], 2400)
        self.assertEqual(result["incremental_net_cash_vs_baseline"], 4000)

    def test_purchase_box_conversion_preserves_amount(self):
        result = calculate_purchase(self.facts("S07"), {"purchase_intent": {"quantity": 25, "unit": "箱", "unit_cost": 160}})
        self.assertEqual(result["details"]["original_quantity"], 100)
        self.assertEqual(result["details"]["original_amount"], 4000)

    def test_promotion_stages_share_inventory_for_each_demand_case(self):
        result = calculate_promotion(self.facts("S06"), {"sales_settlement_days": 0})
        self.assertEqual(result["feasibility"], "feasible")
        cases = result["details"]["demand_scenarios"]
        self.assertEqual([cases[k]["expected_sold_qty"] for k in ("low", "base", "high")], [20, 40, 40])
        self.assertEqual([s["expected_sold_qty"] for s in cases["high"]["stages"]], [25, 15])
        self.assertEqual(result["expected_sales_revenue"], 420)
        self.assertEqual(result["expected_net_cash"], 400)
        self.assertEqual([r["quantity"] for r in result["allocations"]], [40, 40])

    def test_promotion_price_recalculates_without_fabricated_elasticity(self):
        result = calculate_promotion(self.facts("S06"), {"stage_prices": {"PROMO-S06-1": 12}, "sales_settlement_days": 0})
        self.assertEqual(result["expected_sold_qty"], 40)
        self.assertEqual(result["expected_sales_revenue"], 440)
        invalid = calculate_promotion(self.facts("S06"), {"stage_prices": {"PROMO-S06-2": 9}})
        self.assertEqual(invalid["feasibility"], "blocked")

    def test_promotion_reserved_component_reduces_shared_cap(self):
        facts = self.facts("S06")
        row = next(r for r in facts["tables"]["inventory"] if r["store_id"] == "ST-004" and r["sku_id"] == "SKU-008")
        row["reserved_qty"] = 35
        result = calculate_promotion(facts, {"sales_settlement_days": 0})
        self.assertEqual(result["allocated_qty"], 25)
        self.assertEqual(result["expected_sold_qty"], 25)

    def test_return_contract_does_not_imply_supplier_acceptance_or_known_freight(self):
        result = calculate_return(self.facts("S05"))
        self.assertEqual(result["details"]["conditional_settlement_amount"], 900)
        self.assertEqual(result["feasibility"], "needs_confirmation")
        self.assertIn("supplier_confirmed", result["missing_fields"])
        self.assertIn("freight_fee", result["missing_fields"])
        self.assertIsNone(result["execution_cost"])

    def test_confirmed_refund_uses_explicit_freight_and_settlement(self):
        result = calculate_return(self.facts("S05"), {"return_terms": {
            "packaging_confirmed": True, "supplier_confirmed": True, "freight_fee": 45, "acceptance_date": "2026-10-06"}})
        self.assertEqual(result["feasibility"], "feasible")
        self.assertEqual(result["expected_net_cash"], 855)
        refund = next(e for e in result["settlement_timeline"] if e["direction"] == "in")
        self.assertEqual(refund["event_date"], "2026-10-13")

    def test_exchange_and_credit_are_not_cash_refunds(self):
        for mode in ("exchange", "payable_credit"):
            with self.subTest(mode=mode):
                result = calculate_return(self.facts("S05"), {"settlement_mode": mode})
                self.assertFalse(any(e["direction"] == "in" for e in result["settlement_timeline"]))

    def test_confirmed_exchange_checks_value_and_has_no_refund(self):
        facts = load_scenario("S05", "exchange")
        terms = {"packaging_confirmed": True, "supplier_confirmed": True, "freight_fee": 30,
                 "acceptance_date": "2026-10-06", "replacement_sku_id": "SKU-006",
                 "replacement_lot_id": "SCLOT-S05-REPLACEMENT", "replacement_qty": 100,
                 "replacement_unit_cost": 9, "cash_difference": 0}
        result = calculate_return(facts, {"return_terms": terms})
        self.assertEqual(result["feasibility"], "feasible")
        self.assertEqual(result["expected_net_cash"], -30)
        self.assertFalse(any(e["direction"] == "in" for e in result["settlement_timeline"]))
        terms["replacement_unit_cost"] = 10
        self.assertEqual(calculate_return(facts, {"return_terms": terms})["feasibility"], "blocked")

    def test_confirmed_credit_reduces_payable_without_cash_in(self):
        facts = load_scenario("S05", "payable_credit")
        terms = {"packaging_confirmed": True, "supplier_confirmed": True, "freight_fee": 30,
                 "acceptance_date": "2026-10-06", "payable_id": "AP-S05-001", "credit_apply_date": "2026-10-16"}
        result = calculate_return(facts, {"return_terms": terms})
        self.assertEqual(result["feasibility"], "feasible")
        self.assertEqual(result["expected_cash_in"], 0)
        self.assertEqual(result["expected_cash_out"], 1130)
        self.assertEqual(result["incremental_net_cash_vs_baseline"], 870)
        self.assertEqual(result["actions"][0]["applied_credit_amount"], 900)
        terms["credit_apply_date"] = "2026-10-07"
        self.assertEqual(calculate_return(facts, {"return_terms": terms})["feasibility"], "blocked")

    def test_purchase_and_promotion_duplicates_are_rejected(self):
        for sid, kind in (("S07", "purchase"), ("S06", "promotion")):
            with self.subTest(kind=kind):
                result = calculate_combination(self.facts(sid), {"sales_settlement_days": 0,
                    "combination": [{"type": kind, "quantity": 10}, {"type": kind, "quantity": 10}]})
                self.assertEqual(result["feasibility"], "blocked")

    def test_inputs_cannot_replace_identities_or_raise_contract_refund_ratio(self):
        with self.assertRaises(ValueError):
            calculate_purchase(self.facts("S07"), {"purchase_intent": {"store_id": "ST-001"}})
        self.assertEqual(calculate_return(self.facts("S05"), {"return_terms": {"refund_ratio_pct": 100}})["feasibility"], "blocked")

    def test_combination_prevents_repeated_inventory_and_target_demand(self):
        first = self.transfer()
        second = deepcopy(first)
        second["strategy_id"] = "another-transfer"
        result = validate_combination(self.facts(), [first, second], [first["strategy_id"], second["strategy_id"]])
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["errors"]), 2)
        self.assertIsNone(result["expected_net_cash"])

    def test_combination_recomputes_source_sales_once(self):
        request = {"sales_settlement_days": 0, "combination": [
            {"type": "transfer", "target_store_id": "ST-002", "quantity": 40},
            {"type": "transfer", "target_store_id": "ST-004", "quantity": 10}]}
        result = calculate_combination(self.facts(), request)
        self.assertEqual(result["feasibility"], "feasible")
        self.assertEqual(len(result["children"]), 2)
        self.assertEqual(result["allocations"][0]["quantity"], 50)
        independent = sum(c["details"]["cash_comparison"]["proposed"]["expected_net_cash"] for c in result["children"])
        source_once = result["details"]["retained_sales"][0]["expected_sales_revenue"]
        self.assertEqual(independent - result["expected_net_cash"], source_once)
        self.assertEqual(result["execution_cost"], 90)
        self.assertIsNone(result["allocated_qty"])

    def test_comparison_accounts_for_displaced_existing_target_sales(self):
        facts = self.facts()
        source = next(r for r in facts["tables"]["inventory"] if r["lot_id"] == "LOT-001-001")
        source["sellable_until"] = "2026-11-01"
        # Earlier-expiry transferred goods take demand from existing target lots.
        target = next(r for r in facts["tables"]["inventory"] if r["lot_id"] == "LOT-002-001")
        target["quantity"] = 80
        candidate = self.transfer(facts, quantity=10)
        self.assertEqual(candidate["feasibility"], "feasible")
        raw_batch_delta = candidate["expected_net_cash"] - compare_options(facts, {"sales_settlement_days": 0})["baseline"]["expected_net_cash"]
        self.assertLess(candidate["incremental_net_cash_vs_baseline"], raw_batch_delta)

    def test_promotion_and_return_compare_against_their_full_affected_baseline(self):
        result = compare_options(self.facts("S06"), {"sales_settlement_days": 0})
        promotion = next(c for c in result["candidates"] if c["type"] == "promotion")
        self.assertIn("cash_comparison", promotion["details"])
        self.assertIsNotNone(promotion["incremental_net_cash_vs_baseline"])
        self.assertEqual(result["recommended_strategy_id"], "retain")

    def test_combination_overlap_blocked_before_cash_is_summed(self):
        result = calculate_combination(self.facts(), {"sales_settlement_days": 0, "combination": [
            {"type": "transfer", "target_store_id": "ST-002", "quantity": 80},
            {"type": "transfer", "target_store_id": "ST-002", "quantity": 80}]})
        self.assertEqual(result["feasibility"], "blocked")
        self.assertIsNone(result["expected_net_cash"])

    def test_future_shipment_is_not_available_before_arrival(self):
        facts = self.facts("S07")
        shipment = next(r for r in facts["tables"]["in_transit"] if r["shipment_line_id"] == "SHIP-002")
        shipment["expected_arrival_at"] = "2026-11-01T12:00:00+08:00"
        result = calculate_purchase(facts)
        self.assertEqual(result["details"]["recommended_quantity"], 90)

    def test_invalid_promotional_overlap_and_return_quantity(self):
        facts = self.facts("S06")
        facts["tables"]["promotion_stages"][1]["start_date"] = "2026-10-07"
        self.assertEqual(calculate_promotion(facts)["feasibility"], "blocked")
        self.assertEqual(calculate_return(self.facts("S05"), {"quantity": 101})["feasibility"], "blocked")

    def test_cash_window_deduplicates_without_reusing_outside_period_events(self):
        event = {"event_id": "a", "amount": 50, "direction": "in", "event_date": "2026-10-04"}
        old = {**event, "event_id": "old", "event_date": "2026-10-02"}
        future = {**event, "event_id": "end", "event_date": "2026-10-17"}
        result = simulate_cash([], [event, event, old, future], start_date="2026-10-03", end_date="2026-10-17")
        self.assertEqual(result["proposed"]["expected_net_cash"], 50)
        with self.assertRaises(ValueError):
            simulate_cash([], [event, {**event, "amount": 60}], start_date="2026-10-03", end_date="2026-10-17")

    def test_cash_missing_amount_and_date_retains_partial_subtotal(self):
        events = [{"event_id": "a", "amount": 20, "direction": "in", "event_date": "2026-10-05"},
                  {"event_id": "b", "amount": None, "direction": "out", "event_date": "2026-10-06"}]
        result = simulate_cash([], events, start_date="2026-10-03", end_date="2026-10-17")
        self.assertIsNone(result["proposed"]["expected_net_cash"])
        self.assertEqual(result["proposed"]["known_cash_in"], 20)


if __name__ == "__main__":
    unittest.main()
