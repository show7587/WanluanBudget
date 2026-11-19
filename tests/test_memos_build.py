"""Unit tests for memos build output (memos.json, SQLite memos, index.json) and input hardening."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.build import build
from scripts.memos import MEMO_COLUMNS

BASELINE_SITE_JSON_SHA1 = {
    "114.json": "63d4330292acdaeb38bd1a81bf5234322b95bb24",
    "115.json": "7b552de886fe74bf0906cb37d61a9e83446693a0",
    "116.json": "ea485e0fffba5feaafa842bfb9f22467d37d789c",
    "compare_114_115.json": "151b7d627d53731f88e650680bbd81609f5f7e7c",
    "compare_115_116.json": "997a89ffc1931b84d0e4c3a116926816712afb7f",
    "compare.json": "997a89ffc1931b84d0e4c3a116926816712afb7f",
    "reference_114.json": "1e93e4e1d3457ff4a0be13e61823113d63cc1b5a",
    "search.json": "8c650e4c6d03427909c746f11a168b0a1ce5153f",
}


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _setup_temp_repo(tmp_dir: Path) -> Path:
    """Create an isolated copy of scripts, data (116), raw (116), and evidence (116)."""
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


class TestMemosBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.tmp_path = Path(cls._tmpdir.name)
        cls.out_dir = cls.tmp_path / "build"
        cls.site_dir = cls.tmp_path / "site" / "data"
        build(
            data_dir=ROOT_DIR / "data",
            out_dir=cls.out_dir,
            site_dir=cls.site_dir,
        )
        cls.sqlite_path = cls.out_dir / "budget.sqlite"
        cls.memos_json = json.loads((cls.site_dir / "memos.json").read_text(encoding="utf-8"))
        cls.index_json = json.loads((cls.site_dir / "index.json").read_text(encoding="utf-8"))
        cls.search_json = json.loads((cls.site_dir / "search.json").read_text(encoding="utf-8"))
        cls.reference_114 = json.loads((cls.site_dir / "reference_114.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_memos_json_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td2:
            p2 = Path(td2)
            build(data_dir=ROOT_DIR / "data", out_dir=p2 / "build", site_dir=p2 / "site")
            bytes1 = (self.site_dir / "memos.json").read_bytes()
            bytes2 = (p2 / "site" / "memos.json").read_bytes()
            self.assertEqual(bytes1, bytes2)

    def test_memos_json_structure_and_counts(self) -> None:
        years_dict = self.memos_json["years"]
        self.assertEqual(list(years_dict.keys()), ["114", "115", "116"])
        self.assertEqual(len(years_dict["114"]), 20)
        self.assertEqual(len(years_dict["115"]), 5)
        self.assertEqual(len(years_dict["116"]), 3)

        expected_keys = set(MEMO_COLUMNS) | {"target"}
        for y_str, items in years_dict.items():
            ids = [m["memo_id"] for m in items]
            self.assertEqual(ids, sorted(ids))
            for m in items:
                self.assertEqual(set(m.keys()), expected_keys)
                self.assertIsInstance(m["year"], int)
                self.assertIsInstance(m["page"], int)
                self.assertIsInstance(m["pdf_page"], int)
                self.assertEqual(str(m["year"]), y_str)

    def test_memos_targets_match_search_and_reference(self) -> None:
        search_ids = {doc["id"] for doc in self.search_json}
        ref_cells = {
            (t["page"], c["r"], c["c"])
            for t in self.reference_114["tables"]
            for c in t["cells"]
        }

        for items in self.memos_json["years"].values():
            for m in items:
                target = m["target"]
                scope = m["scope"]
                if scope in ("revenue_item", "expenditure_item", "plan", "summary"):
                    self.assertIn("search_id", target)
                    self.assertIn(target["search_id"], search_ids)
                elif scope == "reference_cell":
                    self.assertEqual(target["kind"], "reference")
                    self.assertIn((target["page"], target["row"], target["col"]), ref_cells)
                elif scope == "page":
                    self.assertEqual(target["kind"], "page")

    def test_plan_scope_target_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            memos_path = tmp_root / "data" / "memos.csv"
            with memos_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = [r for r in reader if r["year"] == "116"]
            rows.append(
                {
                    "memo_id": "M116-9999",
                    "year": "116",
                    "scope": "plan",
                    "page": "78",
                    "locator": "32120010601",
                    "field": "name",
                    "type": "print_layout",
                    "printed_text": "出席國際會議及考察",
                    "data_text": "出席國際會議及考察-出席國際會議及考察",
                    "suggested_text": "",
                    "note": "測試 plan scope target 解析",
                    "pdf_file": "116年度總萬巒鄉總預算案(P37-175).pdf",
                    "pdf_page": "44",
                    "verified_method": "測試",
                    "verified_on": "2026-11-19",
                    "evidence": "",
                    "status": "confirmed",
                }
            )
            with memos_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            build(data_dir=tmp_root / "data", out_dir=tmp_root / "build", site_dir=tmp_root / "site")
            memos_out = json.loads((tmp_root / "site" / "memos.json").read_text(encoding="utf-8"))
            search_out = json.loads((tmp_root / "site" / "search.json").read_text(encoding="utf-8"))
            search_ids = {d["id"] for d in search_out}
            plan_memo = next(m for m in memos_out["years"]["116"] if m["memo_id"] == "M116-9999")
            self.assertEqual(
                plan_memo["target"],
                {"kind": "plan", "search_id": "116-plan-32120010601", "plan_code": "32120010601"},
            )
            self.assertIn(plan_memo["target"]["search_id"], search_ids)

    def test_index_json_memo_years_and_other_jsons_unchanged(self) -> None:
        self.assertEqual(self.index_json["memo_years"], [114, 115, 116])
        for filename, expected_sha1 in BASELINE_SITE_JSON_SHA1.items():
            with self.subTest(filename=filename):
                self.assertEqual(_sha1(self.site_dir / filename), expected_sha1)

    def test_sqlite_memos_table_queries(self) -> None:
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            count_114 = conn.execute("SELECT COUNT(*) FROM memos WHERE year=114").fetchone()[0]
            self.assertEqual(count_114, 20)
            typos = conn.execute(
                "SELECT memo_id, type, target_search_id FROM memos WHERE type='print_typo' ORDER BY memo_id"
            ).fetchall()
            self.assertGreaterEqual(len(typos), 5)
            self.assertEqual(typos[0], ("M114-0001", "print_typo", "114-revenue-12120010204-1"))
        finally:
            conn.close()

    def test_build_raises_on_missing_search_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            memos_path = tmp_root / "data" / "memos.csv"
            with memos_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = [r for r in reader if r["year"] == "116"]
            rows[0]["locator"] = "99999999999:1"
            with memos_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaises(ValueError):
                build(data_dir=tmp_root / "data", out_dir=tmp_root / "build", site_dir=tmp_root / "site")


class TestMemosInputHardening(unittest.TestCase):
    def test_unknown_year_fails_validate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            memos_path = tmp_root / "data" / "memos.csv"
            with memos_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = [r for r in reader if r["year"] == "116"]
            bad_row = dict(rows[0])
            bad_row["memo_id"] = "M117-0001"
            bad_row["year"] = "117"
            rows.append(bad_row)
            with memos_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            proc = subprocess.run(
                [sys.executable, str(tmp_root / "scripts" / "validate.py"), "116"],
                cwd=str(tmp_root),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("117", proc.stderr)
            report_text = (tmp_root / "reports" / "validate_116.md").read_text(encoding="utf-8")
            self.assertNotIn("M117-0001", report_text)

    def test_missing_required_column_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo(Path(td))
            memos_path = tmp_root / "data" / "memos.csv"
            with memos_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = [c for c in (reader.fieldnames or []) if c != "status"]
                rows = [{k: v for k, v in r.items() if k != "status"} for r in reader if r["year"] == "116"]
            with memos_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            proc = subprocess.run(
                [sys.executable, str(tmp_root / "scripts" / "validate.py"), "116"],
                cwd=str(tmp_root),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("status", proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_invalid_evidence_paths_fail(self) -> None:
        for bad_path in ("../x.png", "/etc/passwd", "docs/other/x.png"):
            with self.subTest(evidence=bad_path), tempfile.TemporaryDirectory() as td:
                tmp_root = _setup_temp_repo(Path(td))
                memos_path = tmp_root / "data" / "memos.csv"
                with memos_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    fieldnames = list(reader.fieldnames or [])
                    rows = [r for r in reader if r["year"] == "116"]
                rows[0]["evidence"] = bad_path
                with memos_path.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)

                proc = subprocess.run(
                    [sys.executable, str(tmp_root / "scripts" / "validate.py"), "116"],
                    cwd=str(tmp_root),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 1)
                report_text = (tmp_root / "reports" / "validate_116.md").read_text(encoding="utf-8")
                self.assertIn("V6:", report_text)


if __name__ == "__main__":
    unittest.main()
