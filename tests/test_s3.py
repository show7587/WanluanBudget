import csv
from pathlib import Path
import tempfile
import unittest

from scripts.match_items import (
    CANDIDATES_FIELDNAMES,
    ITEMS_FIELDNAMES,
     main as match_items_main,
    match_items,
    normalize_text,
)


REVENUE_HEADERS = [
    "year",
    "page",
    "code",
    "name",
    "item_seq",
    "unit",
    "qty",
    "unit_price",
    "amount_元",
    "note",
    "dept",
]

EXPENDITURE_HEADERS = [
    "year",
    "page",
    "plan_code",
    "用途別_code",
    "用途別",
    "unit",
    "qty",
    "unit_price",
    "amount_元",
    "說明",
    "經費來源",
    "item_seq",
]


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestMatchItemsS3(unittest.TestCase):
    def test_normalize_text_years_doc_numbers_and_punctuation(self) -> None:
        # 115年度 vs 116年、不同函文字號與標點空白，正規化後應完全一致
        t115 = (
            "統籌分配稅-普通統籌  115年度中央普通統籌分配稅款"
            "（依據財政部114.08.20台財庫字第11403710000號函辦理）。"
            "115年縣統籌分配稅款114.9.25屏府財稅財字第1140570000號函。"
        )
        t116 = (
            "統籌分配稅-普通統籌 116年中央普通統籌分配稅款"
            "(依據財政部115.08.24台財庫字第11503718571號函辦理)！"
            "116年度縣統籌分配稅款115.9.29屏府財稅財字第1150571040號函"
        )
        self.assertEqual(normalize_text(t115), normalize_text(t116))
        self.assertIn("<年>", normalize_text(t115))

        # R1/R2: 非括號函文字號移除時，不得誤吃前方的說明本文
        self.assertEqual(
            normalize_text("辦理環境清潔補助款依屏府環衛字第1159019686號函核定"),
            "辦理環境清潔補助款",
        )
        self.assertEqual(
            normalize_text("補助款屏府財字第12號函"),
            "補助款",
        )

    def test_inline_doc_number_diff_only_matches_as_exact(self) -> None:
        """同一說明、僅非括號函文字號不同 → 正規化後相等並配對為 exact。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            exp_115 = [
                {
                    "year": "115",
                    "page": "75",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "100000",
                    "amount_元": "100000",
                    "說明": "辦理環境清潔補助款依屏府環衛字第1149000111號函核定",
                    "經費來源": "上級補助",
                    "item_seq": "1",
                },
                {
                    "year": "115",
                    "page": "75",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "50000",
                    "amount_元": "50000",
                    "說明": "補助款屏府財字第11號函",
                    "經費來源": "上級補助",
                    "item_seq": "2",
                },
            ]
            exp_116 = [
                {
                    "year": "116",
                    "page": "76",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "120000",
                    "amount_元": "120000",
                    "說明": "辦理環境清潔補助款依屏府環衛字第1159019686號函核定",
                    "經費來源": "上級補助",
                    "item_seq": "1",
                },
                {
                    "year": "116",
                    "page": "76",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "50000",
                    "amount_元": "50000",
                    "說明": "補助款屏府財字第12號函",
                    "經費來源": "上級補助",
                    "item_seq": "2",
                },
            ]
            _write_csv(data_dir / "115" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_115)
            _write_csv(data_dir / "116" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_116)

            rows = match_items("115", "116", data_dir=data_dir)
            self.assertEqual(len(rows), 2)
            self.assertEqual([r["status"] for r in rows], ["exact", "exact"])
            self.assertEqual([r["from_item_seq"] for r in rows], ["1", "2"])
            self.assertEqual([r["to_item_seq"] for r in rows], ["1", "2"])

    def test_four_basic_statuses_and_items_csv_filtering(self) -> None:
        """涵蓋：完全相同(exact)、相似候選(candidate)、新增(added)、刪除(deleted)，且候選不寫入 items.csv。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)

            # 歲入 115 年與 116 年同屬細目 01120010201
            rev_115 = [
                {
                    "year": "115",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "1",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "300000",
                    "amount_元": "300000",
                    "note": "依據遺產及贈與稅法第1條辦理。",
                    "dept": "財政課",
                },
                {
                    "year": "115",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "2",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "50000",
                    "amount_元": "50000",
                    "note": "辦理遺產稅申報輔導及查核作業經費。",
                    "dept": "財政課",
                },
                {
                    "year": "115",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "3",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "10000",
                    "amount_元": "10000",
                    "note": "舊年度一次性專案宣導手冊印製。",
                    "dept": "財政課",
                },
            ]
            rev_116 = [
                {
                    "year": "116",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "1",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "320000",
                    "amount_元": "320000",
                    "note": "依據遺產及贈與稅法第1條辦理",  # 去標點後 exact
                    "dept": "財政課",
                },
                {
                    "year": "116",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "2",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "55000",
                    "amount_元": "55000",
                    "note": "辦理遺產稅申報輔導及宣導作業經費。",  # 僅「查核」改「宣導」，相似度 > 0.75 -> candidate
                    "dept": "財政課",
                },
                {
                    "year": "116",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "3",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "20000",
                    "amount_元": "20000",
                    "note": "新年度數位化櫃台設備建置。",  # 新增 added
                    "dept": "財政課",
                },
            ]

            _write_csv(data_dir / "115" / "revenue_items.csv", REVENUE_HEADERS, rev_115)
            _write_csv(data_dir / "116" / "revenue_items.csv", REVENUE_HEADERS, rev_116)

            rc = match_items_main(["115", "116", "--data-dir", str(data_dir)])
            self.assertEqual(rc, 0)

            cand_path = data_dir / "crosswalk" / "items_candidates.csv"
            items_path = data_dir / "crosswalk" / "items.csv"
            self.assertTrue(cand_path.exists())
            self.assertTrue(items_path.exists())

            cand_rows = _read_csv(cand_path)
            self.assertEqual(list(cand_rows[0].keys()), CANDIDATES_FIELDNAMES)

            by_status = {r["status"]: r for r in cand_rows}
            self.assertEqual(set(by_status.keys()), {"exact", "candidate", "deleted", "added"})

            # 驗證各狀態內容
            self.assertEqual(by_status["exact"]["from_item_seq"], "1")
            self.assertEqual(by_status["exact"]["to_item_seq"], "1")
            self.assertEqual(by_status["exact"]["similarity"], "1.0000")

            self.assertEqual(by_status["candidate"]["from_item_seq"], "2")
            self.assertEqual(by_status["candidate"]["to_item_seq"], "2")
            sim_val = float(by_status["candidate"]["similarity"])
            self.assertGreaterEqual(sim_val, 0.75)
            self.assertLess(sim_val, 1.0)

            self.assertEqual(by_status["deleted"]["from_item_seq"], "3")
            self.assertEqual(by_status["deleted"]["to_item_seq"], "")

            self.assertEqual(by_status["added"]["from_item_seq"], "")
            self.assertEqual(by_status["added"]["to_item_seq"], "3")

            # 驗證 items.csv 只包含 exact 配對（115 年與 116 年各一筆，且共用同一個 item_id），不含 candidate/deleted/added
            item_rows = _read_csv(items_path)
            self.assertEqual(len(item_rows), 2)
            self.assertEqual(list(item_rows[0].keys()), ITEMS_FIELDNAMES)
            self.assertEqual(item_rows[0]["item_id"], item_rows[1]["item_id"])
            self.assertEqual({r["year"] for r in item_rows}, {"115", "116"})
            self.assertEqual({r["item_seq"] for r in item_rows}, {"1"})

    def test_year_token_normalization_leads_to_exact_match(self) -> None:
        """年度字樣與函文字號正規化後視為完全相同（exact）。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            exp_115 = [
                {
                    "year": "115",
                    "page": "65",
                    "plan_code": "33120010101",
                    "用途別_code": "2033",
                    "用途別": "約用人員酬金",
                    "unit": "月",
                    "qty": "12",
                    "unit_price": "35000",
                    "amount_元": "420000",
                    "說明": "辦理115年度一般行政約用人員薪資(依據屏東縣政府114.9.10屏府民行字第1140012345號函核定補助)。",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            exp_116 = [
                {
                    "year": "116",
                    "page": "66",
                    "plan_code": "33120010101",
                    "用途別_code": "2033",
                    "用途別": "約用人員酬金",
                    "unit": "月",
                    "qty": "12",
                    "unit_price": "36000",
                    "amount_元": "432000",
                    "說明": "辦理116年一般行政約用人員薪資（依據屏東縣政府115.9.12屏府民行字第1150098765號函核定補助）",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            _write_csv(data_dir / "115" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_115)
            _write_csv(data_dir / "116" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_116)

            rows = match_items("115", "116", data_dir=data_dir)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "exact")
            self.assertEqual(rows[0]["scope_key"], "33120010101+2033")

    def test_different_scopes_never_match(self) -> None:
        """不同 scope（如不同細目編號、不同計畫編號或不同用途別）即使文字完全相同也不會互相配對。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            # 歲출：相同計畫編號但不同用途別_code (2033 vs 2051)
            exp_115 = [
                {
                    "year": "115",
                    "page": "70",
                    "plan_code": "33120010101",
                    "用途別_code": "2033",
                    "用途別": "約用人員酬金",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "100000",
                    "amount_元": "100000",
                    "說明": "完全相同的說明文字測試",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            exp_116 = [
                {
                    "year": "116",
                    "page": "70",
                    "plan_code": "33120010101",
                    "用途別_code": "2051",
                    "用途別": "按日按件計資酬金",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "100000",
                    "amount_元": "100000",
                    "說明": "完全相同的說明文字測試",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            _write_csv(data_dir / "115" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_115)
            _write_csv(data_dir / "116" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_116)

            rows = match_items("115", "116", data_dir=data_dir)
            self.assertEqual(len(rows), 2)
            statuses = {(r["scope_key"], r["status"]) for r in rows}
            self.assertEqual(
                statuses,
                {
                    ("33120010101+2033", "deleted"),
                    ("33120010101+2051", "added"),
                },
            )
            items_rows = _read_csv(data_dir / "crosswalk" / "items.csv")
            self.assertEqual(len(items_rows), 0)

    def test_codes_crosswalk_mapping_works_for_revenue_and_expenditure(self) -> None:
        """data/crosswalk/codes.csv 對應生效後，舊編號可與新編號配對，且 items.csv 保留各年度原始 scope_key。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            codes_rows = [
                {
                    "from_year": "115",
                    "from_code": "01120010999",
                    "to_year": "116",
                    "to_code": "01120010201",
                    "note": "細目編號調整",
                },
                {
                    "from_year": "115",
                    "from_code": "33120010000",
                    "to_year": "116",
                    "to_code": "33120010101",
                    "note": "工作計畫編號重編",
                },
            ]
            _write_csv(
                data_dir / "crosswalk" / "codes.csv",
                ["from_year", "from_code", "to_year", "to_code", "note"],
                codes_rows,
            )

            rev_115 = [
                {
                    "year": "115",
                    "page": "37",
                    "code": "01120010999",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "1",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "300000",
                    "amount_元": "300000",
                    "note": "依據遺產及贈與稅法第1條辦理。",
                    "dept": "財政課",
                }
            ]
            rev_116 = [
                {
                    "year": "116",
                    "page": "37",
                    "code": "01120010201",
                    "name": "遺產及贈與稅-遺產稅",
                    "item_seq": "1",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "300000",
                    "amount_元": "300000",
                    "note": "依據遺產及贈與稅法第1條辦理。",
                    "dept": "財政課",
                }
            ]
            exp_115 = [
                {
                    "year": "115",
                    "page": "61",
                    "plan_code": "33120010000",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "50000",
                    "amount_元": "50000",
                    "說明": "辦公廳舍清潔及環境維護費用",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            exp_116 = [
                {
                    "year": "116",
                    "page": "61",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "年",
                    "qty": "1",
                    "unit_price": "50000",
                    "amount_元": "50000",
                    "說明": "辦公廳舍清潔及環境維護費用",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            _write_csv(data_dir / "115" / "revenue_items.csv", REVENUE_HEADERS, rev_115)
            _write_csv(data_dir / "116" / "revenue_items.csv", REVENUE_HEADERS, rev_116)
            _write_csv(data_dir / "115" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_115)
            _write_csv(data_dir / "116" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_116)

            rows = match_items("115", "116", data_dir=data_dir)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["status"] == "exact" for r in rows))
            self.assertEqual(
                {r["scope_key"] for r in rows},
                {"01120010201", "33120010101+2009"},
            )

            items_rows = _read_csv(data_dir / "crosswalk" / "items.csv")
            self.assertEqual(len(items_rows), 4)
            rev_items = [r for r in items_rows if r["kind"] == "revenue"]
            self.assertEqual(rev_items[0]["item_id"], rev_items[1]["item_id"])
            self.assertEqual(
                {(r["year"], r["scope_key"]) for r in rev_items},
                {("115", "01120010999"), ("116", "01120010201")},
            )

    def test_similarity_just_below_075_not_candidate(self) -> None:
        """相似度剛好低於 0.75（例如 8 個字中 5 個字相同 -> 2*5/(8+8) = 0.625，或 11 個字中 8 個字相同 -> 16/22 = 0.7273）不列為候選。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            # "甲乙丙丁戊己庚辛壬癸子" (11字) vs "甲乙丙丁戊己庚辛丑寅卯" (11字)，前8字相同 -> 相似度 16/22 = 0.727272... < 0.75
            exp_115 = [
                {
                    "year": "115",
                    "page": "80",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "10000",
                    "amount_元": "10000",
                    "說明": "甲乙丙丁戊己庚辛壬癸子",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            exp_116 = [
                {
                    "year": "116",
                    "page": "80",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "10000",
                    "amount_元": "10000",
                    "說明": "甲乙丙丁戊己庚辛丑寅卯",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                }
            ]
            _write_csv(data_dir / "115" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_115)
            _write_csv(data_dir / "116" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_116)

            rows = match_items("115", "116", data_dir=data_dir)
            statuses = [r["status"] for r in rows]
            self.assertNotIn("candidate", statuses)
            self.assertEqual(set(statuses), {"deleted", "added"})

    def test_deterministic_across_reruns(self) -> None:
        """重複執行 match_items 產生的 items_candidates.csv 與 items.csv 內容與順序完全一致（deterministic）。"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            exp_115 = [
                {
                    "year": "115",
                    "page": "61",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "10000",
                    "amount_元": "10000",
                    "說明": "115年度鄉政宣導活動便當及茶水費",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                },
                {
                    "year": "115",
                    "page": "61",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "20000",
                    "amount_元": "20000",
                    "說明": "辦理本鄉村里鄰長文康活動保險及雜支",
                    "經費來源": "本鄉財源",
                    "item_seq": "2",
                },
            ]
            exp_116 = [
                {
                    "year": "116",
                    "page": "61",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "12000",
                    "amount_元": "12000",
                    "說明": "116年度鄉政宣導活動便當及茶水費",
                    "經費來源": "本鄉財源",
                    "item_seq": "1",
                },
                {
                    "year": "116",
                    "page": "61",
                    "plan_code": "33120010101",
                    "用途別_code": "2009",
                    "用途別": "一般事務費",
                    "unit": "式",
                    "qty": "1",
                    "unit_price": "22000",
                    "amount_元": "22000",
                    "說明": "辦理本鄉村里鄰長研習活動保險及雜支",
                    "經費來源": "本鄉財源",
                    "item_seq": "2",
                },
            ]
            _write_csv(data_dir / "115" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_115)
            _write_csv(data_dir / "116" / "expenditure_items.csv", EXPENDITURE_HEADERS, exp_116)

            match_items("115", "116", data_dir=data_dir)
            cand_first = (data_dir / "crosswalk" / "items_candidates.csv").read_text(encoding="utf-8")
            items_first = (data_dir / "crosswalk" / "items.csv").read_text(encoding="utf-8")

            # 第二次重跑
            match_items("115", "116", data_dir=data_dir)
            cand_second = (data_dir / "crosswalk" / "items_candidates.csv").read_text(encoding="utf-8")
            items_second = (data_dir / "crosswalk" / "items.csv").read_text(encoding="utf-8")

            self.assertEqual(cand_first, cand_second)
            self.assertEqual(items_first, items_second)


if __name__ == "__main__":
    unittest.main()
