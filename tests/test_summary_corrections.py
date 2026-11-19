"""p3「收支簡明比較分析表」科目名稱修正接口，以及 114 的 3 格錯字修正（賬→賸、鐘→鍾）。"""

from __future__ import annotations

import copy
import csv
import unittest
from pathlib import Path

from scripts.parse_book import load_corrections, load_toc, parse_part1_summary

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "raw" / "114"
TABLE = "收支簡明比較分析表"
LOCATORS = {
    f"{TABLE}:r4": "預計移用以前年度歲計賸餘調節因應數",
    f"{TABLE}:r8": "收支賸餘",
}


def _parse(corrections):
    text = (RAW_DIR / "part1.md").read_text(encoding="utf-8")
    toc = load_toc(RAW_DIR, text)
    return parse_part1_summary(text, "114", toc, corrections, partial=True)


class TestSummarySubjectCorrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corrections = load_corrections(ROOT / "data" / "corrections.csv", "114")

    def test_registered_corrections_apply_and_rename_rows(self) -> None:
        rows, _, applied, _ = _parse(self.corrections)
        applied_keys = {(int(c["page"]), c["locator"], c["field"]) for c in applied}
        names = {r["科目名稱"] for r in rows if r["source_table"] == TABLE}
        for locator, expected in LOCATORS.items():
            self.assertIn((3, locator, "科目名稱"), applied_keys)
            self.assertIn(expected, names)
        self.assertFalse([n for n in names if "賬" in n])

    def test_old_mismatch_is_not_applied(self) -> None:
        corrections = copy.deepcopy(self.corrections)
        key = (3, f"{TABLE}:r8", "科目名稱")
        corrections[key]["old"] = "三、收支賬餘X"
        rows, _, applied, _ = _parse(corrections)
        applied_keys = {(int(c["page"]), c["locator"], c["field"]) for c in applied}
        self.assertNotIn(key, applied_keys)
        names = {r["科目名稱"] for r in rows if r["source_table"] == TABLE}
        self.assertIn("收支賬餘", names)  # 未套用 → 保留 OCR 原文
        self.assertIn(f"{TABLE}:r4", {k[1] for k in applied_keys})  # 另一筆不受影響

    def test_only_target_names_differ_from_uncorrected_parse(self) -> None:
        corrected, _, _, _ = _parse(self.corrections)
        plain, _, _, _ = _parse({k: v for k, v in self.corrections.items() if not k[1].startswith(TABLE)})
        self.assertEqual(len(corrected), len(plain))
        diffs = [(a["科目名稱"], b["科目名稱"]) for a, b in zip(plain, corrected) if a != b]
        self.assertEqual(
            sorted(diffs),
            sorted(
                [
                    ("預計移用以前年度歲計賬餘調節因應數", "預計移用以前年度歲計賸餘調節因應數"),
                    ("收支賬餘", "收支賸餘"),
                ]
            ),
        )


class TestP87Surname(unittest.TestCase):
    def test_p87_land_rent_row_uses_printed_surname(self) -> None:
        with (ROOT / "data" / "114" / "expenditure_items.csv").open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["page"] == "87" and "祭祀公業法人屏東縣" in r["說明"]]
        self.assertEqual(len(rows), 1)
        self.assertIn("屏東縣鍾德重有土地", rows[0]["說明"])
        self.assertNotIn("鐘德重", rows[0]["說明"])


if __name__ == "__main__":
    unittest.main()
