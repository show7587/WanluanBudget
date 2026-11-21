"""檢查 series 契約 fixture 本身（S0）：只驗 fixture 與 docs/series-contract.md 一致，不測任何實作。"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "fixtures" / "series_sample.json"
EXPECTED = ROOT / "tests" / "fixtures" / "series_expected.json"
CONTRACT = ROOT / "docs" / "series-contract.md"

KIND_ORDER = {"revenue": 0, "plan": 1, "object": 2}
REV_LEVEL_ORDER = {"款": 0, "項": 1, "子目": 2, "細目": 3}
LEVELS = {"revenue": set(REV_LEVEL_ORDER), "plan": {"工作計畫"}, "object": {"用途別"}}
REQUIRED = {"kind", "level", "code", "display_name", "name", "amount_元", "page",
            "parent_key", "children", "dept", "unresolved", "name_changed"}
PER_YEAR = ("name", "page", "parent_key", "children", "dept", "unresolved")
# 計畫 §4「S0 契約」列出的必備案例，對照表每一列的第一欄要能找到這些字樣
REQUIRED_CASES = ("改碼", "被擠掉", "中間年缺值", "只出現一年", "改名", "0 值",
                  "負增減", "鏈式改碼", "指數基準年不是第一年")


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class SeriesFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = _load(SAMPLE)
        cls.expected = _load(EXPECTED)
        cls.years = [str(y) for y in cls.sample["years"]]
        cls.items = cls.sample["items"]

    def present_years(self, item: dict) -> set[str]:
        return {y for y, v in item["amount_元"].items() if v is not None}

    def test_top_level(self) -> None:
        self.assertEqual(set(self.sample), {"years", "items", "aliases"})
        self.assertEqual(self.sample["years"], sorted(self.sample["years"]))

    def test_item_fields(self) -> None:
        for key, it in self.items.items():
            with self.subTest(key=key):
                self.assertTrue(REQUIRED <= set(it), REQUIRED - set(it))
                self.assertIn(it["kind"], KIND_ORDER)
                self.assertIn(it["level"], LEVELS[it["kind"]])
                self.assertEqual(list(it["amount_元"]), self.years, "amount_元 要有 years 每一年")
                present = self.present_years(it)
                self.assertTrue(present, "至少一年有資料")
                for f in PER_YEAR:
                    self.assertEqual(set(it[f]), present, f"{f} 只列有資料的年度")
                if it["kind"] in ("plan", "object"):
                    self.assertEqual(set(it["政事別"]), present)
                else:
                    self.assertNotIn("政事別", it)
                # key 與 code 一致
                base = key.split(":", 1)[1]
                m = re.fullmatch(r"(.+)@(\d+)", base)
                self.assertEqual(it["code"], m.group(1) if m else base)
                self.assertTrue(key.startswith(it["kind"] + ":"))
                # display_name 與 name_changed
                latest = max(present, key=int)
                self.assertEqual(it["display_name"], it["name"][latest])
                self.assertEqual(it["name_changed"], len(set(it["name"].values())) > 1)

    def test_item_order(self) -> None:
        keys = list(self.items)
        ordered = sorted(keys, key=lambda k: (KIND_ORDER[self.items[k]["kind"]],
                                              REV_LEVEL_ORDER.get(self.items[k]["level"], 9), k))
        self.assertEqual(keys, ordered)

    def test_aliases(self) -> None:
        aliases = self.sample["aliases"]
        self.assertEqual(list(aliases), sorted(aliases))
        for src, dst in aliases.items():
            with self.subTest(alias=src):
                year, raw = src.split(":", 1)
                self.assertIn(year, self.years)
                self.assertNotEqual(raw, dst)
                self.assertIn(dst, self.items)
                self.assertIsNotNone(self.items[dst]["amount_元"][year], "alias 指向的項目該年要有值")

    def test_hierarchy_consistent_per_year(self) -> None:
        for key, it in self.items.items():
            for y, kids in it["children"].items():
                with self.subTest(key=key, year=y):
                    self.assertEqual(kids, sorted(kids))
                    for c in kids:
                        self.assertIn(c, self.items)
                        self.assertEqual(self.items[c]["parent_key"].get(y), key)
            for y, parent in it["parent_key"].items():
                if parent is not None:
                    with self.subTest(key=key, year=y, parent=parent):
                        self.assertIn(parent, self.items)
                        self.assertIn(key, self.items[parent]["children"][y])

    def test_expected_matches_sample(self) -> None:
        exp = self.expected["items"]
        self.assertEqual(set(exp), set(self.items))
        for key, e in exp.items():
            with self.subTest(key=key):
                self.assertEqual(set(e), {"diff_元", "pct", "index_base_year", "index"})
                for f in ("diff_元", "pct", "index"):
                    self.assertEqual(list(e[f]), self.years)
                self.assertIsNone(e["diff_元"][self.years[0]])
                self.assertIsNone(e["pct"][self.years[0]])

    def test_expected_values_follow_contract_rules(self) -> None:
        """以契約 §4 的文字規則再推一次，交叉檢查手算值（第二種推導，不是實作）。"""
        for key, it in self.items.items():
            v = it["amount_元"]
            e = self.expected["items"][key]
            with self.subTest(key=key):
                for i, y in enumerate(self.years):
                    if i == 0:
                        continue
                    p = self.years[i - 1]
                    if v[y] is None or v[p] is None:
                        self.assertIsNone(e["diff_元"][y])
                        self.assertIsNone(e["pct"][y])
                        continue
                    self.assertEqual(e["diff_元"][y], v[y] - v[p])
                    if v[y] == 0 and v[p] == 0:
                        self.assertEqual(e["pct"][y], 0)
                    elif v[p] == 0:
                        self.assertIsNone(e["pct"][y])
                    else:
                        self.assertEqual(e["pct"][y], round((v[y] - v[p]) / v[p] * 100, 2))
                base = next((y for y in self.years if v[y] not in (None, 0)), None)
                self.assertEqual(e["index_base_year"], int(base) if base else None)
                for y in self.years:
                    if base is None or v[y] is None:
                        self.assertIsNone(e["index"][y])
                    else:
                        self.assertEqual(e["index"][y], round(v[y] / v[base] * 100, 2))

    def test_contract_case_table(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        section = text.split("### 必備案例對照", 1)[1].split("\n## ", 1)[0]
        rows = [ln.replace("\\|", "\x00").split("|")
                for ln in section.splitlines() if ln.startswith("| ") and not ln.startswith("| 案例")]
        case_col = " ".join(r[1] for r in rows)
        for case in REQUIRED_CASES:
            self.assertIn(case, case_col, f"對照表缺案例：{case}")
        for r in rows:
            keys = re.findall(r"`([a-z]+:[^`]+)`", r[2].replace("\x00", "|"))
            with self.subTest(row=r[1].strip()):
                self.assertTrue(keys, "對照表每列至少要有一個 fixture key")
                for k in keys:
                    self.assertIn(k, self.items)


if __name__ == "__main__":
    unittest.main()
