"""Unit tests for agency-level expenditure checks in scripts/validate.py."""

from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.parse_book import ROOT_DIR
from scripts.validate import validate_year


def _setup_temp_year(tmp_dir: Path, year: str) -> Path:
    (tmp_dir / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_dir / "data").mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT_DIR / "raw" / year, tmp_dir / "raw" / year)
    shutil.copytree(ROOT_DIR / "data" / year, tmp_dir / "data" / year)
    shutil.copy2(ROOT_DIR / "data" / "corrections.csv", tmp_dir / "data" / "corrections.csv")
    return tmp_dir


class TestValidateAgencyChecks(unittest.TestCase):
    def test_agency_checks_pass_for_114_115_116(self) -> None:
        expected = {
            "114": (True, 25_950_000, 30_871_000),
            "115": (False, 26_617_000, 32_661_000),
            "116": (False, 29_021_000, 36_207_000),
        }
        for year, (partial, council_yuan, pooled_yuan) in expected.items():
            with self.subTest(year=year):
                res = validate_year(year, ROOT_DIR, partial=partial)
                checks = {c["科目名稱"]: c for c in res["expenditure_agency_checks"]}
                self.assertEqual(set(checks.keys()), {"代表會主管", "統籌支撥科目"})

                council = checks["代表會主管"]
                self.assertTrue(council["passed"])
                self.assertEqual(council["target_元"], council_yuan)
                self.assertEqual(council["plans_sum_元"], council_yuan)
                self.assertEqual(council["diff_元"], 0)
                self.assertEqual(council["status"], "通過")

                pooled = checks["統籌支撥科目"]
                self.assertTrue(pooled["passed"])
                self.assertEqual(pooled["target_元"], pooled_yuan)
                self.assertEqual(pooled["plans_sum_元"], pooled_yuan)
                self.assertEqual(pooled["diff_元"], 0)
                self.assertEqual(pooled["status"], "通過")

    def test_agency_check_fails_when_summary_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = _setup_temp_year(Path(tmp), "114")
            summary_path = tmp_root / "data" / "114" / "summary.csv"
            with summary_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
                fieldnames = list(rows[0].keys())

            for r in rows:
                if (
                    r["source_table"] == "歲出機關別預算比較總表"
                    and r["科目名稱"] == "代表會主管"
                ):
                    r["本年度"] = str(int(r["本年度"]) + 1000)

            with summary_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            res = validate_year("114", tmp_root, partial=True)
            checks = {c["科目名稱"]: c for c in res["expenditure_agency_checks"]}
            self.assertFalse(checks["代表會主管"]["passed"])
            self.assertEqual(checks["代表會主管"]["diff_元"], -1000)
            self.assertIn("失敗", checks["代表會主管"]["status"])
            self.assertTrue(checks["統籌支撥科目"]["passed"])

    def test_agency_check_fails_when_plans_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = _setup_temp_year(Path(tmp), "114")
            plans_path = tmp_root / "data" / "114" / "plans.csv"
            with plans_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
                fieldnames = list(rows[0].keys())

            for r in rows:
                if r["政事別"] == "退休撫卹支出":
                    r["總額"] = str(int(r["總額"]) + 500)
                    break

            with plans_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            res = validate_year("114", tmp_root, partial=True)
            checks = {c["科目名稱"]: c for c in res["expenditure_agency_checks"]}
            self.assertFalse(checks["統籌支撥科目"]["passed"])
            self.assertEqual(checks["統籌支撥科目"]["diff_元"], 500)
            self.assertIn("失敗", checks["統籌支撥科目"]["status"])
            self.assertTrue(checks["代表會主管"]["passed"])


if __name__ == "__main__":
    unittest.main()
