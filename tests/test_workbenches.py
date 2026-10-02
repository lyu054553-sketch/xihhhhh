"""本轮工作台纵向闭环的确定性回归。"""

import base64
import io
import os
import tempfile
import unittest

from openpyxl import Workbook

from backend.api import DataImportInput, _diagnosis_report, _read_import_rows, _risk_factors, _work_item_copy
from backend.api import _transfer_network
from backend.domain import (
    calculate_expiry_rescue,
    calculate_procurement_brake,
    compare_sales,
    calculate_transfer,
    validate_action_bundle,
)
from backend.store import Store


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp.close()
        self.store = Store(self.temp.name)
        self.store.seed_demo()

    def tearDown(self):
        self.store.close()
        os.unlink(self.temp.name)

    def test_transfer_quantity_changes_calculation_and_blocks_limits(self):
        input_data = self.store.default_workbench_input("transfer", 1)
        baseline = calculate_transfer(input_data)
        self.assertTrue(baseline["valid"])
        changed = dict(input_data, quantity=50)
        self.assertNotEqual(baseline["before_after"]["target"]["on_hand_after"], calculate_transfer(changed)["before_after"]["target"]["on_hand_after"])
        blocked = calculate_transfer(dict(input_data, quantity=100))
        self.assertFalse(blocked["valid"])
        self.assertIn("超出调出门店可调数量", "；".join(blocked["errors"]))

    def test_expiry_quantity_conservation_and_procurement_payment_are_separate(self):
        expiry = self.store.default_workbench_input("expiry-rescue", 3)
        self.assertFalse(calculate_expiry_rescue(dict(expiry, promo_qty=90, transfer_qty=40))["valid"])
        procurement = calculate_procurement_brake(self.store.default_workbench_input("procurement-brake", 4))
        self.assertEqual(procurement["inventory_position"]["current_inventory"], 80)
        self.assertEqual(procurement["inventory_position"]["in_transit_qty"], 40)
        self.assertIsNotNone(procurement["payment"]["deferred_payment_pressure"])

    def test_draft_persists_and_shared_lot_cannot_be_double_allocated(self):
        input_data = self.store.default_workbench_input("transfer", 1)
        input_data["quantity"] = 41
        self.store.mark_workbench_dirty("transfer", 1, input_data)
        persisted = Store(self.temp.name).workbench_draft("transfer", 1)
        self.assertEqual(persisted["status"], "needs_recalculation")
        self.assertEqual(int(persisted["input"]["quantity"]), 41)
        conflict = validate_action_bundle(
            [{"lot_id": "LOT-A", "quantity": 30, "type": "expiry_rescue"}, {"lot_id": "LOT-A", "quantity": 30, "type": "expiry_rescue"}],
            available_by_lot={"LOT-A": 50}, allowed_routes=[],
        )
        self.assertFalse(conflict["valid"])

    def test_erp_csv_and_xlsx_are_parsed_for_field_validation(self):
        csv_payload = DataImportInput(filename="库存.csv", content="sku,store,inventory_qty\nSKU-1,西湖店,12\n")
        rows, headers, error = _read_import_rows(csv_payload)
        self.assertIsNone(error)
        self.assertEqual(headers, ["sku", "store", "inventory_qty"])
        self.assertEqual(rows[0]["inventory_qty"], "12")

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["sku", "store", "batch", "expiry_date"])
        sheet.append(["SKU-2", "拱墅店", "LOT-1", "2026-12-31"])
        output = io.BytesIO()
        workbook.save(output)
        xlsx_payload = DataImportInput(filename="效期.xlsx", data_kind="expiry", file_base64=base64.b64encode(output.getvalue()).decode())
        rows, headers, error = _read_import_rows(xlsx_payload)
        self.assertIsNone(error)
        self.assertEqual(headers, ["sku", "store", "batch", "expiry_date"])
        self.assertEqual(rows[0]["batch"], "LOT-1")

    def test_diagnosis_keeps_confirmed_anomaly_separate_from_unproven_causes(self):
        risk = self.store.risk(1)
        comparison = compare_sales(risk["sales_30"], risk["comparison"])
        report = _diagnosis_report(risk, comparison)
        factors = _risk_factors(risk)
        self.assertIn("已确认", report["conclusion"])
        self.assertIn("尚不能确认", report["cannot_conclude"])
        pricing = next(item for item in factors if item["label"] == "定价不合理")
        self.assertEqual(pricing["evidence_level"], "insufficient")
        customer = next(item for item in factors if item["label"] == "门店客群不匹配")
        self.assertEqual(customer["evidence_level"], "partial")

    def test_transfer_network_and_expiry_queue_inputs_are_real_calculable_records(self):
        transfer_input = self.store.default_workbench_input("transfer", 1)
        network = _transfer_network(transfer_input)
        self.assertEqual(len(network), 50)
        self.assertEqual(network[0]["name"], "余杭未来店")
        self.assertIsNotNone(network[0]["calculation"]["economic"]["potential_loss_without_transfer"])
        expiry_risks = [item for item in self.store.risks() if item["risk_type"] == "促销"]
        self.assertEqual(len(expiry_risks), 7)
        self.assertEqual(self.store.default_workbench_input("expiry-rescue", 6)["product"], "海盐薯片分享装 80g×8")

    def test_today_work_copy_states_store_product_action_and_reason(self):
        transfer = self.store.risk(1)
        title, reason = _work_item_copy(transfer)
        self.assertEqual(title, "西湖文三店 · 每日坚果礼盒 750g 滞销待调拨")
        self.assertIn("库存 120 件", reason)
        self.assertIn("预计需 168 天售完", reason)

        purchase = self.store.risk(4)
        title, reason = _work_item_copy(purchase)
        self.assertIn("待暂停或减量采购", title)
        self.assertIn("近 30 天仅销售 14 件", reason)


if __name__ == "__main__":
    unittest.main()
