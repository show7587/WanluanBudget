# 交接 prompt：逐年趨勢與自選科目比較

> 用法：把下面「---」之間的內容整段貼給接手的 AI（在使用者本機、repo 根目錄開啟的 session）。

---

你接手的是「萬巒鄉預算資料庫」repo 的新功能：**逐年趨勢與自選科目獨立比較**。你的角色是**主 session（協調者）**：負責契約、資料檢核與 code review；程式實作交給 agy（Antigravity CLI）。

## 開工前必讀（依序）

1. `CLAUDE.md`：專案規則，優先於任何預設行為。特別注意：用繁體中文回覆；`raw/**` 不改；對不上的不自動修正；不要擴大範圍；commit 前列出檔案清單與完整訊息並等使用者確認；不直接推 `main`，PR 由使用者自己合併。
2. `docs/PLAN-series.md`（v2）：本功能的完整計畫，是唯一依據。v2 已併入獨立審查的所有意見，**不要重新討論已決定事項**。
3. 對照程式：`scripts/build.py` 的 `_collect_year_compare_items`、`_build_compare_json`、`_remap_compare_item_codes`、`_write_compare_files`；`data/crosswalk/codes.csv`；`web/src/router.ts`、`web/src/data/`、`web/src/views/CompareView.vue`。

## 第一步：先問使用者（不要自己決定）

1. 是否核准 `docs/PLAN-series.md` v2？
2. §8 待決定：政事別合計、機關合計、跨計畫用途別合計、歲入／歲出總計，首版要不要放進趨勢功能？（計畫預設為不含）

兩題都得到明確答覆才開始 S0。含糊的回覆不算同意，要再問。

## 執行順序

1. **S0 契約（你自己做）**：依計畫 §3.1、§4 產出 `tests/fixtures/series_sample.json` 與 `tests/fixtures/series_expected.json`，以及前端 `SeriesData` 型別草稿。fixture 必須包含：
   - 114 項 `04-03` → 115 `04-02` 的改碼；
   - 被擠掉的 114 `04-02` 財產售價 → `revenue:04-02@114`；
   - 中間年缺值（`09120010101`：114、116 有，115 無）；
   - 只出現一年的項目、改名、0 值；
   - 一個合成的鏈式改碼案例。

   給使用者看過契約後再派工。
2. **平行派工**：
   - **agy #1 → Lane A**（後端 `series.json` 與 `tests/test_series.py`），worktree `../wb-series-a`、分支 `feat/series-a`。
   - **agy #2 → Lane B**（前端全部），worktree `../wb-series-b`、分支 `feat/series-b`。
   - **你 → Lane C**：`scripts/check_series.py`。只從 CSV 重算，**不得 import `build.py` 的 series 邏輯**，也不讀 `site/data/<年>.json` 的金額。報告輸出到 `reports/check_series.md`。

   給 agy 的指示要包含：計畫中該 lane 的段落、§4 的檔案擁有權表（只能改自己的檔案）、S0 契約檔路徑、驗收指令。agy 在 herdr 的**可見 pane** 開啟；用 `/model` 選模型前先讀畫面確認游標位置。
3. **整合**：A、B 合併到 `feat/series`。
4. **Gate**：你親自重跑 D1–D9（計畫 §5）和 §6 的 code review。**不採信 agy 的自我報告**，所有數字都要自己重跑取得。阻擋項退回 agy 修正後，再重跑 D1–D9。
5. **端到端驗收**：依計畫 §7 第 4 點用瀏覽器實測（`cd web && npm run dev -- --port <沒用過的埠>`；可用 `mcp__browsermcp__browser`，先用 ToolSearch 載入）。
6. **交付**：整理驗證報告給使用者 → 使用者確認 → 列出 commit 檔案清單與完整訊息（Conventional Commits、繁中）→ 等使用者確認 → push 分支 → `gh pr create` → **由使用者自行合併**。

## 最容易做錯的地方（計畫裡都有，這裡再強調）

- **canonical key 不能直接用最新年度的 key**。114 的 `04-03` 改成 `04-02` 會和 114 自己的 `04-02` 撞 key。必須照 §3.1 的「斷鏈 → `@<年>` 後綴」演算法，並輸出 `aliases`。前端所有入口都要**先查 `aliases`，查不到才直接用原始 key**。
- 現有 compare 的 crosswalk 方向是「新年度的碼換成舊年度的碼」，series 的方向相反。D2 交叉比對時，compare 的 key 要先經 `aliases.get("<a>:"+k, k)` 轉換。
- 缺值一律 `null`，不補 0。series 的差額要兩年都有值才計算，和 compare 的 `diff_元`（缺值當 0）**刻意不同**。增減率遇到缺值年**不跳過去比更早的年度**。
- `parent_key`、`children`、`dept`、`政事別`、`unresolved` 都是**逐年**欄位，D5 也要逐年檢查。
- 歲出政事別、機關、用途別視角的彙總節點**不顯示**「看趨勢」入口（除非使用者在第一步決定要包含）。
- `unittest discover` 會重寫 `data/116/*.csv` 與 `reports/validate_116.md`，跑完要 `git status --short` 確認沒有意外變動。
- 暫存檔放 session scratchpad，不放 `/tmp`；heredoc 一律用 `<<'EOF'`。

## 完成定義

計畫 §7 的五項全部通過，`reports/check_series.md` 與 code review 沒有未解決的阻擋項，使用者確認後開出 PR。

---
