"""Unit tests for Slice S1 (parse_book.py and validate.py)."""

from __future__ import annotations

import csv
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from scripts.parse_book import (
    CORRECTIONS_FIELDNAMES,
    ROOT_DIR,
    find_unapplied_corrections,
    load_corrections,
    parse_book,
    parse_html_table,
    parse_part3_revenue,
    parse_single_amount,
    parse_toc,
)
from scripts.validate import validate_year


class TestS1Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parse_result = parse_book("116", ROOT_DIR)
        cls.val_result = validate_year("116", ROOT_DIR)
        cls.summary_csv = ROOT_DIR / "data" / "116" / "summary.csv"
        cls.revenue_csv = ROOT_DIR / "data" / "116" / "revenue_items.csv"
        cls.corrections_csv = ROOT_DIR / "data" / "corrections.csv"
        cls.report_md = ROOT_DIR / "reports" / "validate_116.md"

        with cls.summary_csv.open("r", encoding="utf-8", newline="") as f:
            cls.summary_rows = list(csv.DictReader(f))
        with cls.revenue_csv.open("r", encoding="utf-8", newline="") as f:
            cls.revenue_rows = list(csv.DictReader(f))

    def test_a_revenue_pages_and_continuation(self) -> None:
        """(a) 頁碼逐筆等於 tests/fixtures/116_revenue_pages.csv；09120010102 續頁落在 53–57。"""
        fixture_path = ROOT_DIR / "tests" / "fixtures" / "116_revenue_pages.csv"
        with fixture_path.open("r", encoding="utf-8", newline="") as f:
            expected_pages = list(csv.DictReader(f))

        pages_by_code: dict[str, list[int]] = defaultdict(list)
        code_order: list[str] = []
        for r in self.revenue_rows:
            code = r["code"]
            if code not in pages_by_code:
                code_order.append(code)
            pages_by_code[code].append(int(r["page"]))

        self.assertEqual(len(code_order), 20)
        actual_pages = [
            {
                "code": code,
                "page_start": str(min(pages_by_code[code])),
                "page_end": str(max(pages_by_code[code])),
            }
            for code in code_order
        ]
        self.assertEqual(actual_pages, expected_pages)

        rows_53_57 = [r for r in self.revenue_rows if 53 <= int(r["page"]) <= 57]
        self.assertTrue(len(rows_53_57) > 0)
        self.assertTrue(all(r["code"] == "09120010102" for r in rows_53_57))
        self.assertEqual({int(r["page"]) for r in rows_53_57}, {53, 54, 55, 56, 57})

    def test_b_fine_items_sum_or_known_diff(self) -> None:
        """(b) 套用 corrections.csv 後，20 個細目明細加總 = 表頭預算金額，或明確以 _known_diff 登記為未解決差額。"""
        checks = self.val_result["fine_item_checks"]
        self.assertEqual(len(checks), 20)

        passed_codes = [c["code"] for c in checks if c["passed"]]
        self.assertEqual(len(passed_codes), 19)

        failed_codes = [c["code"] for c in checks if c["failed"]]
        self.assertEqual(failed_codes, [])

        unresolved = [c for c in checks if c["unresolved"]]
        self.assertEqual(len(unresolved), 1)
        u_item = unresolved[0]
        self.assertEqual(u_item["code"], "09120010102")
        self.assertEqual(u_item["detail_sum_元"], 36_414_792)
        self.assertEqual(u_item["header_budget_元"], 44_260_000)
        self.assertEqual(u_item["diff_元"], -7_845_208)

        kd_corr = u_item["known_diff_correction"]
        self.assertIsNotNone(kd_corr)
        self.assertEqual(kd_corr["field"], "_known_diff")
        self.assertEqual(int(kd_corr["old"]), -7_845_208)
        self.assertEqual(kd_corr["new"], "UNRESOLVED")
        self.assertTrue(kd_corr["reason"].strip() != "")

        report_text = self.report_md.read_text(encoding="utf-8")
        self.assertIn("## 摘要（未解決待查證項目）", report_text)
        self.assertIn("未解決，待使用者查證", report_text)

    def test_b_rejects_unregistered_or_mismatched_known_diff(self) -> None:
        """驗證若無 _known_diff 或 _known_diff 差額與實際不符，不會被其他修正掩蓋且視為未套用/失敗。"""
        part1_text = (ROOT_DIR / "raw" / "116" / "part1.md").read_text(encoding="utf-8")
        part3_text = (ROOT_DIR / "raw" / "116" / "part3.md").read_text(encoding="utf-8")
        toc = parse_toc(part1_text)
        all_corrs = load_corrections(self.corrections_csv, "116")

        # Case 1: _known_diff has wrong amount (-999 instead of -7845208)
        corrs_wrong_diff = dict(all_corrs)
        corrs_wrong_diff[(53, "09120010102", "_known_diff")] = {
            "year": "116",
            "page": "53",
            "locator": "09120010102",
            "field": "_known_diff",
            "old": "-999",
            "new": "UNRESOLVED",
            "reason": "錯誤差額測試",
        }
        _, _, _, rev_applied, _ = parse_part3_revenue(part3_text, "116", toc, corrs_wrong_diff)
        applied_fields = {(int(c["page"]), c["locator"], c["field"]) for c in rev_applied}
        self.assertNotIn((53, "09120010102", "_known_diff"), applied_fields)

    def test_c_zero_unregistered_numeric_anomalies_and_valid_amounts(self) -> None:
        """(c) 報告中「數字欄位異常、未登記修正」與「未套用修正」筆數皆為 0；已知 OCR 位置都變成合理的單一金額。"""
        self.assertEqual(len(self.val_result["unregistered_anomalies"]), 0)
        self.assertEqual(len(self.val_result["unapplied_corrections"]), 0)

        report_text = self.report_md.read_text(encoding="utf-8")
        self.assertIn("**數字欄位異常、未登記修正筆數**：**0**", report_text)
        self.assertIn("**已登記但因 `old` 與 raw 不符而未套用之修正筆數**：**0**", report_text)

        for r in self.revenue_rows:
            u_val, ok_u = parse_single_amount(r["unit_price"], allow_empty=False)
            a_val, ok_a = parse_single_amount(r["amount_元"], allow_empty=False)
            self.assertTrue(ok_u and u_val is not None and u_val > 0, f"Invalid unit_price in {r}")
            self.assertTrue(ok_a and a_val is not None and a_val > 0, f"Invalid amount_元 in {r}")

        by_code = defaultdict(list)
        for r in self.revenue_rows:
            by_code[r["code"]].append(r)

        self.assertEqual(int(by_code["01120011301"][0]["amount_元"]), 4_000_000)
        self.assertEqual(int(by_code["01120011501"][0]["amount_元"]), 1_200_000)
        self.assertEqual(int(by_code["07120010102"][0]["amount_元"]), 300_000)
        self.assertEqual(int(by_code["09120010102"][0]["unit_price"]), 149_475)
        self.assertEqual(int(by_code["09120010102"][0]["amount_元"]), 149_475)
        self.assertEqual(
            [int(x["amount_元"]) for x in by_code["10120010101"]],
            [50_000, 100_000],
        )
        self.assertEqual(
            [int(x["amount_元"]) for x in by_code["12120010204"]],
            [4_500_000, 666_000, 144_000],
        )

    def test_parse_single_amount_and_unregistered_anomalies(self) -> None:
        """驗證 parse_single_amount 對黏連數字回傳失敗，且無 corrections 時 parser 會標記異常。"""
        for bad in (
            "4,000,0004,000,000",
            "1,200,0001,200,000",
            "300,000300,000",
            "50,000100,000",
            "150,00050,000100,000",
            "5,310,0004,500,000",
            "",
            "-",
        ):
            val, ok = parse_single_amount(bad, allow_empty=False)
            self.assertFalse(ok, f"Expected {bad!r} to fail parse_single_amount")
            self.assertIsNone(val)

        for good, expected in (
            ("4,000,000", 4_000_000),
            ("-8,403", -8_403),
            ("25500", 25_500),
            ("654", 654),
        ):
            val, ok = parse_single_amount(good, allow_empty=False)
            self.assertTrue(ok)
            self.assertEqual(val, expected)

        part1_text = (ROOT_DIR / "raw" / "116" / "part1.md").read_text(encoding="utf-8")
        part3_text = (ROOT_DIR / "raw" / "116" / "part3.md").read_text(encoding="utf-8")
        toc = parse_toc(part1_text)
        _, _, anomalies, _, _ = parse_part3_revenue(part3_text, "116", toc, corrections={})
        self.assertGreaterEqual(len(anomalies), 10)

    def test_corrections_csv_format_and_validation(self) -> None:
        """驗證 corrections.csv 每列剛好 7 欄且 reason 非空，格式錯誤時 load_corrections 會拋出 ValueError。"""
        with self.corrections_csv.open("r", encoding="utf-8", newline="") as f:
            raw_rows = list(csv.reader(f))

        self.assertGreater(len(raw_rows), 1)
        self.assertEqual(raw_rows[0], CORRECTIONS_FIELDNAMES)
        for idx, row in enumerate(raw_rows[1:], start=2):
            self.assertEqual(len(row), 7, f"第 {idx} 列欄數 != 7: {row}")
            self.assertTrue(row[6].strip() != "", f"第 {idx} 列 reason 為空")

        # Verify load_corrections raises ValueError on unquoted comma (8 columns) or empty reason
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_csv_1 = Path(tmpdir) / "bad_cols.csv"
            bad_csv_1.write_text(
                "year,page,locator,field,old,new,reason\n"
                "116,39,01120011301:1,amount_元,100,200,未加引號,多出一欄\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_corrections(bad_csv_1, "116")

            bad_csv_2 = Path(tmpdir) / "empty_reason.csv"
            bad_csv_2.write_text(
                "year,page,locator,field,old,new,reason\n"
                "116,39,01120011301:1,amount_元,100,200,\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_corrections(bad_csv_2, "116")

        # Verify find_unapplied_corrections detects unused corrections
        fake_corr = {
            (99, "nonexistent:1", "amount_元"): {
                "year": "116",
                "page": "99",
                "locator": "nonexistent:1",
                "field": "amount_元",
                "old": "1",
                "new": "2",
                "reason": "測試未套用修正",
            }
        }
        self.assertEqual(len(find_unapplied_corrections(fake_corr, [])), 1)

    def test_d_revenue_grand_total_and_hierarchy(self) -> None:
        """(d) 歲入總額 312,678 千元，各款／項跟 part1 的歲入來源別預算總表一致（09120010102 標示為未解決）。"""
        self.assertEqual(self.val_result["expected_grand_total_yuan"], 312_678_000)
        self.assertEqual(self.val_result["total_kuan_header_yuan"], 312_678_000)
        self.assertEqual(self.val_result["grand_total_page"], 4)

        for hc in self.val_result["hsiang_checks"]:
            self.assertTrue(hc["header_passed"], f"項不符: {hc}")
            if hc["科目名稱"] != "上級政府補助收入":
                self.assertTrue(hc["detail_passed"], f"明細項不符: {hc}")
                self.assertEqual(hc["detail_status"], "通過")
            else:
                self.assertIn("未解決，待使用者查證", hc["detail_status"])
                self.assertIn("p53–p57 09120010102", hc["detail_status"])

        for kc in self.val_result["kuan_checks"]:
            self.assertTrue(kc["header_passed"], f"款不符: {kc}")
            if kc["科目名稱"] != "補助及協助收入":
                self.assertTrue(kc["detail_passed"], f"明細款不符: {kc}")
                self.assertEqual(kc["detail_status"], "通過")
            else:
                self.assertIn("未解決，待使用者查證", kc["detail_status"])
                self.assertIn("p53–p57 09120010102", kc["detail_status"])

    def test_e_revenue_header_count_matches_toc(self) -> None:
        """(e) 歲入明細的表頭數等於目錄頁數（24），不相等時報錯中止。"""
        self.assertEqual(self.val_result["revenue_header_count"], 24)
        self.assertEqual(len(self.val_result["part1_section_checks"]), 8)
        self.assertTrue(all(s["passed"] for s in self.val_result["part1_section_checks"]))

        part1_text = (ROOT_DIR / "raw" / "116" / "part1.md").read_text(encoding="utf-8")
        part3_text = (ROOT_DIR / "raw" / "116" / "part3.md").read_text(encoding="utf-8")
        toc = parse_toc(part1_text)
        corrupted_part3 = part3_text.replace("歲入項目說明提要", "已移除表頭", 1)
        with self.assertRaises(ValueError):
            parse_part3_revenue(corrupted_part3, "116", toc, corrections={})

    def test_f_summary_conflicts_and_spot_fixture(self) -> None:
        """(f) summary.csv 同時有兩筆上年度歲出（267,169、271,169），報告列為衝突；且逐筆符合 116_summary_spot.csv。"""
        exp_rows = [
            r
            for r in self.summary_rows
            if r["科目名稱"] == "歲出合計" and r["上年度"] != ""
        ]
        prev_year_vals = {int(r["上年度"]) for r in exp_rows}
        self.assertIn(267_169_000, prev_year_vals)
        self.assertIn(271_169_000, prev_year_vals)

        table_pages_267 = {(r["source_table"], int(r["page"])) for r in exp_rows if int(r["上年度"]) == 267_169_000}
        table_pages_271 = {(r["source_table"], int(r["page"])) for r in exp_rows if int(r["上年度"]) == 271_169_000}
        self.assertIn(("歲入歲出簡明比較分析表", 1), table_pages_267)
        self.assertIn(("收支簡明比較分析表", 3), table_pages_271)

        report_text = self.report_md.read_text(encoding="utf-8")
        self.assertIn("267,169", report_text)
        self.assertIn("271,169", report_text)

        spot_path = ROOT_DIR / "tests" / "fixtures" / "116_summary_spot.csv"
        with spot_path.open("r", encoding="utf-8", newline="") as f:
            spot_rows = list(csv.DictReader(f))

        self.assertEqual(len(spot_rows), 9)
        summary_index = {
            (r["year"], r["source_table"], r["款"], r["項"], r["科目名稱"]): r
            for r in self.summary_rows
        }
        for sr in spot_rows:
            key = (sr["year"], sr["source_table"], sr["款"], sr["項"], sr["科目名稱"])
            self.assertIn(key, summary_index, f"找不到 summary.csv 對應列: {key}")
            actual = summary_index[key]
            self.assertEqual(actual["page"], sr["page"])
            self.assertEqual(actual["本年度"], sr["本年度"])
            self.assertEqual(actual["上年度"], sr["上年度"])
            self.assertEqual(actual["前年度決算"], sr["前年度決算"])

    def test_html_table_rowspan_colspan_expansion(self) -> None:
        """驗證 HTML <table> rowspan / colspan 二維展開正確。"""
        sample = (
            "<table>"
            "<tr><td rowspan='2'>A</td><td colspan='2'>B</td></tr>"
            "<tr><td>C</td><td>D</td></tr>"
            "</table>"
        )
        grid = parse_html_table(sample)
        self.assertEqual(grid, [["A", "B", "B"], ["A", "C", "D"]])


if __name__ == "__main__":
    unittest.main()
