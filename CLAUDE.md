# CLAUDE.md — 萬巒鄉預算資料庫（給 AI 助手的操作手冊）

屏東縣萬巒鄉總預算書（掃描 PDF → OCR）→ 正規化 CSV → 驗證報告 → SQLite／靜態網站。使用者介紹請看 `README.md`；已知問題與待辦看 `docs/TODO.md`；原始規格看 `docs/PLAN.md`（部分已過時，以本檔與程式為準）。

## 先守住的規則

- **一律用繁體中文（zh-TW）回覆**；技術名詞、程式碼、路徑、指令、錯誤訊息維持英文。
- **`raw/**` 永遠不修改。** OCR 錯誤只能登記在 `data/corrections.csv`，且 `reason` 必須寫明依據（哪一頁原件、可由哪些欄位推導）。正確值推導不出來就列進報告交給使用者，**不要猜數字**。
- **對不上的不自動修正。** 驗證報告要誠實列出失敗。
- **不要自行擴大範圍。** 使用者說的範圍就是範圍；含糊的回覆不算同意，直接問。
- **commit／push／PR 流程**：Conventional Commits、訊息用繁體中文；commit 前先列出檔案清單與完整訊息，等使用者明確確認。不直接推 `main`：新分支 → push 分支 → `gh pr create` → **由使用者自己在 GitHub 合併**（合併 `main` 會觸發部署，屬對外發佈）。使用者明說「直接 merge」才可代為合併，且只限他指定的那個 PR。
- **不修改資料庫以外的使用者資料**；暫存檔放 session 的 scratchpad，不放 `/tmp`；不要複製 `data/114/*.pdf` 這類大檔（不在 git 內）。
- 改動 `data/`、schema、序列化這類資料機制時：先唯讀探勘 → 寫計畫 → 獨立審查 → 使用者核准 → 實作 → 獨立驗證。

## 資料流程

```
raw/<年>/part1.md,part2.md,part3.md        OCR 原文（唯讀）
   │  scripts/parse_book.py <年> [--partial] [--reference-tables]
   ▼
data/<年>/summary.csv, revenue_items.csv, plans.csv, expenditure_items.csv  (+ reference_tables.csv 僅 114)
   │  套用 data/corrections.csv；頁碼由目錄頁數與「每頁開頭的表頭」推算
   │  scripts/validate.py <年> [--partial]  → reports/validate_<年>.md（任何失敗 → 退出碼 1）
   ▼
   │  scripts/build.py  → build/budget.sqlite（gitignore）+ site/data/*.json（含 compare_*.json、series.json）
   ▼
site/（純靜態）→ GitHub Pages（.github/workflows/pages.yml，push 到 main 時部署 ./site）
```

- `site/data/series.json`：跨年度時間序列（逐年趨勢頁的資料來源），規則見下方「逐年趨勢（series.json）」；`scripts/check_series.py` 從 CSV 獨立重算並檢核。
- `scripts/match_items.py <舊年> <新年>`：明細層級跨年度配對工具（產出 `data/crosswalk/items_candidates.csv`、`items.csv`），**目前沒有接進網站**，網站的比較只到款／項／細目／計畫層級。
- `data/crosswalk/codes.csv`：跨年度代碼對照。`build.py` 的 `_remap_compare_item_codes` 在比較配對前換代碼，只套用在登記的年度對（例如 114 的項 04-03 ＝ 115 的項 04-02「廢舊物資售價」，115→116 不受影響）。

### 年度與來源

| 年度 | raw 來源 | 解析指令 | 備註 |
|---|---|---|---|
| 116 | MinerU 轉的 md（3 份） | `parse_book.py 116` | 資料核對完成 |
| 115 | part1/part2 為 MinerU md；part3 歲入 23 頁（`ocr_rev/`）、歲出 87 頁（`ocr_exp/`）由 agy 讀 `raw/115/pages_img/` 重新 OCR；參考表沿用 MinerU md | `parse_book.py 115` | 目次用人工整理的 `raw/115/toc.md`；重做前的版本在 `raw/115/original/`；`pages_img/` 不進 git |
| 114 | `data/114/114年度總預算.md` 切出 p1–p90，p91–p173 由使用者補的 `114年萬巒鄉總預算案Part1–3.md` 接上；備份在 `raw/114/original/` | `parse_book.py 114 --partial --reference-tables` | 見下方「114 的特殊處理」 |

`--reference-tables` **只對 114 使用**（115、116 沒有對應的參考表 CSV；對 115 使用會產生不該存在的 `data/115/reference_tables.csv`）。

### 金額單位
總表在書上是**千元**，明細是**元**；CSV 一律存**元**，`build.py` 讀入時**不再 ×1000**。

## 技術與慣例

- **Python 3.14，只用標準函式庫**（`html.parser`、`csv`、`sqlite3`、`difflib`、`argparse`、`unittest`）。不要引入 pandas、BeautifulSoup 等套件。
- **前端是 `web/`**：Vue 3 + TypeScript + Vite 6 + vue-router（hash）+ ECharts 5.5.1 + MiniSearch 7.1.0（皆 npm 版、鎖版本）。`cd web && npm ci && npm test && npm run build`，輸出 `web/dist`；資料讀 `site/data/*.json`（`site/` 現在只放 `build.py` 產生的資料）。頁面：總覽／歲出（政事別、機關別、用途別）／歲入／比較／趨勢／搜尋／參考表／備註。資料轉換層在 `web/src/data/`，各頁在 `web/src/views/`，共用元件在 `web/src/components/`。舊的原生 JS 前端（`site/app.js` 等）已於 2026-11-20 移除，需要時從 git 歷史找。
- 前端路由用 URL hash：`#/<年>/<總覽|歲出|歲入|比較|趨勢|搜尋|參考表|備註>?<參數>`（drill 路徑 `path=<節點id;節點id…>`、歲出視角 `view=`）；`參考表` 只有 114 顯示（`index.json` 的 `reference_years`），`備註` 只在 `index.json` 的 `memo_years` 含該年度時顯示；`趨勢` 只在 `index.json` 的 `series_years` 至少 2 年時顯示（頁面參數見下方「逐年趨勢」）。比較頁一律是 (Y-1, Y)：檢視年度為較新年度、與前一年度比；最早年度（114）沒有比較資料，頁面顯示說明並連到 115／116 的比較頁。`compare.json` 等於最新一對，由 `build.py` 輸出，前端不讀它。
- 檔案分工：`parse_book.py`（約 1,650 行，解析與修正套用）、`memos.py`（備註表與 PDF 頁碼對照的載入、定位與驗證）、`validate.py`（驗證與報告）、`build.py`（SQLite 與網站 JSON、參考表、比較、備註、series）、`check_series.py`（series.json 獨立檢核）、`web/src/`（前端：路由、畫面、資料轉換；趨勢頁在 `web/src/views/trend/` 與 `TrendView.vue`）。
- SQLite 表：`summary`、`revenue_items`、`plans`、`expenditure_items`、`crosswalk_codes`、`crosswalk_items`、`crosswalk_items_candidates`、`memos`；有「未解決」旗標欄位（`unresolved*`），來源是 `corrections.csv` 中 `field=_known_diff` 且 `new=UNRESOLVED` 的列（機制存在，**目前沒有登記任何一筆**）。

### CSV 欄位

- `summary.csv`：`year,source_book,source_table,page,款,項,科目名稱,本年度,上年度,前年度決算`；唯一鍵 `(year, source_table, 科目)`。不同表互相矛盾時**兩筆都保留**。
- `revenue_items.csv`：`year,page,code,name,item_seq,unit,qty,unit_price,amount_元,note,dept`；續頁的列歸給前一個細目，`page` 記實際所在頁。
- `plans.csv`：`year,page_start,page_end,plan_code,name,dept,政事別,總額`。
- `expenditure_items.csv`：`year,page,plan_code,用途別_code,用途別,unit,qty,unit_price,amount_元,說明,經費來源,item_seq`。
- `reference_tables.csv`（114）：通用長格式，一格一列：`year,source_book,source_table,page,table_seq,row_idx,col_idx,rowspan,colspan,text,value_num`。
- 編號：歲入細目 11 碼（例 `01120010201`）、歲出工作計畫 11 碼（例 `33120010101`）、用途別 4 碼（例 `2033`）。

## corrections.csv（OCR 修正登記表）

欄位：`year,page,locator,field,old,new,reason`。唯一鍵 `(page, locator, field)`（`year` 另外限定年度）。

| 目標 | locator | field |
|---|---|---|
| 歲入明細 | `<細目編號>:<item_seq>`（`item_seq` 是整個細目的流水序號，**不是**頁內序號；多頁細目如 `09120010102` 要用跨頁序號） | 欄位名（如 `說明`、`amount_元`…） |
| 歲出明細 | `<計畫編號>:<序號>`（序號是 raw 展開前的列序，**不是** CSV 的 `item_seq`） | 欄位名 |
| 總表（summary） | `<表名>:<款>-<項>-<名稱>`（用**修正前**的值） | `款`／`項`／`科目名稱` |
| 參考表（114）單格 | `ref:r{row}c{col}`（原始座標） | `text` |
| 參考表（114）整列 | `ref:r{row}`（原始列號，沒有 `c`） | `_rows`：`old` 為原始列的 JSON `[[col,rowspan,colspan,text],...]`（須逐字相符），`new` 為替換列的 JSON 陣列（每列同樣是格子陣列；`[]` = 刪除該列） |
| 特殊動作 | 同上 | `_row_action`，`new=DROP_SUBTOTAL_ROW`（排除被當成明細的小計列） |
| 已知差額 | — | `_known_diff`，`new=UNRESOLVED` |

- `old` 必須與 raw **逐字相同**，否則判為「已登記但未套用」，`validate.py` 退出碼 1。
- 參考表的處理順序：(1) 單格文字修正 → (2) 整列取代／刪除 → (3) 重編 `row_idx` 為連續。**所有 locator 一律寫「原始」列號**（OCR HTML 解析後、套用任何修正之前），不是 CSV 裡看到的新列號；同一頁在整列修正之後的列若還要加單格修正，也要寫原始列號。同一原始列不可同時有單格與整列修正（會 raise）。整列修正的替換列必須明確列出該列所有未被上方 rowspan 覆蓋的欄（空格寫 `[col,1,1,""]`），因為 `web/src/views/reference/referenceModel.ts` 只把每列的格子排序後直接輸出 `<td>`、不補空洞，漏格會讓整列往左偏。
- 欄位值可用 `||` 把一列拆成多列。
- 修正筆數：`parse_book.py` 會印出套用／未套用／未登記異常；三者要分別是 N／0／0。

## 逐年趨勢（series.json）

跨 114–116 看單一項目的逐年金額、差額、增減率，並可自選最多 8 個項目（可跨歲入／歲出、不同層級）獨立比較。完整規格是 `docs/series-contract.md`（schema 與規則的唯一依據）；`docs/PLAN-series.md` 是當初的計畫與分工紀錄。

- **收錄範圍**：歲入款／項／子目／細目、歲出工作計畫、計畫下用途別（`object:<計畫碼>|<用途別碼>`）。**不含**政事別、機關、跨計畫用途別合計與歲入／歲出總計。
- **缺值一律 `null`，不補 0。** 差額與增減率要**相鄰兩年都有值**才算，缺值年**不跳過去比更早的年度**；這與 `compare_*.json` 的 `diff_元`（缺值當 0）刻意不同。差額、增減率、指數都不存在 JSON 裡，由前端 `web/src/views/trend/trendModel.ts` 計算。
- **canonical key 與 `aliases`**：歲入項目的代碼依 `data/crosswalk/codes.csv` 沿年度鏈換成最新代碼；被別的舊代碼「認領」而斷鏈的項目加 `@<年>` 後綴（例如 114 的財產售價是 `revenue:04-02@114`，114 項 04-03 的廢舊物資售價則併入 `revenue:04-02`）。`aliases` 記錄所有 `"<年>:<原始key>"` → canonical key。**解析一律先查 `aliases`，查不到才把原始 key 當 canonical key**；不能先查 `items`，否則 `114:revenue:04-02` 會誤命中廢舊物資售價。
- **改 `codes.csv` 會影響 series**：`build.py` 遇到計畫代碼、非相鄰年度列，或同年撞 key 會直接報錯，不默默略過。
- **趨勢頁網址**：`#/<年>/趨勢?items=<key;key…>&mode=amount|yoy|index`；`items` 可放 canonical key 或 `<年>:<原始key>`。「看趨勢」入口在歲入 drill、歲出 drill（只限工作計畫與計畫下用途別）、比較頁（key 是年度對**舊年度**的代碼）與搜尋結果。
- **體積**：`series.json` 約 345KB，上限 350KB（測試有 assert）；再增加年度很可能超過，屆時要評估放寬上限或瘦身欄位。
- **檢核**：`python3 scripts/check_series.py` 從 CSV 獨立重算（不 import `build.py`），做 D1–D9，輸出 `reports/check_series.md`，任一失敗退出碼為 1。`--skip-build` 跳過 D6、`--skip-baseline` 跳過 D8。D6 會跑兩次 `build.py`、D8 會跑 `validate.py` 與 `unittest`，都會重寫 `data/`、`reports/`，跑完要 `git status --short` 確認沒有意外變動。D7 的抽樣清單要人工對照原件，「人工核對」欄不會自動填。

## 備註表（資料備註）

如實記錄預算書原件的印刷錯字、前後不一致、版面限制與資料缺口，同時維持 CSV 數字與原書文字不變（完整欄位與規則見 `docs/MEMOS.md`）。

- **檔案**：`data/memos.csv`（17 欄：`memo_id,year,scope,page,locator,field,type,printed_text,data_text,suggested_text,note,pdf_file,pdf_page,verified_method,verified_on,evidence,status`）、`data/pdf_sources.csv`（已核對的書面頁碼與 PDF 頁序對照）、`docs/evidence/<年>/<memo_id>.png`（裁切灰階證據截圖，進版控）。
- **型別**：`scope` ∈ `revenue_item`｜`expenditure_item`｜`plan`｜`summary`｜`reference_cell`｜`page`；`type` ∈ `print_typo`｜`print_inconsistent`｜`print_layout`｜`data_gap`；`status` ∈ `confirmed`｜`pending_publisher`。
- **驗證規則**：`scripts/memos.py` 的 `validate_memos_global` 與 `validate_memos(<年>)` 檢查 CSV 完整性、年度目錄存在與 V1–V7（唯一 ID、locator 恰好命中 1 列且頁碼相符、`data_text` 逐字 guard、`print_typo` 必填且不同的 `printed_text`/`suggested_text`、`pdf_sources.csv` 頁碼偏移、安全的 `docs/evidence/` 路徑且檔案存在、合法日期）。`validate.py` 與 `build.py` 共用同一組檢查，任一失敗皆中止且 `build.py` 不寫出 `memos.json`。
- **建置輸出**：`site/data/memos.json`（依年度分組、帶解析後的 `target`）、SQLite `memos` 表、`site/data/index.json` 的 `memo_years`。
- **前端行為**：依 `index.memo_years` 載入 `data/memos.json`（載入失敗快取為 `null`、優雅降級）；各畫面有備註的項目顯示 `ⓘ` 按鈕開啟共用詳情面板；備註頁 `#/<年>/備註` 支援 `type` 與 `p` 篩選與連回對應畫面；搜尋索引僅將 `print_typo` 的 `suggested_text` 併入 `alias` 欄位（避免其他類型的說明文字污染搜尋）。
- **證據圖部署與本機預覽**：CI（`.github/workflows/pages.yml`）建置 `web/`；Vite 在 dev 時提供 `docs/evidence`、build 時複製到 `web/dist/evidence`（`web/vite.config.ts` 的 `siteData` plugin），圖片不 commit 進 `site/`。圖片載入失敗時前端降級只顯示路徑文字。
- **新增／修改備註的標準作法**：先對照 PDF 原圖並視需要存證據圖 → 更新 `data/memos.csv`（必要時先補已核對的 `data/pdf_sources.csv`）→ 必跑 `python3 scripts/validate.py <年> [--partial]`、`python3 scripts/build.py`、`python3 -m unittest discover -s tests`。

## 驗證（validate.py）檢查什麼

歲入：細目明細加總 = 區塊表頭預算金額；細目 → 子目 → 項 → 款 → 總計與 part1 的歲入來源別總表一致。
歲出：明細加總 = 用途別小計 = 計畫總額；用途別對照政事別；計畫對照 part1 政事別合計。
機關別：p10「歲出機關別預算比較總表」的「代表會主管」= 鄉民代表會各計畫加總；「統籌支撥科目」= 退休撫卹支出＋補助及其他支出的計畫加總（三年皆相符）。
其他：未登記的數字異常（千分位黏連等）、未套用的修正、`summary.csv` 跨表衝突（列出各自頁碼）。

驗證輸出的基準（目前）：

```
114 --partial：歲出計畫 50/50、用途別 291/291、機關別 2/2、跨表衝突 2、備註 20/20
115          ：48/48、300/300、2/2、衝突 0、備註 5/5
116          ：49/49、296/296、2/2、衝突 2、備註 3/3
```

報告裡「失敗 **0**」這類統計字樣本身也含「失敗」二字，判斷要看表格列，不要只 grep。

## 常用指令與測試

```bash
python3 scripts/parse_book.py 114 --partial --reference-tables
python3 scripts/validate.py 114 --partial
python3 scripts/build.py                       # 決定性：重跑不應產生差異
python3 scripts/check_series.py                # series.json 獨立檢核 D1–D9（見「逐年趨勢」）
python3 -m unittest discover -s tests          # 約 120 個（Python）；前端測試在 web/：cd web && npm test
```

**重要副作用**：`unittest discover` 會對真實 repo 重跑 `parse_book.py 116` 與 `validate.py 116`，寫回 `data/116/*.csv` 與 `reports/validate_116.md`。結果必須與 `HEAD` 完全相同（冪等）；跑完請 `git status --short` 確認沒有意外變動。

本機預覽：`cd web && npm run dev -- --port <埠>`（建議換沒用過的埠，避免瀏覽器快取舊頁面）。 真實瀏覽器檢查可用 `mcp__browsermcp__browser`（延遲載入工具，先用 ToolSearch 載入）。

## 已知限制與資料筆記

### 114 的特殊處理
- 114 一律用 `--partial`。不帶時會在三處失敗（part1 表頭被 OCR 成「萬縊」、歲入表頭 16/24 頁、歲出表頭 82/93 頁）；修法是重新 OCR 並替換 `raw/114`，但會讓既有修正的 `old` 對不上，而且「嚴格模式」本身不增加正確性證據。`--partial` 下表數與目錄頁數的核對已通過。
- `raw/114/part2.md`（p11–p36 的預算表）沒有任何程式讀它，不影響已發布資料；其機關別資訊已用 p10 核對。
- 書面 PDF：`data/114/114年度萬巒鄉總預算Part1.pdf`（p1–p90 為主）與 `…Part2.pdf`（88 頁；PDF 第 n 頁約對應原書 p(88+n)，到 p153；p154 之後偏移，第 77、83 頁是只印標題的扉頁，第 88 頁空白）。PDF 為掃描影像、**無文字層**，也**不在 git 內**（`.gitignore` 的 `data/114/*.pdf`）。另有 `114年度屏東縣萬巒鄉總決算.pdf` 與 `…第一次追加(減)預算案.pdf`，**從未打開過**，內容與可用性未知。
- 用 PDF 做獨立核對時：PDF 沒有文字層，需先 `pdftoppm`（`brew install poppler`）轉圖；做法是請另一個模型**不看現有 CSV** 獨立轉錄圖片，再用**確定性腳本**逐格 diff，只裁決不一致處。已完成的核對：歲出明細 p91–p153（63 頁、408 列）金額零差異，6 格說明文字已依原書修正；參考表 p154–p173 除 p165（已修正）與 p159（缺「備註」欄、暫不處理）外與原件一致。

### 原書本身的印刷不一致（保留原樣，不要改）
- 114：稅課收入前年度決算 p1 為 219,572、p6 為 219,573；其他收入 p1 為 7,322、p6 為 7,321（p6 影像已確認）。
- 114：雜項收入 p5 印項 01、p6 印 02，`summary.csv` 照 p5 保留。
- 116（TODO T4）：p1 上年度歲出基準不一致（267,169／267,969／271,169）；p10 前年度決算合計印 322,278，三個機關加總是 353,260。需向公所質詢，由使用者處理。
- p160／p161 的「員」「工」分組標題；p165／p167 表頭的「燃料使用費(全年))」（真的印兩個右括號）；p97 役政說明文字、p55 第 10／17 筆說明、p44／p53 的括號（使用者已確認原件如此）。
- 「資本移轉」被頁面切開：p170／p172 最右欄只印「資」（已依使用者指示補成「資本移轉」），p171／p173 左側印「本移轉」（保持原樣）。「商品及勞務購買支出」是依影像兩直行組合，書內沒有第二個來源。
- 歲出明細說明裡的省略號（例如「第113....號」）點數是原書印刷，不是雜訊；比對時要看原圖數點。

### 參考表（reference_tables.csv，僅 114）
- 只在 CSV 與網站「參考表」頁呈現，內容為 OCR 原樣，只套用 `corrections.csv` 登記過的修正；115、116 沒有。
- **p159 人事費彙計表的「備註」欄沒有資料，所以不列出。** 原書在「合計」右邊有一欄「備註」（表頭有字、欄內空白），OCR 只輸出 9 欄（col 0–8），漏了整欄。只影響表頭、不影響任何數字；現有 `ref:` 修正只能改既有儲存格文字、不能新增儲存格，使用者決定先記錄、不動程式與資料（`docs/TODO.md` 待辦 9）。
- p164「一、考察鄉民代表大陸考察」是類別標題與計畫名稱兩列併成一格，內容正確。
- **p165 公務車輛明細表的 OCR 列黏連已修正**（2026-11-19，PR #8）：原書分開的列（每組的「小計」列＋下一組的「標頭」列）被 OCR 併成一列並帶錯的 `rowspan`（車輛數 `243` 其實是 24 與 3、`34` 是 3 與 4、`41` 是 4 與 1，環保業務的小計「1」遺失）。用上面的「整列修正」機制登記 7 筆（4 取代、3 刪除），p165 還原為 24 列，並與 Part2.pdf 第 78 頁的獨立轉錄逐格相符；內部加總（24 = 3+4+1+16、各組小計與燃料使用費）有測試（`tests/test_reference_rows.py`）。p166–p168 對照原件後沒有黏連。網站在 p165–p168 顯示的提示（`build.py` 的 `_REFERENCE_NOTES`）已改為「p165 已依原書逐列修正」。

### 其他未完成
- `raw/114/part2.md` 的 p27 歲出機關別預算表下半部遺失、p16–p17、p18–p19 兩組表格被合併，目前 parser 不解析（`docs/TODO.md` T5 待辦 3）。
- p91–p173 的歲出明細以外，114 的 p1–p90 尚無「二次獨立讀取＋逐格比對」；說明文字、名稱、單位這類沒有數字約束的欄位是盲區。
- 明細層級（說明欄各列）的跨年度配對（`match_items.py`）尚未接進網站；跨年度比較目前只到款／項／子目／細目／工作計畫／用途別（趨勢頁）。

## 踩過的坑

- **heredoc 一律用有引號的分隔符 `<<'EOF'`**。曾因沒加引號，文字中的反引號被當成命令執行，把使用者未 commit 的檔案收進 stash（已用 `git stash pop` 還原並以 sha256 核對）。內含反引號的文字改用 Write／Edit 寫檔。
- zsh 不會把存在變數裡的檔案清單自動拆開（`for f in $FILES` 只得到一個字串）；同理 `python3 scripts/validate.py "114 --partial"` 會被當成單一參數而失敗。
- 對含大 PDF 的 `data/114` 不要整個複製；要複製 repo 做實驗用 `rsync -a --exclude='.git' --exclude='*.pdf' --exclude='pages_img' --exclude='images'`。
- 工具可能把輸出導到 `/tmp` 的暫存檔，要立刻清掉；一律用 scratchpad。
- 在有未 commit 變更時要開另一條分支的工作，用 `git worktree add ../<目錄> -b <分支> main`，不要在同一個 checkout 切來切去；完成後記得 `git worktree remove`。
- 用 agy（Antigravity CLI）做獨立轉錄或實作時，在 herdr 的**可見 pane** 開啟；在 `/model` 選單用方向鍵選模型前，**先讀畫面確認游標位置**（游標會停在上次的模型上）；主 session 必須**獨立重跑驗證**，不採信 agy 的自我報告（曾有報告引用錯誤數字的情況）。

## 目錄速查

```
raw/<年>/                 OCR 原文（唯讀）；115 另有 ocr_exp/ ocr_rev/ toc.md original/
data/<年>/                CSV；data/corrections.csv；data/memos.csv；data/pdf_sources.csv；data/crosswalk/codes.csv
scripts/                  parse_book.py  validate.py  build.py  memos.py  match_items.py  check_series.py
reports/                  validate_<年>.md（由 validate.py 產生，會進 git）  check_series.md（由 check_series.py 產生）
site/                     data/*.json（由 build.py 產生，會進 git；前端 web/ 讀取）
web/                      Vue 3 + Vite 前端（src/data 轉換層、src/views 各頁、src/components、tests）
build/budget.sqlite       本機 SQLite（gitignore）
tests/                    test_s1/s2/s3、test_build、test_compare、test_memos*、test_validate_agency、test_series、test_series_fixture；fixtures/（含 series_sample／series_expected）
docs/                     PLAN.md  TODO.md  MEMOS.md  PLAN-series.md  series-contract.md  evidence/<年>/*.png
議事記錄_依科室分類.md    鄉民代表會議事記錄筆記，與預算資料庫無關
```
