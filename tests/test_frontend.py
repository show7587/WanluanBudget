"""前端（site/app.js）的導覽邏輯測試：用 Node 的 vm 搭配模擬的 DOM 執行，不需要瀏覽器。

只涵蓋路由、導覽與錯誤處理；不測 CSS、真實版面或 CDN 函式庫。沒有安裝 node 時整個類別會被跳過。
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
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
                self.assertIn("243", r["html"])
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


if __name__ == "__main__":
    unittest.main()
