"""Unit tests for Slice S2 (expenditure parsing and validation in parse_book.py and validate.py)."""

from __future__ import annotations

import csv
import unittest
from collections import defaultdict
from pathlib import Path

from scripts.parse_book import (
    EXPENDITURE_FIELDNAMES,
    PLANS_FIELDNAMES,
    ROOT_DIR,
    load_corrections,
    parse_book,
    parse_part3_expenditure,
    parse_single_amount,
    parse_toc,
)
from scripts.validate import validate_year


class TestS2Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parse_result = parse_book("116", ROOT_DIR)
        cls.val_result = validate_year("116", ROOT_DIR)
        cls.plans_csv = ROOT_DIR / "data" / "116" / "plans.csv"
        cls.expenditure_csv = ROOT_DIR / "data" / "116" / "expenditure_items.csv"
        cls.corrections_csv = ROOT_DIR / "data" / "corrections.csv"
        cls.report_md = ROOT_DIR / "reports" / "validate_116.md"

        with cls.plans_csv.open("r", encoding="utf-8", newline="") as f:
            cls.plans_rows = list(csv.DictReader(f))
        with cls.expenditure_csv.open("r", encoding="utf-8", newline="") as f:
            cls.expenditure_rows = list(csv.DictReader(f))

    def test_a_expenditure_header_count_and_pages(self) -> None:
        """驗證歲出明細表頭數 = 96（對應目錄 p61–p156），不相等時報錯中止。"""
        self.assertEqual(self.val_result["expenditure_header_count"], 96)
        self.assertEqual(len(self.plans_rows), 49)

        with self.plans_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        self.assertEqual(header, PLANS_FIELDNAMES)

        with self.expenditure_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            exp_header = next(reader)
        self.assertEqual(exp_header, EXPENDITURE_FIELDNAMES)

        # Page coverage: first plan starts at p61, last plan ends at p156, contiguous pages
        self.assertEqual(int(self.plans_rows[0]["page_start"]), 61)
        self.assertEqual(int(self.plans_rows[-1]["page_end"]), 156)
        for i in range(len(self.plans_rows) - 1):
            curr_end = int(self.plans_rows[i]["page_end"])
            next_start = int(self.plans_rows[i + 1]["page_start"])
            self.assertEqual(next_start, curr_end + 1)

        # Verify header count mismatch raises ValueError
        part1_text = (ROOT_DIR / "raw" / "116" / "part1.md").read_text(encoding="utf-8")
        part3_text = (ROOT_DIR / "raw" / "116" / "part3.md").read_text(encoding="utf-8")
        toc = parse_toc(part1_text)
        corrupted_part3 = part3_text.replace("歲出計畫說明提要", "已移除歲出表頭", 1)
        with self.assertRaises(ValueError):
            parse_part3_expenditure(corrupted_part3, "116", toc, corrections={})

    def test_b_use_subtotals_and_plan_totals(self) -> None:
        """驗證每個用途別明細加總 = 用途別小計，且用途別小計加總 = 計畫總額。"""
        use_checks = self.val_result["expenditure_use_checks"]
        plan_checks = self.val_result["expenditure_plan_checks"]

        self.assertEqual(len(plan_checks), 49)
        self.assertGreater(len(use_checks), 200)

        failed_uses = [u for u in use_checks if u["failed"]]
        self.assertEqual(failed_uses, [], f"Failed use checks: {failed_uses}")

        failed_plans = [p for p in plan_checks if p["failed"]]
        self.assertEqual(failed_plans, [], f"Failed plan checks: {failed_plans}")

        self.assertTrue(all(u["passed"] for u in use_checks))
        self.assertTrue(all(p["passed"] for p in plan_checks))

        for p in plan_checks:
            self.assertEqual(p["use_subtotal_sum_元"], p["header_budget_元"])
            self.assertEqual(p["detail_sum_元"], p["header_budget_元"])

    def test_c_function_totals_and_grand_total(self) -> None:
        """驗證計畫總額按政事別（項、款）加總 = part1 歲出政事別預算總表，總計 321,081 千元（321,081,000 元）。"""
        self.assertEqual(self.val_result["expected_exp_grand_total_yuan"], 321_081_000)
        self.assertEqual(self.val_result["total_exp_plan_yuan"], 321_081_000)
        self.assertEqual(self.val_result["total_exp_use_yuan"], 321_081_000)
        self.assertEqual(self.val_result["total_exp_detail_yuan"], 321_081_000)

        hsiang_checks = self.val_result["expenditure_hsiang_checks"]
        kuan_checks = self.val_result["expenditure_kuan_checks"]
        self.assertEqual(len(hsiang_checks), 16)
        self.assertEqual(len(kuan_checks), 7)

        for hc in hsiang_checks:
            self.assertTrue(hc["plan_passed"], f"政事別項計畫加總不符: {hc}")
            self.assertTrue(hc["use_passed"], f"政事別項用途別加總不符: {hc}")
            self.assertTrue(hc["detail_passed"], f"政事別項明細加總不符: {hc}")
            self.assertEqual(hc["detail_status"], "通過")

        for kc in kuan_checks:
            self.assertTrue(kc["plan_passed"], f"政事別款計畫加總不符: {kc}")
            self.assertTrue(kc["use_passed"], f"政事別款用途別加總不符: {kc}")
            self.assertTrue(kc["detail_passed"], f"政事別款明細加總不符: {kc}")
            self.assertEqual(kc["detail_status"], "通過")

    def test_d_numeric_anomalies_and_spot_checks(self) -> None:
        """驗證無未登記數字異常、無未套用修正，且已知 OCR 異常計畫展開正確。"""
        self.assertEqual(len(self.val_result["unregistered_anomalies"]), 0)
        self.assertEqual(len(self.val_result["unapplied_corrections"]), 0)

        for r in self.expenditure_rows:
            u_val, ok_u = parse_single_amount(r["unit_price"], allow_empty=False)
            a_val, ok_a = parse_single_amount(r["amount_元"], allow_empty=False)
            self.assertTrue(ok_u and u_val is not None and u_val > 0, f"Invalid unit_price in {r}")
            self.assertTrue(ok_a and a_val is not None and a_val > 0, f"Invalid amount_元 in {r}")
            self.assertRegex(r["用途別_code"], r"^\d{4}$")
            self.assertFalse(r["用途別_code"].endswith("00"))
            self.assertTrue(r["經費來源"].strip() != "", f"Empty 經費來源 in {r}")

        # Verify without corrections, expenditure parser flags anomalies
        part1_text = (ROOT_DIR / "raw" / "116" / "part1.md").read_text(encoding="utf-8")
        part3_text = (ROOT_DIR / "raw" / "116" / "part3.md").read_text(encoding="utf-8")
        toc = parse_toc(part1_text)
        _, _, _, raw_exp_anomalies, _, _ = parse_part3_expenditure(
            part3_text, "116", toc, corrections={}
        )
        self.assertGreaterEqual(len(raw_exp_anomalies), 15)

        # Spot check specific OCR-repaired plans
        by_plan = defaultdict(list)
        for r in self.expenditure_rows:
            by_plan[r["plan_code"]].append(r)

        # p61-62: 33120010101 rowspan shift on 1055 保險 (70,000 belongs to 1050, 4 items sum to 560,000 in 1055)
        items_1050 = [r for r in by_plan["33120010101"] if r["用途別_code"] == "1050"]
        items_1055 = [r for r in by_plan["33120010101"] if r["用途別_code"] == "1055"]
        self.assertEqual([int(r["amount_元"]) for r in items_1050], [370_000, 70_000])
        self.assertEqual(int(items_1050[1]["page"]), 62)
        self.assertEqual([int(r["amount_元"]) for r in items_1055], [250_000, 100_000, 110_000, 100_000])

        # p87: 40120010101 2012 土地租金 (7 items summing to 413,000)
        items_2012 = [r for r in by_plan["40120010101"] if r["用途別_code"] == "2012"]
        self.assertEqual(
            [int(r["amount_元"]) for r in items_2012],
            [99_600, 120_000, 5_000, 50_000, 12_100, 126_000, 300],
        )

        # p119: 59120019201 (2 items: 5,165,220 and 780)
        self.assertEqual(
            [int(r["amount_元"]) for r in by_plan["59120019201"]],
            [5_165_220, 780],
        )

        # p135: 51120010201 dept corrected from 幼兒圈 to 幼兒園
        plan_5112 = next(p for p in self.plans_rows if p["plan_code"] == "51120010201")
        self.assertEqual(plan_5112["dept"], "幼兒園")

        report_text = self.report_md.read_text(encoding="utf-8")
        self.assertIn("歲出計畫說明提要與各項費用明細表", report_text)
        self.assertIn("321,081,000", report_text)


if __name__ == "__main__":
    unittest.main()
