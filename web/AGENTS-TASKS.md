# 階段 B 任務簡報（給實作者）

專案：萬巒鄉預算查詢前端改版（Vue 3 + Vite + TS + ECharts 5.5.1）。`web/` 是新前端，`site/` 是舊站（**不要改**）。
資料：`site/data/*.json`（由 `scripts/build.py` 產生，**唯讀**，不要改 `data/`、`scripts/`、`raw/`、`site/`）。

## 共通規則
- 只編輯你被指派的檔案；**不要改** `App.vue`、`router.ts`、`main.ts`、`src/data/*`、`src/components/*`、`src/styles/*`（需要共用元件的新功能，請寫在你自己的檔案或你的 view 資料夾內）。
- 金額單位一律「元」，用 `src/data/format.ts`（千分位、`fmtCompact`、百分比 2 位小數）。
- 無障礙（WCAG 2.1 AA）：圖表要有 `aria-label` 與可切換的資料表格；鍵盤可操作；**顏色不能是唯一的資訊載體**（要有 ▲▼ 符號或文字）；RWD（手機寬度 375px 不得橫向捲動頁面）；深色模式用 `tokens.css` 的變數，不要寫死色碼。
- 不要引入新的 npm 套件。
- 完成標準：`cd web && npx vue-tsc --noEmit && npx vitest run && npx vite build` 全過。
- 在你的 worktree 分支上 `git add` + `git commit`（Conventional Commits，繁體中文訊息）。**不要 push。**
- 最後回報：改了哪些檔案、驗證指令與結果、未完成事項。

## 可用的共用資源
- 資料：`useBudget(yearRef)`（`src/composables/useBudget.ts`）→ `{loading,error,index,data,compare}`；`normalizeRevenue(data, compare)`、`normalizeExpenditure(data, compare, view)`（view：政事別｜機關別｜用途別）→ `TreeNode[]`。
- 元件：`ChartPanel`（標題、圖/表切換、匯出）、`TreemapChart`、`DataTable`、`DrillExplorer`（麵包屑＋treemap＋表格＋匯出，路徑 v-model）、`Breadcrumb`、`KpiCard`、`DiffLegend`。
- 路徑狀態：`useQueryPath()`、`useQueryString()`（`src/composables/useRouteState.ts`）。
- 增減色階：`src/data/diffScale.ts`（`diffBand(status,pct)`）。
- 年度取自 `useRoute().params.year`。

## 任務
### B1 總覽（`src/views/OverviewView.vue`，可新增 `src/views/overview/*`）
KPI 卡（歲入、歲出、餘絀、動用以前年度賸餘；對應 `data.overview`）；3 個年度（`index.year_summaries`）歲入 vs 歲出對照長條圖（ECharts，附資料表）；歲入／歲出結構圖（各一，款層級環圈圖或長條，附資料表）；連到歲出、歲入、比較頁的入口卡片（`router-link`，保留目前年度）。

### B2 歲入（`src/views/RevenueView.vue`）
用 `DrillExplorer`：`normalizeRevenue`，rootLabel「歲入」，款→項→子目→細目；`colorBy` 提供切換「依金額（類別色）／依較上年度增減」；路徑用 `useQueryPath()`；顯示比較資料說明（無比較資料的年度要說明「上年度數字取自預算書」）。

### B3 歲出（`src/views/ExpenditureView.vue`）
三視角分頁（政事別／機關別／用途別，`useQueryString('view', ...)`，切換時清掉 path）；各視角用 `DrillExplorer`；用途別註明「大類為依用途別代碼第 1 碼的名稱分類，不是經常／資本拆分」。

### B4 比較（`src/views/CompareView.vue`，可新增 `src/views/compare/*`）
以 `useBudget` 的 `compare`（本年度 vs 上一年度）呈現：歲出（工作計畫／用途別）與歲入（款／項）增減排行（發散長條圖，正負分色並附 ▲▼ 與數字）、`DiffLegend`、增減 % 篩選（全部／新增／增加／減少）、可切換資料表格與匯出。最早年度（沒有比較資料）顯示說明並導向其他頁。

---
# 階段 C 任務簡報：移植舊站剩下的三頁
舊版實作在 `site/app.js`（`renderSearch`、`getSearch`、`renderReference`、`renderMemosPage` 與 memo 相關函式，約第 70–250、557–800 行），可閱讀其行為與資料欄位，但**不要修改 `site/`**，用 Vue 3 + TS 重寫。
共通規則同上（只改自己的檔案；不動 App.vue／router.ts／src/data/*／src/components/*／styles；金額千分位；WCAG 2.1 AA；RWD；深色模式用 tokens）。`minisearch@7.1.0` 已安裝（npm 版，用法與舊版 CDN 版相同）。資料檔：`data/search.json`、`data/memos.json`、`data/reference_114.json`（透過 `import.meta.env`/`fetch("data/…")` 相對路徑載入；失敗要優雅降級並顯示說明）。年度取自 `useRoute().params.year`。
## C1 搜尋 `src/views/SearchView.vue`（可新增 `src/views/search/*`）
`q`（關鍵字）、`kind`（歲入／歲出／全部）、`y`（年度篩選）同步到 URL query；MiniSearch 中文分詞沿用舊版 `tokenize`；結果列表顯示名稱、種類、年度、金額（元，千分位）、預算書頁碼、說明片段（命中字樣標示，不能只靠顏色，用 `<mark>`），並提供連到對應歲入／歲出頁的連結（歲入：`/{年}/歲入?path=revenue:{code}` 等，節點 id 規則見 `src/data/normalize.ts`）。無結果、載入中、載入失敗都要有狀態說明。
## C2 備註 `src/views/MemoView.vue`（可新增 `src/views/memo/*`）
讀 `data/memos.json`（`years[年度]` 陣列），列表可依 `type`（print_typo／print_inconsistent／print_layout／data_gap）與頁碼 `p` 篩選（同步 URL query）；每筆顯示：類型（文字標籤，不只顏色）、位置（scope／page／locator）、印刷原文、資料中文字、建議文字、說明、核對方式與日期、PDF 頁序、狀態；證據圖 `evidence` 路徑若存在則以 `<img>` 顯示（載入失敗就只顯示路徑文字，圖在 `evidence/…` 相對路徑，不在 repo 的 dev 環境可能 404）。
## C3 參考表 `src/views/ReferenceView.vue`（可新增 `src/views/reference/*`）
僅 114 年。讀 `data/reference_114.json`：`{year, tables:[{page, table_seq, source_table, unit, rows, cols, cells:[{r,c,rs,cs,t,v}]}]}`（`r/c` 為列／欄，`rs/cs` 為 rowspan／colspan，`t` 文字，`v` 數值或 null；同一頁可能有多張表，以 `page` 篩選、依 `table_seq` 排序），以頁碼 `p` 切換（同步 URL query），還原成 HTML 表格：每列的格子依 `c` 排序後直接輸出 `<td>`／`<th>`（含 rowspan／colspan，不補空格），數字欄靠右千分位，附頁面提示（`notes` 若有）與表格捲動區（`tabindex=0`、`role=region`、aria-label）。
