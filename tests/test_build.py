"""Unit tests for scripts/build.py (Slice S3)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from scripts.build import ROOT_DIR, build


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestBuild(unittest.TestCase):
    """Verify SQLite and JSON build outputs using temporary directories only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.tmp_path = Path(cls._tmpdir.name)
        cls.out_dir = cls.tmp_path / "build"
        cls.site_dir = cls.tmp_path / "site" / "data"
        cls.result = build(
            data_dir=ROOT_DIR / "data",
            out_dir=cls.out_dir,
            site_dir=cls.site_dir,
        )
        cls.sqlite_path = cls.out_dir / "budget.sqlite"
        cls.year_116_json = json.loads(
            (cls.site_dir / "116.json").read_text(encoding="utf-8")
        )
        cls.index_json = json.loads(
            (cls.site_dir / "index.json").read_text(encoding="utf-8")
        )
        cls.search_json = json.loads(
            (cls.site_dir / "search.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_1_revenue_item_01120011701_page_43(self) -> None:
        """驗收 1: select page, amount_元 from revenue_items where code='01120011701' 應回傳 page 43。"""
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            rows = conn.execute(
                "SELECT page, amount_元 FROM revenue_items WHERE year=116 AND code='01120011701' ORDER BY item_seq"
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(
            rows,
            [
                (43, 213588000),
                (43, 20939346),
                (43, 654),
            ],
        )
        self.assertTrue(all(page == 43 for page, _ in rows))
        self.assertEqual(sum(amt for _, amt in rows), 234528000)

    def test_2_sql_queries_by_year_code_keyword_and_page(self) -> None:
        """驗收 2: 可用 SQL 依年度＋細目編號、關鍵字（LIKE）、頁碼查詢。"""
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            by_code = conn.execute(
                "SELECT year, code, name, page, amount_元 FROM revenue_items "
                "WHERE year=116 AND code='01120011401'"
            ).fetchall()
            self.assertEqual(by_code, [(116, "01120011401", "房屋稅-房屋稅", 40, 10000000)])

            by_keyword = conn.execute(
                "SELECT year, code, page, amount_元, note FROM revenue_items "
                "WHERE year=116 AND note LIKE '%檳榔%'"
            ).fetchall()
            self.assertEqual(len(by_keyword), 1)
            self.assertEqual(by_keyword[0][:4], (116, "09120010102", 54, 18000))

            by_page = conn.execute(
                "SELECT plan_code, name, dept, 總額 FROM plans "
                "WHERE year=116 AND 78 BETWEEN page_start AND page_end"
            ).fetchall()
            self.assertEqual(
                by_page,
                [("32120010601", "出席國際會議及考察-出席國際會議及考察", "秘書室", 300000)],
            )
        finally:
            conn.close()

    def test_3_totals_match_321081000_and_312678000(self) -> None:
        """驗收 3: 計畫總額加總 = 321,081,000 元；歲入細目表頭總計 = 312,678,000 元（從 summary 取）。"""
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            plan_sum = conn.execute(
                "SELECT SUM(總額) FROM plans WHERE year=116"
            ).fetchone()[0]
            exp_detail_sum = conn.execute(
                "SELECT SUM(amount_元) FROM expenditure_items WHERE year=116"
            ).fetchone()[0]
            rev_summary_total = conn.execute(
                "SELECT 本年度 FROM summary "
                "WHERE year=116 AND source_table='歲入來源別預算總表' AND 科目名稱='歲入合計'"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(plan_sum, 321081000)
        self.assertEqual(exp_detail_sum, 321081000)
        self.assertEqual(rev_summary_total, 312678000)

        # Also check JSON overview & hierarchy sums
        self.assertEqual(self.year_116_json["overview"]["revenue_total_元"], 312678000)
        self.assertEqual(self.year_116_json["overview"]["expenditure_total_元"], 321081000)
        self.assertEqual(self.year_116_json["overview"]["expenditure_plan_sum_元"], 321081000)

        # Sum of 20 fine-item header budgets in 116.json == 312,678,000 元
        fine_items = [
            fine
            for kuan in self.year_116_json["revenue"]["hierarchy"]
            for hsiang in kuan["children"]
            for sub in hsiang["children"]
            for fine in sub["children"]
        ]
        self.assertEqual(len(fine_items), 20)
        self.assertEqual(sum(f["amount_元"] for f in fine_items), 312678000)

    def test_4_search_json_contains_betel_nut_with_page(self) -> None:
        """驗收 4: search.json 搜尋「檳榔」找得到並帶頁碼。"""
        self.assertIsInstance(self.search_json, list)
        required_keys = {"id", "year", "kind", "code", "name", "text", "page"}
        for doc in self.search_json:
            self.assertTrue(required_keys.issubset(doc.keys()))
            self.assertIn(doc["kind"], ("revenue", "expenditure", "plan", "summary"))

        hits = [
            doc
            for doc in self.search_json
            if doc["year"] == 116 and ("檳榔" in doc["text"] or "檳榔" in doc["name"])
        ]
        self.assertGreaterEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit["year"], 116)
        self.assertEqual(hit["kind"], "revenue")
        self.assertEqual(hit["code"], "09120010102")
        self.assertEqual(hit["page"], 54)

    def test_4b_year_115_is_built_and_totals_match(self) -> None:
        """115 年度已納入建置：歲出計畫總額 = 271,169,000 元、歲入細目表頭總計 = 261,484,000 元。"""
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            years = [r[0] for r in conn.execute("SELECT DISTINCT year FROM plans ORDER BY year")]
            self.assertEqual(years, [115, 116])
            plan_total = conn.execute("SELECT SUM(總額) FROM plans WHERE year=115").fetchone()[0]
            self.assertEqual(plan_total, 271169000)
            n_plans = conn.execute("SELECT COUNT(*) FROM plans WHERE year=115").fetchone()[0]
            self.assertEqual(n_plans, 48)
            revenue_total = conn.execute(
                "SELECT SUM(amount_元) FROM revenue_items WHERE year=115"
            ).fetchone()[0]
            self.assertEqual(revenue_total, 261484000)
        finally:
            conn.close()

    def test_5_no_unresolved_flags_after_t1_fix(self) -> None:
        """T1 已依 PDF p53 補齊：SQLite 與 JSON 中不再有未解決旗標，09120010102 明細加總等於表頭。"""
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            rows = conn.execute(
                "SELECT DISTINCT code FROM revenue_items WHERE year=116 AND unresolved=1"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [])

        fine_by_code = {
            fine["code"]: fine
            for kuan in self.year_116_json["revenue"]["hierarchy"]
            for hsiang in kuan["children"]
            for sub in hsiang["children"]
            for fine in sub["children"]
        }
        target = fine_by_code["09120010102"]
        self.assertFalse(target["unresolved"])
        self.assertEqual(target["amount_元"], 44260000)
        self.assertEqual(target["detail_amount_元"], 44260000)
        self.assertEqual(target["page_start"], 53)
        self.assertEqual(target["page_end"], 57)
        for f in fine_by_code.values():
            self.assertFalse(f["unresolved"])

    def test_6_hierarchies_structure_and_pages(self) -> None:
        """驗證歲入（款→項→子目→細目）與歲出（政事別→機關→工作計畫→用途別→明細）結構與頁碼。"""
        rev_kuan = self.year_116_json["revenue"]["hierarchy"]
        self.assertEqual(len(rev_kuan), 7)
        for k in rev_kuan:
            self.assertEqual(k["level"], "款")
            self.assertIsInstance(k["amount_元"], int)
            self.assertIsInstance(k["page"], int)
            for h in k["children"]:
                self.assertEqual(h["level"], "項")
                self.assertIsInstance(h["amount_元"], int)
                self.assertIsInstance(h["page"], int)
                for s in h["children"]:
                    self.assertEqual(s["level"], "子目")
                    self.assertIsInstance(s["amount_元"], int)
                    self.assertIsInstance(s["page"], int)
                    for f in s["children"]:
                        self.assertEqual(f["level"], "細目")
                        self.assertIsInstance(f["amount_元"], int)
                        self.assertIsInstance(f["page"], int)
                        self.assertGreaterEqual(len(f["children"]), 1)

        exp_funcs = self.year_116_json["expenditure"]["hierarchy"]
        self.assertEqual(len(exp_funcs), 7)
        plan_count = 0
        detail_count = 0
        for fn in exp_funcs:
            self.assertEqual(fn["level"], "政事別")
            self.assertIsInstance(fn["amount_元"], int)
            self.assertIsInstance(fn["page"], int)
            for dept in fn["children"]:
                self.assertEqual(dept["level"], "機關")
                self.assertIsInstance(dept["amount_元"], int)
                self.assertIsInstance(dept["page"], int)
                for plan in dept["children"]:
                    plan_count += 1
                    self.assertEqual(plan["level"], "工作計畫")
                    self.assertIsInstance(plan["amount_元"], int)
                    self.assertIsInstance(plan["page_start"], int)
                    self.assertIsInstance(plan["page_end"], int)
                    self.assertLessEqual(plan["page_start"], plan["page_end"])
                    for use in plan["children"]:
                        self.assertEqual(use["level"], "用途別")
                        self.assertIsInstance(use["amount_元"], int)
                        self.assertIsInstance(use["page"], int)
                        for item in use["children"]:
                            detail_count += 1
                            self.assertEqual(item["level"], "明細")
                            self.assertIsInstance(item["amount_元"], int)
                            self.assertIsInstance(item["page"], int)

        self.assertEqual(plan_count, 49)
        self.assertEqual(detail_count, 636)

    def test_7_deterministic_rebuild_and_crosswalk_loading(self) -> None:
        """驗收 5: 重跑兩次輸出位元組完全一致（比對 SHA-256），且能載入存在的 crosswalk CSV。"""
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            out1 = t_path / "run1_build"
            site1 = t_path / "run1_site"
            out2 = t_path / "run2_build"
            site2 = t_path / "run2_site"

            build(data_dir=ROOT_DIR / "data", out_dir=out1, site_dir=site1)
            build(data_dir=ROOT_DIR / "data", out_dir=out2, site_dir=site2)

            self.assertEqual(
                _sha256(out1 / "budget.sqlite"),
                _sha256(out2 / "budget.sqlite"),
            )
            for fname in ("116.json", "index.json", "search.json"):
                self.assertEqual(
                    _sha256(site1 / fname),
                    _sha256(site2 / fname),
                )

            # Test loading optional crosswalk CSVs when present
            custom_data = t_path / "custom_data"
            shutil.copytree(ROOT_DIR / "data" / "116", custom_data / "116")
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", custom_data / "corrections.csv")
            cw_dir = custom_data / "crosswalk"
            cw_dir.mkdir(parents=True, exist_ok=True)

            with (cw_dir / "items.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["item_id", "kind", "year", "scope_key", "item_seq"])
                w.writerow(["REV-01120010201-115-001", "revenue", "116", "01120010201", "1"])

            with (cw_dir / "items_candidates.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(
                    [
                        "kind",
                        "scope_key",
                        "from_year",
                        "from_item_seq",
                        "to_year",
                        "to_item_seq",
                        "status",
                        "similarity",
                        "from_text",
                        "to_text",
                    ]
                )
                w.writerow(
                    [
                        "expenditure",
                        "33120010101+1015",
                        "115",
                        "1",
                        "116",
                        "1",
                        "candidate",
                        "0.8571",
                        "職員薪俸。",
                        "職員薪俸、加給。",
                    ]
                )

            out3 = t_path / "run3_build"
            site3 = t_path / "run3_site"
            build(data_dir=custom_data, out_dir=out3, site_dir=site3)

            conn = sqlite3.connect(str(out3 / "budget.sqlite"))
            try:
                cw_items = conn.execute("SELECT * FROM crosswalk_items").fetchall()
                cw_cands = conn.execute("SELECT * FROM crosswalk_items_candidates").fetchall()
            finally:
                conn.close()

            self.assertEqual(len(cw_items), 1)
            self.assertEqual(cw_items[0][0], "REV-01120010201-115-001")
            self.assertEqual(len(cw_cands), 1)
            self.assertEqual(cw_cands[0][6], "candidate")


if __name__ == "__main__":
    unittest.main()
