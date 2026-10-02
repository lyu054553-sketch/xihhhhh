import unittest

from backend.domain import TEACHER_BASELINE_VERSION, teacher_baseline


class TeacherBaselineTests(unittest.TestCase):
    def base(self, **overrides):
        row = {
            "inventory_amount": 1200,
            "available_qty": 120,
            "sales_30": 10,
            "sales_cost_30": 300,
            "sales_90": 30,
            "stat_class": "A",
            "purchase_status": "正常采购",
            "stockout": False,
            "near_stockout": False,
        }
        row.update(overrides)
        return row

    def test_p1_stop_and_no_sales(self):
        result = teacher_baseline(self.base(sales_cost_30=0, sales_90=0, purchase_status="停止采购"))
        self.assertEqual(result["calculation_version"], TEACHER_BASELINE_VERSION)
        self.assertEqual(result["priority"], "P1")
        self.assertEqual(result["trigger_reason"], "停采且90天无销售")
        self.assertTrue(result["candidate"])
        self.assertEqual(result["suggested_reduction_amount"], 1200.0)

    def test_p2_ratio_over_three(self):
        result = teacher_baseline(self.base(inventory_amount=1201, sales_cost_30=300))
        self.assertEqual(result["priority"], "P2")
        self.assertEqual(result["trigger_reason"], "降库存存销比超过3")
        self.assertEqual(result["teacher_ratio"], 12.0)
        self.assertAlmostEqual(result["reduction_ratio"], 4.0033333333)

    def test_p3_ratio_over_target_but_not_three(self):
        result = teacher_baseline(self.base(inventory_amount=800, sales_cost_30=300), target_ratio=2)
        self.assertEqual(result["priority"], "P3")
        self.assertEqual(result["trigger_reason"], "超过设定目标存销比")

    def test_stockout_and_near_stockout_are_excluded(self):
        for flags in ({"stockout": True}, {"near_stockout": True}):
            result = teacher_baseline(self.base(inventory_amount=2000, **flags))
            self.assertTrue(result["eligible"] is False)
            self.assertFalse(result["candidate"])
            self.assertIsNone(result["priority"])

    def test_teacher_ratio_uses_roundup_before_and_after_division(self):
        result = teacher_baseline(self.base(inventory_amount=30, available_qty=3, sales_30=0, sales_90=1, sales_cost_30=3))
        self.assertEqual(result["monthly_sales"], 0.4)
        self.assertEqual(result["teacher_ratio"], 7.5)
        self.assertEqual(result["reduction_ratio"], 10.0)

    def test_missing_sales_does_not_become_zero_sales(self):
        result = teacher_baseline(self.base(sales_90=None, sales_cost_30=None))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["candidate"])
        self.assertIn("sales_90", result["missing_fields"])
        self.assertIn("sales_cost_30", result["missing_fields"])


if __name__ == "__main__":
    unittest.main()
