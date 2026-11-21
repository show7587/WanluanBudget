"""Unit tests for multi-year series.json generation (Lane A, docs/series-contract.md)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.build import ROOT_DIR, _build_series_json, build

KIND_ORDER = {"revenue": 0, "plan": 1, "object": 2}
REV_LEVEL_ORDER = {"款": 0, "項": 1, "子目": 2, "細目": 3}
LEVELS = {
    "revenue": set(REV_LEVEL_ORDER),
    "plan": {"工作計畫"},
    "object": {"用途別"},
}
REQUIRED_FIELDS = {
    "kind",
    "level",
    "code",
    "display_name",
    "name",
    "amount_元",
    "page",
    "parent_key",
    "children",
    "dept",
    "unresolved",
    "name_changed",
}
PER_YEAR_FIELDS = ("name", "page", "parent_key", "children", "dept", "unresolved")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_item(
    kind: str,
    level: str,
    code: str,
    name: str,
    amount: int,
    *,
    page: int = 1,
    parent_key: str | None = None,
    children_keys: list[str] | None = None,
    dept: str = "",
    func: str | None = None,
    unresolved: bool = False,
) -> dict:
    item: dict = {
        "kind": kind,
        "level": level,
        "code": code,
        "name": name,
        "amount_元": amount,
        "page": page,
        "page_start": page,
        "page_end": page,
        "unresolved": unresolved,
        "in_hierarchy": True,
        "children_keys": list(children_keys or []),
        "parent_key": parent_key,
        "dept": dept,
    }
    if func is not None:
        item["政事別"] = func
    return item


class TestSeriesBuild(unittest.TestCase):
    """以真實資料（寫入暫存目錄）驗證 series.json 的 schema、改碼、缺年、決定性與體積。"""

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
        cls.series_path = cls.site_dir / "series.json"
        cls.series_json = json.loads(cls.series_path.read_text(encoding="utf-8"))
        cls.index_json = json.loads((cls.site_dir / "index.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_schema_and_ordering(self) -> None:
        self.assertTrue(self.series_path.is_file())
        self.assertEqual(set(self.series_json.keys()), {"years", "items", "aliases"})
        self.assertEqual(self.series_json["years"], [114, 115, 116])
        self.assertEqual(self.index_json["series_years"], [114, 115, 116])

        year_strs = [str(y) for y in self.series_json["years"]]
        items = self.series_json["items"]
        self.assertGreater(len(items), 0)

        keys = list(items.keys())
        expected_order = sorted(
            keys,
            key=lambda k: (
                KIND_ORDER[items[k]["kind"]],
                REV_LEVEL_ORDER.get(items[k]["level"], 9),
                k,
            ),
        )
        self.assertEqual(keys, expected_order)

        for key, it in items.items():
            with self.subTest(key=key):
                self.assertTrue(REQUIRED_FIELDS <= set(it.keys()), REQUIRED_FIELDS - set(it.keys()))
                self.assertIn(it["kind"], KIND_ORDER)
                self.assertIn(it["level"], LEVELS[it["kind"]])
                self.assertTrue(key.startswith(it["kind"] + ":"))

                base = key.split(":", 1)[1]
                m = re.fullmatch(r"(.+)@(\d+)", base)
                self.assertEqual(it["code"], m.group(1) if m else base)

                self.assertEqual(list(it["amount_元"].keys()), year_strs)
                present = {y for y, v in it["amount_元"].items() if v is not None}
                self.assertTrue(present, "至少一年有資料")
                for field in PER_YEAR_FIELDS:
                    self.assertEqual(set(it[field].keys()), present)
                for y in present:
                    self.assertEqual(set(it["page"][y].keys()), {"page", "page_start", "page_end"})
                    self.assertEqual(it["children"][y], sorted(it["children"][y]))
                    for ck in it["children"][y]:
                        self.assertIn(ck, items)
                        self.assertEqual(items[ck]["parent_key"].get(y), key)
                    parent = it["parent_key"][y]
                    if parent is not None:
                        self.assertIn(parent, items)
                        self.assertIn(key, items[parent]["children"][y])

                if it["kind"] in ("plan", "object"):
                    self.assertEqual(set(it["政事別"].keys()), present)
                else:
                    self.assertNotIn("政事別", it)

                latest_y = max(present, key=int)
                self.assertEqual(it["display_name"], it["name"][latest_y])
                self.assertEqual(it["name_changed"], len(set(it["name"].values())) > 1)

        aliases = self.series_json["aliases"]
        self.assertEqual(list(aliases.keys()), sorted(aliases.keys()))
        for src, dst in aliases.items():
            year_s, raw = src.split(":", 1)
            self.assertIn(year_s, year_strs)
            self.assertNotEqual(raw, dst)
            self.assertIn(dst, items)
            self.assertIsNotNone(items[dst]["amount_元"][year_s])

    def test_missing_years_are_null_not_zero(self) -> None:
        items = self.series_json["items"]

        # 中間年缺值：115 為 null（不是 0）
        sub_gen = items["revenue:09120010101"]
        self.assertEqual(sub_gen["amount_元"], {"114": 5713000, "115": None, "116": 150000})
        self.assertEqual(set(sub_gen["name"].keys()), {"114", "116"})
        self.assertNotIn("115", sub_gen["page"])

        plan_edu = items["plan:51120019101"]
        self.assertEqual(plan_edu["amount_元"], {"114": 2748000, "115": None, "116": 11174000})
        self.assertEqual(set(plan_edu["政事別"].keys()), {"114", "116"})

        # 只出現一年且金額為 0：有資料年是 0，缺年是 null
        exam = items["revenue:05120010104"]
        self.assertEqual(exam["amount_元"], {"114": None, "115": 0, "116": None})
        self.assertEqual(set(exam["name"].keys()), {"115"})

        # 只出現一年的計畫
        elec = items["plan:37120010105"]
        self.assertEqual(elec["amount_元"], {"114": None, "115": 3200000, "116": None})

    def test_crosswalk_114_04_03_to_04_02_and_displaced_04_02(self) -> None:
        items = self.series_json["items"]
        aliases = self.series_json["aliases"]

        self.assertEqual(
            aliases,
            {
                "114:revenue:04-02": "revenue:04-02@114",
                "114:revenue:04-03": "revenue:04-02",
            },
        )

        # 廢舊物資售價：114 04-03 併入 revenue:04-02
        waste = items["revenue:04-02"]
        self.assertEqual(waste["code"], "04-02")
        self.assertEqual(waste["display_name"], "廢舊物資售價")
        self.assertEqual(waste["amount_元"], {"114": 20000, "115": 120000, "116": 120000})
        self.assertFalse(waste["name_changed"])
        self.assertEqual(waste["children"]["114"], ["revenue:07120010500"])
        self.assertEqual(items["revenue:07120010500"]["parent_key"]["114"], "revenue:04-02")

        # 被擠掉的 114 財產售價：revenue:04-02@114
        prop = items["revenue:04-02@114"]
        self.assertEqual(prop["code"], "04-02")
        self.assertEqual(prop["display_name"], "財產售價")
        self.assertEqual(prop["amount_元"], {"114": 30000, "115": None, "116": None})
        self.assertEqual(prop["parent_key"], {"114": "revenue:04"})
        self.assertEqual(prop["children"], {"114": ["revenue:07120010200"]})
        self.assertEqual(items["revenue:07120010200"]["parent_key"]["114"], "revenue:04-02@114")

        # 父項 revenue:04 的 114 children 包含兩者（canonical key）
        self.assertIn("revenue:04-02", items["revenue:04"]["children"]["114"])
        self.assertIn("revenue:04-02@114", items["revenue:04"]["children"]["114"])
        self.assertNotIn("revenue:04-03", items["revenue:04"]["children"]["114"])

    def test_size_under_350kb(self) -> None:
        size = self.series_path.stat().st_size
        self.assertLess(size, 350 * 1024, f"series.json 過大：{size} bytes")

    def test_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp2:
            t2 = Path(tmp2)
            site2 = t2 / "site" / "data"
            build(data_dir=ROOT_DIR / "data", out_dir=t2 / "build", site_dir=site2)
            self.assertEqual(_sha256(self.series_path), _sha256(site2 / "series.json"))
            self.assertEqual(
                _sha256(self.site_dir / "index.json"),
                _sha256(site2 / "index.json"),
            )

    def test_single_year_removes_stale_series_and_sets_empty_series_years(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            t_path = Path(tmp)
            data_1yr = t_path / "data"
            out_1yr = t_path / "build"
            site_1yr = t_path / "site_data"

            shutil.copytree(ROOT_DIR / "data" / "116", data_1yr / "116")
            shutil.copy2(ROOT_DIR / "data" / "corrections.csv", data_1yr / "corrections.csv")

            site_1yr.mkdir(parents=True, exist_ok=True)
            stale = site_1yr / "series.json"
            stale.write_text('{"stale":true}\n', encoding="utf-8")

            res = build(data_dir=data_1yr, out_dir=out_1yr, site_dir=site_1yr)
            self.assertEqual(res["years"], [116])
            self.assertFalse(stale.exists())
            idx = json.loads((site_1yr / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(idx["series_years"], [])


class TestSeriesAlgorithmAndErrors(unittest.TestCase):
    """以合成／暫存資料測試鏈式改碼、改名與各種報錯規則（不改真實 codes.csv）。"""

    def test_chained_remapping_from_contract_section_6(self) -> None:
        """契約 §6 的合成鏈式改碼：114 99-01 → 115 99-02 → 116 99-03。"""
        items_by_year = {
            114: {
                "revenue:99-01": _make_item("revenue", "項", "99-01", "合成鏈式改碼項", 100),
                "revenue:99-10": _make_item("revenue", "項", "99-10", "合成舊名", 0),
            },
            115: {
                "revenue:99-02": _make_item("revenue", "項", "99-02", "合成鏈式改碼項", 150),
                "revenue:99-10": _make_item("revenue", "項", "99-10", "合成舊名", 0),
            },
            116: {
                "revenue:99-03": _make_item("revenue", "項", "99-03", "合成鏈式改碼項", 120),
                "revenue:99-10": _make_item("revenue", "項", "99-10", "合成新名", 500),
            },
        }
        codes_rows = [
            {"from_year": 114, "from_code": "99-01", "to_year": 115, "to_code": "99-02", "note": "合成：鏈式改碼第一步"},
            {"from_year": 115, "from_code": "99-02", "to_year": 116, "to_code": "99-03", "note": "合成：鏈式改碼第二步"},
        ]
        series = _build_series_json([114, 115, 116], items_by_year, codes_rows)

        self.assertEqual(
            series["aliases"],
            {
                "114:revenue:99-01": "revenue:99-03",
                "115:revenue:99-02": "revenue:99-03",
            },
        )
        chained = series["items"]["revenue:99-03"]
        self.assertEqual(chained["code"], "99-03")
        self.assertEqual(chained["amount_元"], {"114": 100, "115": 150, "116": 120})
        self.assertFalse(chained["name_changed"])

        renamed = series["items"]["revenue:99-10"]
        self.assertTrue(renamed["name_changed"])
        self.assertEqual(renamed["display_name"], "合成新名")
        self.assertEqual(renamed["name"], {"114": "合成舊名", "115": "合成舊名", "116": "合成新名"})

    def test_same_year_canonical_collision_raises(self) -> None:
        """同一年度有兩個項目對應到同一個 canonical key → ValueError。"""
        items_by_year = {
            114: {
                "revenue:04-03": _make_item("revenue", "項", "04-03", "甲", 100),
                "revenue:04-04": _make_item("revenue", "項", "04-04", "乙", 200),
            },
            115: {
                "revenue:04-02": _make_item("revenue", "項", "04-02", "甲", 150),
            },
        }
        codes_rows = [
            {"from_year": 114, "from_code": "04-03", "to_year": 115, "to_code": "04-02", "note": ""},
            {"from_year": 114, "from_code": "04-04", "to_year": 115, "to_code": "04-02", "note": ""},
        ]
        with self.assertRaises(ValueError):
            _build_series_json([114, 115], items_by_year, codes_rows)

    def test_plan_code_in_crosswalk_raises(self) -> None:
        """codes.csv 出現計畫代碼（from_code 或 to_code）→ ValueError。"""
        items_by_year = {
            114: {
                "plan:33120010101": _make_item("plan", "工作計畫", "33120010101", "行政管理", 1000, func="一般政務支出"),
            },
            115: {
                "plan:33120010102": _make_item("plan", "工作計畫", "33120010102", "行政管理", 1200, func="一般政務支出"),
            },
        }
        with self.assertRaises(ValueError) as ctx1:
            _build_series_json(
                [114, 115],
                items_by_year,
                [{"from_year": 114, "from_code": "33120010101", "to_year": 115, "to_code": "99999999999", "note": ""}],
            )
        self.assertIn("object key", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            _build_series_json(
                [114, 115],
                items_by_year,
                [{"from_year": 114, "from_code": "99999999999", "to_year": 115, "to_code": "33120010102", "note": ""}],
            )
        self.assertIn("object key", str(ctx2.exception))

    def test_non_adjacent_year_crosswalk_raises(self) -> None:
        """codes.csv 出現 to_year != from_year + 1 的列 → ValueError。"""
        items_by_year = {
            114: {"revenue:04-03": _make_item("revenue", "項", "04-03", "甲", 100)},
            115: {"revenue:04-03": _make_item("revenue", "項", "04-03", "甲", 100)},
            116: {"revenue:04-02": _make_item("revenue", "項", "04-02", "甲", 100)},
        }
        for bad_row in (
            {"from_year": 114, "from_code": "04-03", "to_year": 116, "to_code": "04-02", "note": ""},
            {"from_year": 115, "from_code": "04-03", "to_year": 115, "to_code": "04-02", "note": ""},
            {"from_year": 115, "from_code": "04-03", "to_year": 114, "to_code": "04-02", "note": ""},
        ):
            with self.subTest(bad_row=bad_row):
                with self.assertRaises(ValueError):
                    _build_series_json([114, 115, 116], items_by_year, [bad_row])


if __name__ == "__main__":
    unittest.main()
