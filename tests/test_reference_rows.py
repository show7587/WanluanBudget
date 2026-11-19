"""Tests for whole-row reference table corrections (ref:r{N} / _rows) and 114 p165."""

from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import parse_book as pb  # noqa: E402


def _make_part3_html(ref_table_html: str) -> str:
    return (
        "歲入項目說明提要與預算明細表\n"
        "<table><tr><td>rev</td></tr></table>\n"
        "歲出計畫說明提要與各項費用明細表\n"
        "<table><tr><td>exp</td></tr></table>\n"
        "參考表\n"
        f"{ref_table_html}\n"
    )


_TEST_TOC = {
    "歲入項目說明提要與預算明細表": (1, 1),
    "歲出計畫說明提要與各項費用明細表": (2, 2),
    "測試參考表": (3, 3),
}


def _corr(page: int, locator: str, field: str, old: str, new: str) -> dict[str, str]:
    return {
        "year": "114",
        "page": str(page),
        "locator": locator,
        "field": field,
        "old": old,
        "new": new,
        "reason": "test",
    }


class TestReferenceRowCorrections(unittest.TestCase):
    """機制測試：整列取代、刪列、old 不符、row_idx 重編、格內/整列衝突與 value_num。"""

    def test_has_reference_corrections_recognizes_row_locator(self) -> None:
        corrs = {(165, "ref:r5", "_rows"): _corr(165, "ref:r5", "_rows", "[]", "[]")}
        self.assertTrue(pb.has_reference_corrections(corrs))

    def test_replace_delete_renumber_and_value_num(self) -> None:
        html = (
            "<table>"
            "<tr><td>H0</td><td>H1</td><td>H2</td></tr>"
            "<tr><td rowspan='2'>A</td><td>12</td><td>7,120</td></tr>"
            "<tr><td>34</td><td>56</td></tr>"
            "<tr><td>Z</td><td>1</td><td>100</td></tr>"
            "</table>"
        )
        corrs = {
            (3, "ref:r1", "_rows"): _corr(
                3,
                "ref:r1",
                "_rows",
                json.dumps([[0, 2, 1, "A"], [1, 1, 1, "12"], [2, 1, 1, "7,120"]], ensure_ascii=False),
                json.dumps(
                    [
                        [[0, 1, 1, ""], [1, 1, 1, "1"], [2, 1, 1, ""]],
                        [[0, 1, 1, "A"], [1, 1, 1, "2"], [2, 1, 1, "7,120"]],
                    ],
                    ensure_ascii=False,
                ),
            ),
            (3, "ref:r2", "_rows"): _corr(
                3,
                "ref:r2",
                "_rows",
                json.dumps([[1, 1, 1, "34"], [2, 1, 1, "56"]], ensure_ascii=False),
                "[]",
            ),
            (3, "ref:r3c1", "text"): _corr(3, "ref:r3c1", "text", "1", "9"),
        }
        rows, applied = pb.parse_part3_reference_tables(
            _make_part3_html(html), "114", _TEST_TOC, corrections=corrs
        )
        self.assertEqual(len(applied), 3)
        self.assertEqual(pb.find_unapplied_corrections(corrs, applied), [])

        # 原 r0 + (r1 拆成兩列) + (r2 刪除) + r3 => 共 4 列，row_idx 連續 0..3
        row_indices = sorted({r["row_idx"] for r in rows})
        self.assertEqual(row_indices, [0, 1, 2, 3])

        by_rc = {(r["row_idx"], r["col_idx"]): r for r in rows}
        self.assertEqual(by_rc[(1, 1)]["text"], "1")
        self.assertEqual(by_rc[(1, 1)]["value_num"], "1")
        self.assertEqual(by_rc[(2, 0)]["text"], "A")
        self.assertEqual(by_rc[(2, 0)]["value_num"], "")
        self.assertEqual(by_rc[(2, 2)]["text"], "7,120")
        self.assertEqual(by_rc[(2, 2)]["value_num"], "7120")
        self.assertEqual(by_rc[(3, 1)]["text"], "9")
        self.assertEqual(by_rc[(3, 1)]["value_num"], "9")

    def test_old_mismatch_is_not_applied(self) -> None:
        html = "<table><tr><td>A</td><td>10</td></tr></table>"
        corrs = {
            (3, "ref:r0", "_rows"): _corr(
                3,
                "ref:r0",
                "_rows",
                json.dumps([[0, 1, 1, "A"], [1, 1, 1, "99"]]),
                json.dumps([[[0, 1, 1, "B"], [1, 1, 1, "20"]]]),
            )
        }
        rows, applied = pb.parse_part3_reference_tables(
            _make_part3_html(html), "114", _TEST_TOC, corrections=corrs
        )
        self.assertEqual(applied, [])
        self.assertEqual(len(pb.find_unapplied_corrections(corrs, applied)), 1)
        self.assertEqual([r["text"] for r in rows], ["A", "10"])

    def test_cell_and_row_correction_conflict_raises(self) -> None:
        html = "<table><tr><td>A</td><td>10</td></tr></table>"
        corrs = {
            (3, "ref:r0", "_rows"): _corr(
                3,
                "ref:r0",
                "_rows",
                json.dumps([[0, 1, 1, "A"], [1, 1, 1, "10"]]),
                "[]",
            ),
            (3, "ref:r0c1", "text"): _corr(3, "ref:r0c1", "text", "10", "20"),
        }
        with self.assertRaises(ValueError):
            pb.parse_part3_reference_tables(
                _make_part3_html(html), "114", _TEST_TOC, corrections=corrs
            )


class Test114Page165Vehicles(unittest.TestCase):
    """114 年度 p165 公務車輛明細表：格子涵蓋、value_num 與內部加總。"""

    @classmethod
    def setUpClass(cls) -> None:
        csv_path = ROOT_DIR / "data" / "114" / "reference_tables.csv"
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            cls.csv_p165 = [r for r in csv.DictReader(f) if r["page"] == "165"]

        json_path = ROOT_DIR / "site" / "data" / "reference_114.json"
        ref_data = json.loads(json_path.read_text(encoding="utf-8"))
        cls.json_p165 = next(t for t in ref_data["tables"] if t["page"] == 165)

    def test_grid_coverage_csv_and_json(self) -> None:
        self.assertEqual(sorted({int(r["row_idx"]) for r in self.csv_p165}), list(range(24)))
        covered_csv: set[tuple[int, int]] = set()
        for r in self.csv_p165:
            r0, c0 = int(r["row_idx"]), int(r["col_idx"])
            rs, cs = int(r["rowspan"]), int(r["colspan"])
            for dr in range(rs):
                for dc in range(cs):
                    coord = (r0 + dr, c0 + dc)
                    self.assertNotIn(coord, covered_csv, f"CSV 重疊覆蓋 {coord}")
                    covered_csv.add(coord)
        expected = {(r, c) for r in range(24) for c in range(8)}
        self.assertEqual(covered_csv, expected)

        self.assertEqual(self.json_p165["rows"], 24)
        self.assertEqual(self.json_p165["cols"], 8)
        covered_json: set[tuple[int, int]] = set()
        for cell in self.json_p165["cells"]:
            for dr in range(cell["rs"]):
                for dc in range(cell["cs"]):
                    coord = (cell["r"] + dr, cell["c"] + dc)
                    self.assertNotIn(coord, covered_json, f"JSON 重疊覆蓋 {coord}")
                    covered_json.add(coord)
        self.assertEqual(covered_json, expected)

    def test_value_num_matches_rule(self) -> None:
        for r in self.csv_p165:
            text = r["text"]
            expected = text.replace(",", "") if pb.REFERENCE_VALUE_RE.match(text) else ""
            self.assertEqual(r["value_num"], expected, (r["row_idx"], r["col_idx"], text))

    def test_internal_sums(self) -> None:
        by_rc: dict[tuple[int, int], str] = {
            (int(r["row_idx"]), int(r["col_idx"])): r["value_num"] for r in self.csv_p165
        }
        text_rc: dict[tuple[int, int], str] = {
            (int(r["row_idx"]), int(r["col_idx"])): r["text"] for r in self.csv_p165
        }

        def num(r: int, c: int) -> int:
            v = by_rc.get((r, c), "")
            return int(v) if v else 0

        # 總車輛數 24 = 3 + 4 + 1 + 16
        self.assertEqual(text_rc[(1, 2)], "現有車輛")
        self.assertEqual(num(1, 1), 24)
        self.assertEqual(num(1, 1), num(2, 1) + num(7, 1) + num(13, 1) + num(16, 1))

        # 各組車輛列數與小計/標頭車輛數
        self.assertEqual(text_rc[(6, 2)], "小計")
        self.assertEqual(num(6, 1), 3)
        self.assertEqual(num(6, 1), sum(num(r, 1) for r in range(3, 6)))

        self.assertEqual(text_rc[(12, 2)], "小計")
        self.assertEqual(num(12, 1), 4)
        self.assertEqual(num(12, 1), sum(num(r, 1) for r in range(8, 12)))

        self.assertEqual(text_rc[(15, 2)], "小計")
        self.assertEqual(num(15, 1), 1)
        self.assertEqual(num(15, 1), num(14, 1))

        self.assertEqual(num(16, 1), 16)

        # 第 1 組：牌照稅 7,120、燃料 11,430 = 4,800 + 6,180 + 450
        self.assertEqual(num(2, 6), 7120)
        self.assertEqual(num(6, 6), 7120)
        self.assertEqual(sum(num(r, 6) for r in range(3, 6)), 7120)
        self.assertEqual(num(2, 7), 11430)
        self.assertEqual(num(6, 7), 11430)
        self.assertEqual(sum(num(r, 7) for r in range(3, 6)), 11430)

        # 第 2 組：牌照稅 7,120、燃料 6,300 = 4,800 + 600 + 450 + 450
        self.assertEqual(num(7, 6), 7120)
        self.assertEqual(num(12, 6), 7120)
        self.assertEqual(sum(num(r, 6) for r in range(8, 12)), 7120)
        self.assertEqual(num(7, 7), 6300)
        self.assertEqual(num(12, 7), 6300)
        self.assertEqual(sum(num(r, 7) for r in range(8, 12)), 6300)

        # 第 3 組：牌照稅 2,700、燃料 4,800
        self.assertEqual(num(13, 6), 2700)
        self.assertEqual(num(15, 6), 2700)
        self.assertEqual(num(14, 6), 2700)
        self.assertEqual(num(13, 7), 4800)
        self.assertEqual(num(15, 7), 4800)
        self.assertEqual(num(14, 7), 4800)


if __name__ == "__main__":
    unittest.main()
