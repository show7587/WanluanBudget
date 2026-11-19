"""前端（site/app.js）的導覽邏輯測試：用 Node 的 vm 搭配模擬的 DOM 執行，不需要瀏覽器。

只涵蓋路由、導覽與錯誤處理；不測 CSS、真實版面或 CDN 函式庫。沒有安裝 node 時整個類別會被跳過。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
HARNESS = ROOT_DIR / "tests" / "fixtures" / "frontend_harness.js"
NODE = shutil.which("node")


def run_harness(app_js: Path | None = None) -> list[dict]:
    cmd = [NODE, str(HARNESS)] + ([str(app_js)] if app_js else [])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"frontend harness failed: {proc.stderr}")
    return json.loads(proc.stdout)


@unittest.skipUnless(NODE, "需要 node 才能執行前端測試")
class TestSetNavTolerance(unittest.TestCase):
    """舊版 index.html 被瀏覽器快取、卻載入新版 app.js 時（導覽列沒有 data-nav="ref" 的連結），
    setNav 不可丟錯，所有畫面仍要能正常顯示。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.results = run_harness()

    def _get(self, hash_: str, nav_mode: str, injected: bool = False) -> dict:
        for r in self.results:
            if r["hash"] == hash_ and r["navMode"] == nav_mode and r["injected"] == injected:
                return r
        raise AssertionError(f"沒有情境 {hash_} / {nav_mode}")

    def test_legacy_index_html_without_ref_link_still_renders(self) -> None:
        for hash_ in ("#/114/總覽", "#/115/總覽", "#/116/歲入", "#/114/參考表?p=170"):
            with self.subTest(hash=hash_):
                r = self._get(hash_, "legacy")
                self.assertFalse(r["failed"], f"{hash_} 顯示載入失敗：{r['html'][:200]}")
                self.assertGreater(len(r["html"]), 200)
                # 其他導覽連結仍照常更新
                self.assertEqual(r["overviewHref"], "#/" + hash_.split("/")[1] + "/總覽")

    def test_legacy_reference_page_is_still_reachable_by_url(self) -> None:
        r = self._get("#/114/參考表?p=170", "legacy")
        self.assertIn("reftable", r["html"])
        self.assertIn("歲出按職能及經濟性綜合分類表", r["html"])

    def test_current_index_html_ref_link_follows_reference_years(self) -> None:
        """有連結時的既有行為不變：只有有參考表的年度（114）顯示，並指向該年度的參考表頁。"""
        r114 = self._get("#/114/總覽", "current")
        r115 = self._get("#/115/總覽", "current")
        for r in (r114, r115):
            self.assertFalse(r["failed"], r["html"][:200])
        self.assertFalse(r114["refHidden"])
        self.assertEqual(r114["refHref"], "#/114/參考表")
        self.assertTrue(r115["refHidden"])


    def test_vehicle_table_pages_show_the_glue_note_and_other_pages_do_not(self) -> None:
        """公務車輛明細表（p165–p168）頁面頂端顯示黏連提示；其他參考表頁不顯示。"""
        for page in (165, 168):
            with self.subTest(page=page):
                r = self._get(f"#/114/參考表?p={page}", "current")
                self.assertFalse(r["failed"], r["html"][:200])
                self.assertIn('<p class="warn">', r["html"])
                self.assertIn("黏連", r["html"])
                self.assertIn("已依原書逐列修正", r["html"])
                self.assertNotIn("243", r["html"])
                # 提示在單位那一行之後、表格之前
                self.assertLess(r["html"].index("單位："), r["html"].index('<p class="warn">'))
                self.assertLess(r["html"].index('<p class="warn">'), r["html"].index("reftable"))
        r154 = self._get("#/114/參考表?p=154", "current")
        self.assertFalse(r154["failed"], r154["html"][:200])
        self.assertNotIn('<p class="warn">', r154["html"])
        self.assertNotIn("黏連", r154["html"])

    def test_table_note_is_html_escaped(self) -> None:
        """提示文字經 esc() 跳脫，不可變成可執行的 HTML。"""
        r = self._get("#/114/參考表?p=165", "current", injected=True)
        self.assertFalse(r["failed"], r["html"][:200])
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", r["html"])
        self.assertNotIn("<img src=x", r["html"])


@unittest.skipUnless(NODE, "需要 node 才能執行前端測試")
class TestHarnessSanity(unittest.TestCase):
    def test_harness_detects_missing_nav_link_bug_in_an_unguarded_setnav(self) -> None:
        """確認測試本身有效：把 setNav 的防護拿掉（還原成直接對連結呼叫 setAttribute）後，
        舊版 index.html 的情境必須顯示載入失敗。"""
        import tempfile

        src = (ROOT_DIR / "site" / "app.js").read_text(encoding="utf-8")
        guarded = (
            "  if (refA) {\n"
            '    refA.setAttribute("href", href(year, "參考表"));\n'
            "    refA.hidden = !hasReference(index, year);\n"
            "  }"
        )
        unguarded = (
            '  refA.setAttribute("href", href(year, "參考表"));\n'
            "  refA.hidden = !hasReference(index, year);"
        )
        self.assertIn(guarded, src, "setNav 的防護寫法改變了，請同步更新這個測試")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "app_unguarded.js"
            bad.write_text(src.replace(guarded, unguarded), encoding="utf-8")
            results = run_harness(bad)
        legacy = [r for r in results if r["navMode"] == "legacy"]
        self.assertTrue(legacy)
        self.assertTrue(all(r["failed"] for r in legacy), "沒有防護時，舊版 index.html 的情境都應該顯示載入失敗")
        # 有連結的情境不受影響
        self.assertFalse(any(r["failed"] for r in results if r["navMode"] == "current"))

    def test_harness_detects_missing_alias_field_in_minisearch(self) -> None:
        """測試的測試：把 MiniSearch fields 中的 "alias" 拿掉後，案例 5 的條件必須失敗。"""
        src = (ROOT_DIR / "site" / "app.js").read_text(encoding="utf-8")
        with_alias = 'fields: ["name", "text", "code", "dept", "alias"],'
        without_alias = 'fields: ["name", "text", "code", "dept"],'
        self.assertIn(with_alias, src, "MiniSearch fields 寫法改變了，請同步更新這個測試")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "app_no_alias.js"
            bad.write_text(src.replace(with_alias, without_alias, 1), encoding="utf-8")
            results = run_harness(bad)
        r = next(x for x in results if x.get("id") == "search_116_alias")
        self.assertNotIn("alias", r["searchStub"]["fields"])
        self.assertNotIn("12120010204", r["html"])


@unittest.skipUnless(NODE, "需要 node 才能執行前端測試")
class TestMemosFrontend(unittest.TestCase):
    """S2 備註呈現、備註頁、導覽、搜尋別名、容錯、跳脫與列點擊防誤觸測試。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.results = run_harness()

    def _by_id(self, scenario_id: str) -> dict:
        for r in self.results:
            if r.get("id") == scenario_id:
                return r
        raise AssertionError(f"找不到情境 id={scenario_id}")

    def test_1_revenue_detail_memo_markers_and_panel(self) -> None:
        r114 = self._by_id("rev114_memo")
        self.assertFalse(r114["failed"], r114["html"][:200])
        self.assertIn('class="memo-btn"', r114["html"])
        self.assertIn('data-memo="M114-0001"', r114["html"])
        # 點擊 ⓘ 後面板開啟並呈現原書印刷與證據路徑
        self.assertFalse(r114["panelHidden"])
        self.assertIn("M114-0001", r114["panelHtml"])
        self.assertIn("自治修例", r114["panelHtml"])
        self.assertIn("自治條例", r114["panelHtml"])
        self.assertIn("evidence/114/M114-0001.png", r114["panelHtml"])

        r_none = self._by_id("rev114_nomemo")
        self.assertFalse(r_none["failed"])
        self.assertNotIn("memo-btn", r_none["html"])

        r115 = self._by_id("rev115_memo")
        self.assertFalse(r115["failed"])
        self.assertIn('data-memo="M115-0001"', r115["html"])

        r116 = self._by_id("rev116_memo")
        self.assertFalse(r116["failed"])
        self.assertIn('data-memo="M116-0001"', r116["html"])

    def test_1b_clicking_memo_btn_in_drill_row_does_not_navigate(self) -> None:
        r = self._by_id("rev114_sub_rowguard")
        self.assertFalse(r["failed"])
        self.assertIn('data-memo="M114-0001"', r["html"])
        self.assertTrue(r["rowClickHashUnchanged"], "點擊 .memo-btn 時 tr[data-to] 不得改變 location.hash")
        self.assertTrue(r["rowClickNormalChanged"], "一般點擊 tr[data-to] 仍應導覽")

    def test_2_reference_table_cell_and_page_memos(self) -> None:
        # p165 第 0 列第 7 欄 <td> 有 ⓘ（M114-0013）與 has-memo
        r165 = next(r for r in self.results if r["hash"] == "#/114/參考表?p=165" and r["navMode"] == "current" and not r["injected"])
        self.assertFalse(r165["failed"])
        rows = re.findall(r"<tr>(.*?)</tr>", r165["html"], flags=re.S)
        self.assertGreater(len(rows), 0)
        tds = re.findall(r"<td[^>]*>.*?</td>", rows[0], flags=re.S)
        self.assertGreater(len(tds), 7)
        self.assertIn("has-memo", tds[7])
        self.assertIn('data-memo="M114-0013"', tds[7])

        # p154（無備註）不含 memo-btn
        r154 = next(r for r in self.results if r["hash"] == "#/114/參考表?p=154" and r["navMode"] == "current")
        self.assertFalse(r154["failed"])
        self.assertNotIn("memo-btn", r154["html"])

        # p159 頁首有 ⓘ（M114-0010）
        r159 = self._by_id("ref114_p159")
        self.assertFalse(r159["failed"])
        self.assertIn('data-memo="M114-0010"', r159["html"])
        self.assertLess(r159["html"].index('data-memo="M114-0010"'), r159["html"].index("reftable"))

    def test_3_memos_page_counts_and_filters(self) -> None:
        r114 = self._by_id("memo_page_114")
        self.assertFalse(r114["failed"])
        ids_114 = re.findall(r'data-memo-id="(M114-\d+)"', r114["html"])
        self.assertEqual(len(ids_114), 20)
        self.assertEqual(ids_114, sorted(ids_114))
        for label in ("原書錯字", "原書前後不一致", "原書版面", "資料缺口"):
            self.assertIn(label, r114["html"])

        # 篩選 ?type=print_typo
        with (ROOT_DIR / "data" / "memos.csv").open("r", encoding="utf-8", newline="") as f:
            expected_typo_ids = sorted(
                row["memo_id"] for row in csv.DictReader(f) if row["year"] == "114" and row["type"] == "print_typo"
            )
        r_typo = self._by_id("memo_page_114_typo")
        self.assertFalse(r_typo["failed"])
        self.assertEqual(re.findall(r'data-memo-id="(M114-\d+)"', r_typo["html"]), expected_typo_ids)

        # 篩選 ?p=159
        r_p159 = self._by_id("memo_page_114_p159")
        self.assertFalse(r_p159["failed"])
        self.assertEqual(re.findall(r'data-memo-id="(M114-\d+)"', r_p159["html"]), ["M114-0010"])

        # 115＝5、116＝3
        r115 = self._by_id("memo_page_115")
        self.assertFalse(r115["failed"])
        self.assertEqual(len(re.findall(r'data-memo-id="(M115-\d+)"', r115["html"])), 5)

        r116 = self._by_id("memo_page_116")
        self.assertFalse(r116["failed"])
        self.assertEqual(len(re.findall(r'data-memo-id="(M116-\d+)"', r116["html"])), 3)

    def test_4_memo_nav_visibility_and_redirect(self) -> None:
        r114 = next(r for r in self.results if r["hash"] == "#/114/總覽" and r["navMode"] == "current" and r.get("id") is None)
        r115 = next(r for r in self.results if r["hash"] == "#/115/總覽" and r["navMode"] == "current" and r.get("id") is None)
        r116 = self._by_id("nav_116")
        for y, r in (("114", r114), ("115", r115), ("116", r116)):
            self.assertFalse(r["memoHidden"], f"{y} 備註導覽不應隱藏")
            self.assertEqual(r["memoHref"], f"#/{y}/備註")

        r_excl_nav = self._by_id("memo_year_excluded_nav")
        self.assertTrue(r_excl_nav["memoHidden"])

        r_excl_redir = self._by_id("memo_year_excluded_redirect")
        self.assertFalse(r_excl_redir["failed"])
        self.assertEqual(r_excl_redir["finalHash"], "#/114/總覽")

    def test_5_and_6_merge_memo_aliases_and_search_results(self) -> None:
        r = self._by_id("search_116_alias")
        self.assertFalse(r["failed"])
        stub = r["searchStub"]
        self.assertIsNotNone(stub)
        self.assertIn("alias", stub["fields"])
        self.assertIn("自治條例", stub["doc116Alias"] or "")
        self.assertIn("自治條例", stub["doc114Alias"] or "")
        self.assertFalse(stub["sampleNoMemoHasAliasKey"], "沒有備註的文件不得新增 alias 鍵")
        self.assertFalse(stub["rawSearchMutated"], "傳入的原陣列不得被修改")
        # 案例 6：搜尋「自治條例」於 116 命中 12120010204 且有 ⓘ（M116-0001）
        self.assertIn("12120010204", r["html"])
        self.assertIn('data-memo="M116-0001"', r["html"])

    def test_7_memos_404_graceful_degradation(self) -> None:
        for sid in ("memos404_rev", "memos404_ref", "memos404_search"):
            with self.subTest(scenario=sid):
                r = self._by_id(sid)
                self.assertFalse(r["failed"], f"{sid} 不應顯示載入失敗")
                self.assertNotIn("memo-btn", r["html"])
        r_page = self._by_id("memos404_page")
        self.assertFalse(r_page["failed"], "備註頁 404 不應顯示載入失敗")
        self.assertNotIn("memo-btn", r_page["html"])
        self.assertIn("備註資料無法載入", r_page["html"])

    def test_8_memo_html_escaping(self) -> None:
        r_page = self._by_id("memo_escape_page")
        self.assertFalse(r_page["failed"])
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", r_page["html"])
        self.assertNotIn("<img src=x", r_page["html"])

        r_panel = self._by_id("memo_escape_panel")
        self.assertFalse(r_panel["failed"])
        self.assertFalse(r_panel["panelHidden"])
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", r_panel["panelHtml"])
        self.assertNotIn("<img src=x", r_panel["panelHtml"])


if __name__ == "__main__":
    unittest.main()
