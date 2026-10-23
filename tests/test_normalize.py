import unittest
from datetime import datetime
from pathlib import Path

from app.analyze import normalize_transactions
from app.ingest import file_to_text
from app.totals import compute_totals


class NormalizeTests(unittest.TestCase):
    def test_model_json_is_stored_as_given(self):
        items, skipped = normalize_transactions({
            "transactions": [
                {"time": "2026-10-01 08:00:00", "direction": "expense", "amount": "18.50",
                 "category": "餐饮", "title": "早饭", "include": True},
                {"time": "2026-10-02", "direction": "ignore", "amount": "0", "category": "其他", "title": "占位"},
                {"time": "不是日期", "direction": "expense", "amount": "1", "title": "丢掉"},
            ]
        })
        self.assertEqual(skipped, 1)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["included"])
        self.assertEqual(items[0]["amount_cents"], 1850)
        self.assertFalse(items[1]["included"])
        totals = compute_totals(items)
        self.assertEqual(totals["expense_cents"], 1850)
        self.assertEqual(totals["net_expense_cents"], 1850)
        self.assertEqual(totals["excluded_count"], 1)

    def test_repayment_counts_as_expense(self):
        items, skipped = normalize_transactions({
            "transactions": [
                {"time": "2026-10-03 09:00:00", "direction": "还款", "amount": "800",
                 "category": "还款", "title": "花呗还款", "include": True},
            ]
        })
        self.assertEqual(skipped, 0)
        self.assertEqual(items[0]["direction"], "expense")
        self.assertTrue(items[0]["included"])
        self.assertEqual(compute_totals(items)["expense_cents"], 80000)

    def test_bill_file_becomes_text_without_local_classification(self):
        path = Path("/Users/huitingfeng/Downloads/支付宝交易明细(20260923-20261023)(1).csv")
        if not path.is_file():
            self.skipTest("sample bill is not in Downloads")
        kind, text = file_to_text(path.read_bytes(), path.name)
        self.assertEqual(kind, "csv")
        self.assertIn("交易时间", text)
        self.assertNotIsInstance(text, list)
        self.assertGreater(len(text), 1000)


if __name__ == "__main__":
    unittest.main()
