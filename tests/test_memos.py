"""Unit tests for data/memos.csv, data/pdf_sources.csv, and V1-V7 validation in scripts/memos.py & scripts/validate.py."""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.memos import load_memos, load_pdf_sources, validate_memos
from scripts.validate import validate_year


def _mutate_memo_csv(
    memos_path: Path,
    target_id: str,
    updates: dict[str, str],
    duplicate_first: bool = False,
) -> None:
    with memos_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for row in rows:
        if row["memo_id"] == target_id:
            row.update(updates)
            if duplicate_first:
                rows.append(dict(row))
            break

    with memos_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _setup_temp_repo(tmp_dir: Path) -> Path:
    """Create a minimal isolated copy of the repo (year 116) for negative CLI/validation tests."""
    shutil.copytree(ROOT_DIR / "scripts", tmp_dir / "scripts")
    (tmp_dir / "data").mkdir()
    shutil.copy2(ROOT_DIR / "data" / "memos.csv", tmp_dir / "data" / "memos.csv")
    shutil.copy2(ROOT_DIR / "data" / "pdf_sources.csv", tmp_dir / "data" / "pdf_sources.csv")
    shutil.copy2(ROOT_DIR / "data" / "corrections.csv", tmp_dir / "data" / "corrections.csv")
    shutil.copytree(ROOT_DIR / "data" / "116", tmp_dir / "data" / "116")
    shutil.copytree(ROOT_DIR / "raw" / "116", tmp_dir / "raw" / "116")
    if (ROOT_DIR / "docs" / "evidence" / "116").is_dir():
        shutil.copytree(ROOT_DIR / "docs" / "evidence" / "116", tmp_dir / "docs" / "evidence" / "116")
    (tmp_dir / "reports").mkdir()
    return tmp_dir


class TestMemosRealData(unittest.TestCase):
    def test_real_memos_and_pdf_sources_non_empty(self) -> None:
        memos = load_memos(ROOT_DIR)
        sources = load_pdf_sources(ROOT_DIR)
        self.assertGreaterEqual(len(memos), 28)
        self.assertGreaterEqual(len(sources), 8)

    def test_real_years_pass_v1_to_v7(self) -> None:
        for year in ("114", "115", "116"):
            with self.subTest(year=year):
                res = validate_memos(year, root_dir=ROOT_DIR)
                self.assertGreater(len(res["results"]), 0)
                self.assertEqual(res["failed_count"], 0, res["results"])

    def test_report_omits_section_9_when_year_has_no_memos(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            memos_path = tmp_root / "data" / "memos.csv"
            with memos_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = [r for r in reader if r["year"] != "116"]
            with memos_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            res = validate_year("116", root_dir=tmp_root)
            self.assertEqual(res["memo_validation"]["results"], [])
            report_text = (tmp_root / "reports" / "validate_116.md").read_text(encoding="utf-8")
            self.assertNotIn("## 9. 備註檢查", report_text)


class TestMemosNegativeRules(unittest.TestCase):
    def _run_cli_expect_fail(self, tmp_root: Path, expected_rule: str) -> None:
        proc = subprocess.run(
            [sys.executable, str(tmp_root / "scripts" / "validate.py"), "116"],
            cwd=str(tmp_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        report_text = (tmp_root / "reports" / "validate_116.md").read_text(encoding="utf-8")
        self.assertIn("## 9. 備註檢查", report_text)
        self.assertIn(expected_rule, report_text)

    def test_v1_duplicate_memo_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {},
                duplicate_first=True,
            )
            self._run_cli_expect_fail(tmp_root, "V1: memo_id 重複")

    def test_v1_invalid_enum(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"type": "unknown_type"},
            )
            self._run_cli_expect_fail(tmp_root, "V1: type 不合法")

    def test_v2_nonexistent_locator(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"locator": "99999999999:1"},
            )
            self._run_cli_expect_fail(tmp_root, "V2:")

    def test_v2_page_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"page": "60", "pdf_page": "26"},
            )
            self._run_cli_expect_fail(tmp_root, "V2: page=60")

    def test_v3_data_text_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"data_text": "錯一字的測試字串"},
            )
            self._run_cli_expect_fail(tmp_root, "V3: data_text")

    def test_v4_print_typo_missing_suggested_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"suggested_text": ""},
            )
            self._run_cli_expect_fail(tmp_root, "V4:")

    def test_v5_pdf_page_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"pdf_page": "999"},
            )
            self._run_cli_expect_fail(tmp_root, "V5:")

    def test_v6_missing_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"evidence": "docs/evidence/116/does_not_exist.png"},
            )
            self._run_cli_expect_fail(tmp_root, "V6:")

    def test_v7_invalid_verified_on_date(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            _mutate_memo_csv(
                tmp_root / "data" / "memos.csv",
                "M116-0001",
                {"verified_on": "2026-02-30"},
            )
            self._run_cli_expect_fail(tmp_root, "V7:")


if __name__ == "__main__":
    unittest.main()
