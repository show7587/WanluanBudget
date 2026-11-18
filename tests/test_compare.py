"""Unit tests for 115 vs 116 comparison build output (Slice C1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from scripts.build import ROOT_DIR, _remap_compare_item_codes, build


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestCompare(unittest.TestCase):
    """Verify compare.json generation, sampling, single-year cleanup, and the SKIPPED_YEARS mechanism using temp dirs."""

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
        cls.compare_path = cls.site_dir / "compare.json"
        cls.compare_json = json.loads(
            cls.compare_path.read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_a_normal_build_structure_and_hand_calculated_samples(self) -> None:
        """(a) 115/116 正常建置的內容與數字抽樣（對 CSV 手算）、檔案大小與確定性。"""
        self.assertTrue(self.compare_path.exists())
        self.assertLess(self.compare_path.stat().st_size, 300 * 1024)

        self.assertEqual(self.compare_json["years"], [115, 116])
        self.assertEqual(self.compare_json["from_year"], 115)
        self.assertEqual(self.compare_json["to_year"], 116)

        entries = self.compare_json["entries"]
        self.assertIsInstance(entries, dict)

        required_fields = {
            "kind",
            "level",
            "code",
            "name",
            "amount_元",
            "diff_元",
            "pct",
            "page",
            "status",
            "name_changed",
            "unresolved",
            "in_hierarchy",
            "children",
        }
        for key, entry in entries.items():
            self.assertTrue(
                required_fields.issubset(entry.keys()),
                f"Missing fields in {key}",
            )
            self.assertIn(entry["kind"], ("plan", "object", "revenue"))
            self.assertIn(entry["status"], ("both", "only_115", "only_116"))
            for ck in entry["children"]:
                self.assertIn(ck, entries, f"Child {ck} of {key} not in entries")

        # 驗證歲入細目數量：115 年 21 個、116 年 20 個、共有 19 個、總計 22 個
        rev_fines = [
            e
            for e in entries.values()
            if e["kind"] == "revenue" and e["level"] == "細目"
        ]
        self.assertEqual(len(rev_fines), 22)
        fines_115 = [e for e in rev_fines if e["amount_元"]["115"] is not None]
        fines_116 = [e for e in rev_fines if e["amount_元"]["116"] is not None]
        fines_both = [e for e in rev_fines if e["status"] == "both"]
        fines_only_115 = {e["code"] for e in rev_fines if e["status"] == "only_115"}
        fines_only_116 = {e["code"] for e in rev_fines if e["status"] == "only_116"}
        self.assertEqual(len(fines_115), 21)
        self.assertEqual(len(fines_116), 20)
        self.assertEqual(len(fines_both), 19)
        self.assertEqual(fines_only_115, {"05120010104", "12120010101"})
        self.assertEqual(fines_only_116, {"09120010101"})

        # 抽樣 1：未掛入 hierarchy 的歲入細目 12120010101（學雜費收入，115 年 0 元）
        e_tuition = entries["revenue:12120010101"]
        self.assertEqual(e_tuition["status"], "only_115")
        self.assertFalse(e_tuition["in_hierarchy"])
        self.assertEqual(e_tuition["amount_元"]["115"], 0)
        self.assertIsNone(e_tuition["amount_元"]["116"])
        self.assertEqual(e_tuition["diff_元"], 0)
        self.assertIsNone(e_tuition["pct"])
        self.assertEqual(e_tuition["page"]["115"]["page_start"], 57)

        # 抽樣 2：有掛入 hierarchy 的單一年度 0 元細目 05120010104（考試報名費）
        e_exam = entries["revenue:05120010104"]
        self.assertEqual(e_exam["status"], "only_115")
        self.assertTrue(e_exam["in_hierarchy"])
        self.assertEqual(e_exam["amount_元"]["115"], 0)
        self.assertIsNone(e_exam["amount_元"]["116"])
        self.assertIsNone(e_exam["pct"])
        self.assertIn("revenue:05120010104", entries["revenue:05120010100"]["children"])

        # 抽樣 3：僅 116 存在的歲入細目 09120010101（一般性補助收入，150,000 元，p52）
        e_sub_gen = entries["revenue:09120010101"]
        self.assertEqual(e_sub_gen["status"], "only_116")
        self.assertTrue(e_sub_gen["in_hierarchy"])
        self.assertIsNone(e_sub_gen["amount_元"]["115"])
        self.assertEqual(e_sub_gen["amount_元"]["116"], 150000)
        self.assertEqual(e_sub_gen["diff_元"], 150000)
        self.assertIsNone(e_sub_gen["pct"])
        self.assertEqual(e_sub_gen["page"]["116"]["page"], 52)

        # 抽樣 4：歲入細目 01120011701（統籌分配稅-普通統籌）
        # 115: 204,728,000 (p43), 116: 234,528,000 (p43), diff: +29,800,000, pct: +14.56%
        e_tax = entries["revenue:01120011701"]
        self.assertEqual(e_tax["status"], "both")
        self.assertEqual(e_tax["amount_元"]["115"], 204728000)
        self.assertEqual(e_tax["amount_元"]["116"], 234528000)
        self.assertEqual(e_tax["diff_元"], 29800000)
        self.assertEqual(e_tax["pct"], 14.56)
        self.assertEqual(e_tax["page"]["115"]["page"], 43)
        self.assertEqual(e_tax["page"]["116"]["page"], 43)

        # 抽樣 5：歲入款 01（稅課收入）
        # 115: 218,928,000 (p37-43), 116: 250,228,000 (p37-43), diff: +31,300,000, pct: +14.30%
        e_kuan01 = entries["revenue:01"]
        self.assertEqual(e_kuan01["level"], "款")
        self.assertEqual(e_kuan01["amount_元"]["115"], 218928000)
        self.assertEqual(e_kuan01["amount_元"]["116"], 250228000)
        self.assertEqual(e_kuan01["diff_元"], 31300000)
        self.assertEqual(e_kuan01["pct"], 14.3)
        self.assertEqual(len(e_kuan01["children"]), 6)

        # 抽樣 6：歲出工作計畫 33120010101（一般行政-行政管理，鄉民代表會）
        # 115: 7,929,000 (p60-61), 116: 8,518,000 (p61-62), diff: +589,000, pct: +7.43%
        e_plan = entries["plan:33120010101"]
        self.assertEqual(e_plan["status"], "both")
        self.assertEqual(e_plan["amount_元"]["115"], 7929000)
        self.assertEqual(e_plan["amount_元"]["116"], 8518000)
        self.assertEqual(e_plan["diff_元"], 589000)
        self.assertEqual(e_plan["pct"], 7.43)
        self.assertEqual(e_plan["page"]["115"], {"page": 60, "page_start": 60, "page_end": 61})
        self.assertEqual(e_plan["page"]["116"], {"page": 61, "page_start": 61, "page_end": 62})
        self.assertIn("object:33120010101|1015", e_plan["children"])
        self.assertIn("object:33120010101|1025", e_plan["children"])

        # 抽樣 7：歲出用途別 33120010101|1025（技工及工友待遇）
        # 115: 480,000 + 450,000 = 930,000 (p60)
        # 116: 521,000 + 486,000 = 1,007,000 (p61)
        # diff: +77,000, pct: +8.28%
        e_obj = entries["object:33120010101|1025"]
        self.assertEqual(e_obj["status"], "both")
        self.assertEqual(e_obj["amount_元"]["115"], 930000)
        self.assertEqual(e_obj["amount_元"]["116"], 1007000)
        self.assertEqual(e_obj["diff_元"], 77000)
        self.assertEqual(e_obj["pct"], 8.28)
        self.assertEqual(e_obj["children"], [])

        # 抽樣 8：僅 115 存在的歲出計畫 37120010105（民政業務-選舉業務，3,200,000 元，p94-96）
        e_elec = entries["plan:37120010105"]
        self.assertEqual(e_elec["status"], "only_115")
        self.assertEqual(e_elec["amount_元"]["115"], 3200000)
        self.assertIsNone(e_elec["amount_元"]["116"])
        self.assertEqual(e_elec["diff_元"], -3200000)

    def test_b_single_year_build_does_not_create_and_removes_stale_compare_json(self) -> None:
        """(b) 一年度建置不產生 compare.json 且清掉舊檔。"""
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            data_1yr = t_path / "data"
            out_1yr = t_path / "build"
            site_1yr = t_path / "site_data"

            shutil.copytree(ROOT_DIR / "data" / "116", data_1yr / "116")
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", data_1yr / "corrections.csv")

            # 預先放一個舊的 compare.json
            site_1yr.mkdir(parents=True, exist_ok=True)
            stale_compare = site_1yr / "compare.json"
            stale_compare.write_text('{"stale": true}\n', encoding="utf-8")
            self.assertTrue(stale_compare.exists())

            res = build(data_dir=data_1yr, out_dir=out_1yr, site_dir=site_1yr)
            self.assertEqual(res["years"], [116])
            self.assertFalse(stale_compare.exists())
            self.assertTrue((site_1yr / "116.json").exists())

    def test_c_year_114_with_blank_amounts_in_temp_data_dir_is_skipped(self) -> None:
        """(c) SKIPPED_YEARS 機制仍有效：把含空白金額欄位的 114 資料夾放進暫存 data 目錄並暫時列入 SKIPPED_YEARS，build 仍成功且 years == [115, 116]。

        114 已通過驗證並納入真實建置（SKIPPED_YEARS 目前為空），這裡用 mock 暫時把 114 列入跳過清單，
        以保留「資料不完整的年度可被跳過」這個機制的測試。
        """
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            custom_data = t_path / "data"
            out_dir = t_path / "build"
            site_dir = t_path / "site_data"

            shutil.copytree(ROOT_DIR / "data" / "115", custom_data / "115")
            shutil.copytree(ROOT_DIR / "data" / "116", custom_data / "116")
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", custom_data / "corrections.csv")

            # 建立含有空白金額欄位的 114 資料夾
            dir_114 = custom_data / "114"
            dir_114.mkdir(parents=True, exist_ok=True)
            (dir_114 / "summary.csv").write_text(
                "year,source_book,source_table,page,款,項,科目名稱,本年度,上年度,前年度決算\n"
                "114,114年度總預算,歲入來源別預算總表,4,,,歲入合計,,,\n",
                encoding="utf-8",
            )
            (dir_114 / "revenue_items.csv").write_text(
                "year,page,code,name,item_seq,unit,qty,unit_price,amount_元,note,dept\n"
                "114,43,01120010201,遺產及贈與稅-遺產稅,1,年,1,,,空白金額測試,財政課\n",
                encoding="utf-8",
            )
            (dir_114 / "plans.csv").write_text(
                "year,page_start,page_end,plan_code,name,dept,政事別,總額\n"
                "114,60,61,33120010101,一般行政-行政管理,鄉民代表會,一般政務支出,\n",
                encoding="utf-8",
            )
            (dir_114 / "expenditure_items.csv").write_text(
                "year,page,plan_code,用途別_code,用途別,unit,qty,unit_price,amount_元,說明,經費來源,item_seq\n"
                "114,60,33120010101,1015,法定編制人員待遇,年,1,,,空白金額測試,鄉款,1\n",
                encoding="utf-8",
            )

            with mock.patch("scripts.build.SKIPPED_YEARS", frozenset({114})):
                res = build(data_dir=custom_data, out_dir=out_dir, site_dir=site_dir)
            self.assertEqual(res["years"], [115, 116])
            self.assertTrue((site_dir / "compare.json").exists())
            self.assertFalse((site_dir / "114.json").exists())
            self.assertEqual(
                _sha256(site_dir / "compare.json"),
                _sha256(self.compare_path),
            )


class TestComparePairs(unittest.TestCase):
    """相鄰年度 compare_<a>_<b>.json 的產出、向後相容、決定性與清除（只用暫存目錄）。"""

    def _build(self, tmp: str, years: list[int], site_name: str = "site_data") -> Path:
        t_path = Path(tmp)
        data_dir = t_path / "data"
        for y in years:
            shutil.copytree(ROOT_DIR / "data" / str(y), data_dir / str(y))
        shutil.copy2(ROOT_DIR / "data" / "corrections.csv", data_dir / "corrections.csv")
        site = t_path / site_name
        build(data_dir=data_dir, out_dir=t_path / "build", site_dir=site)
        return site

    @staticmethod
    def _compare_files(site: Path) -> list[str]:
        return sorted(p.name for p in site.glob("compare*.json"))

    def test_three_years_produce_two_pairs_and_latest_compare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = self._build(tmp, [114, 115, 116])
            self.assertEqual(
                self._compare_files(site),
                ["compare.json", "compare_114_115.json", "compare_115_116.json"],
            )
            self.assertEqual(
                (site / "compare.json").read_bytes(),
                (site / "compare_115_116.json").read_bytes(),
            )
            c = json.loads((site / "compare_114_115.json").read_text(encoding="utf-8"))
            self.assertEqual(c["years"], [114, 115])
            self.assertEqual(c["from_year"], 114)
            self.assertEqual(c["to_year"], 115)

    def test_two_years_produce_compare_and_one_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = self._build(tmp, [115, 116])
            self.assertEqual(
                self._compare_files(site), ["compare.json", "compare_115_116.json"]
            )
            self.assertEqual(
                (site / "compare.json").read_bytes(),
                (site / "compare_115_116.json").read_bytes(),
            )

    def test_single_year_removes_all_compare_files_but_keeps_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            site = t_path / "site_data"
            site.mkdir()
            (site / "compare.json").write_text("{}\n", encoding="utf-8")
            (site / "compare_114_115.json").write_text("{}\n", encoding="utf-8")
            (site / "compare_115_116.json").write_text("{}\n", encoding="utf-8")
            keep = ["compare_notes.json", "compare_a_b.json", "compare_114_115.txt",
                    "compare_115_116.json.bak", "other.json"]
            for name in keep:
                (site / name).write_text("keep\n", encoding="utf-8")
            (site / "compare_999_1000.json.d").mkdir()
            data_dir = t_path / "data"
            shutil.copytree(ROOT_DIR / "data" / "116", data_dir / "116")
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", data_dir / "corrections.csv")
            res = build(data_dir=data_dir, out_dir=t_path / "build", site_dir=site)
            self.assertEqual(res["years"], [116])
            self.assertEqual(self._compare_files(site), sorted(
                n for n in keep if n.startswith("compare") and n.endswith(".json")
            ))
            for name in keep:
                self.assertTrue((site / name).exists(), name)
            self.assertTrue((site / "compare_999_1000.json.d").is_dir())

    def test_stale_pair_files_removed_when_years_shrink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            site = t_path / "site_data"
            site.mkdir()
            (site / "compare_114_115.json").write_text("{}\n", encoding="utf-8")
            data_dir = t_path / "data"
            for y in (115, 116):
                shutil.copytree(ROOT_DIR / "data" / str(y), data_dir / str(y))
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", data_dir / "corrections.csv")
            build(data_dir=data_dir, out_dir=t_path / "build", site_dir=site)
            self.assertEqual(
                self._compare_files(site), ["compare.json", "compare_115_116.json"]
            )

    def test_pair_outputs_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            s1 = self._build(tmp1, [114, 115, 116])
            s2 = self._build(tmp2, [114, 115, 116])
            for name in ("compare.json", "compare_114_115.json", "compare_115_116.json"):
                self.assertEqual(_sha256(s1 / name), _sha256(s2 / name), name)


class TestCompareCodeCrosswalk(unittest.TestCase):
    """跨年度代碼對應（data/crosswalk/codes.csv）：改編過的項目在比較時要配成同一對。"""

    @staticmethod
    def _items() -> dict[str, dict]:
        return {
            "revenue:04": {
                "kind": "revenue", "code": "04", "children_keys": ["revenue:04-01", "revenue:04-02"],
                "parent_key": None,
            },
            "revenue:04-01": {
                "kind": "revenue", "code": "04-01", "children_keys": [], "parent_key": "revenue:04",
            },
            "revenue:04-02": {
                "kind": "revenue", "code": "04-02", "children_keys": ["revenue:07120010500"],
                "parent_key": "revenue:04",
            },
            "revenue:07120010500": {
                "kind": "revenue", "code": "07120010500", "children_keys": [],
                "parent_key": "revenue:04-02",
            },
        }

    def test_remap_rewrites_key_code_children_and_parent(self) -> None:
        items = self._items()
        out = _remap_compare_item_codes(items, {"04-02": "04-03"})
        self.assertIn("revenue:04-03", out)
        self.assertNotIn("revenue:04-02", out)
        self.assertEqual(out["revenue:04-03"]["code"], "04-03")
        self.assertEqual(out["revenue:04"]["children_keys"], ["revenue:04-01", "revenue:04-03"])
        self.assertEqual(out["revenue:07120010500"]["parent_key"], "revenue:04-03")
        # 原輸入不被修改；不在對應表內的項目原樣保留
        self.assertIn("revenue:04-02", items)
        self.assertEqual(items["revenue:04"]["children_keys"], ["revenue:04-01", "revenue:04-02"])
        self.assertEqual(out["revenue:04-01"], items["revenue:04-01"])

    def test_remap_empty_map_returns_input_unchanged(self) -> None:
        items = self._items()
        self.assertIs(_remap_compare_item_codes(items, {}), items)
        self.assertIs(_remap_compare_item_codes(items, {"99-99": "98-98"}), items)

    def test_remap_collision_raises(self) -> None:
        with self.assertRaises(ValueError):
            _remap_compare_item_codes(self._items(), {"04-02": "04-01"})

    def test_real_data_aligns_waste_material_sales_between_114_and_115(self) -> None:
        """114 的項 04-03 與 115 的項 04-02 同為廢舊物資售價；115→116 的比較不受影響。"""
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            data_dir = t_path / "data"
            for y in (114, 115, 116):
                shutil.copytree(ROOT_DIR / "data" / str(y), data_dir / str(y),
                                ignore=shutil.ignore_patterns("*.pdf"))
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", data_dir / "corrections.csv")
            shutil.copytree(ROOT_DIR / "data" / "crosswalk", data_dir / "crosswalk")
            site = t_path / "site_data"
            build(data_dir=data_dir, out_dir=t_path / "build", site_dir=site)

            entries = json.loads((site / "compare_114_115.json").read_text(encoding="utf-8"))["entries"]
            waste = entries["revenue:04-03"]
            self.assertEqual(waste["status"], "both")
            self.assertEqual(waste["amount_元"], {"114": 20000, "115": 120000})
            self.assertFalse(waste["name_changed"])
            self.assertEqual(entries["revenue:04-02"]["status"], "only_114")
            self.assertEqual(entries["revenue:04-02"]["name"]["114"], "財產售價")
            self.assertEqual(entries["revenue:07120010500"]["parent_key"], "revenue:04-03")
            self.assertEqual(entries["revenue:04"]["children"],
                             ["revenue:04-01", "revenue:04-02", "revenue:04-03"])
            # 沒有登記對應的年度對（115→116）不受影響
            self.assertEqual(
                _sha256(site / "compare_115_116.json"),
                _sha256(ROOT_DIR / "site" / "data" / "compare_115_116.json"),
            )


if __name__ == "__main__":
    unittest.main()
