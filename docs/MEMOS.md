# 資料備註表（`data/memos.csv`）與 PDF 頁碼對照（`data/pdf_sources.csv`）

如實記錄總預算書 PDF 原件的印刷錯字、前後不一致、版面限制與資料缺漏，同時維持 CSV 數字與原文不變。

## 1. `data/memos.csv` 欄位定義

UTF-8 編碼，標準 CSV 引號規則（含逗號、引號、換行者以雙引號包住）。

| 欄位 | 說明 | 必填 |
|---|---|---|
| `memo_id` | 穩定唯一 ID（例：`M114-0001`，依年度流水號） | 是 |
| `year` | 預算年度（例：`114`、`115`、`116`） | 是 |
| `scope` | 備註層級（見第 3 節） | 是 |
| `page` | 書面頁碼（正整數） | 是 |
| `locator` | 資料列定位鍵（見第 3 節；`scope=page` 時為空字串） | 依 `scope` |
| `field` | 備註所指欄位名稱（例：`note`、`說明`、`text`、`前年度決算`；`scope=page` 可空） | 依 `scope` |
| `type` | 備註類型（見第 2 節） | 是 |
| `printed_text` | 原書印刷原文（逐字）；數字不一致可寫成 `p1:219,572｜p6:219,573` | 依 `type` |
| `data_text` | 目前 CSV 該欄位的實際值（逐字），作為防止資料被意外改動的 guard | 選填 |
| `suggested_text` | 正確或通順的寫法（`print_typo` 必填，其他類型可空） | 依 `type` |
| `note` | 繁體中文說明，描述原書狀況與使用者應注意之處 | 是 |
| `pdf_file` | 來源 PDF 檔名（須存在於 `data/pdf_sources.csv`） | 是 |
| `pdf_page` | PDF 檔內頁序（須等於 `page + pdf_page_offset`） | 是 |
| `verified_method` | 核對方式（例：`人工對照原圖`、`獨立轉錄比對（agy）＋原圖裁決`） | 是 |
| `verified_on` | 核對日期（`YYYY-MM-DD`） | 是 |
| `evidence` | repo 內相對路徑，指向裁切之灰階 PNG（`docs/evidence/<年>/<memo_id>.png`，建議 `< 80 KB`） | 選填 |
| `status` | `confirmed`（已對照原圖）｜`pending_publisher`（待公所確認） | 是 |

> **關於 `printed_text` 與 `data_text` 的差異**：`printed_text` 是依原書逐字轉錄（含括號、逗號等標點符號的全半形寬度），`data_text` 則是目前 CSV 該欄位的實際值；兩者可能因專案的 OCR 正規化慣例（例如括號、逗號寬度）而不同，兩者之間的差異本身就是備註所要記錄的事實之一。證據截圖（`evidence`）是判斷原書印刷樣貌的最終依據。
>
> **關於 `printed_text` 的描述性標記慣例**：`printed_text` 原則上逐字等於原書印刷（`print_typo` 類必須逐字，含標點寬度）；但描述性備註（例如 `data_gap`、`print_layout`、`print_inconsistent` 類）可使用說明性標記（如以「｜」分隔多個印刷位置、或加註 `（兩直行）` 等括註），這些標記並非書上所印之字，必須能從 `note` 看出其為說明。

## 2. 類型定義（`type`）

- `print_typo`：原書印刷錯字或贅字／漏字／括號不配對（須填 `printed_text` 與 `suggested_text`，且兩者不同）。
- `print_inconsistent`：原書不同表格或不同欄位之間前後不一致（例如 114 p1 vs p6 決算數、116 T4）。
- `print_layout`：原書版面排版造成的資料限制（例如跨頁裁切「資」／「本移轉」、兩直行組合欄位、分組標題）。
- `data_gap`：OCR 或資料結構缺漏／限制（例如 114 p159 缺「備註」欄、115 表頭 0 千元細目空白存 0）。

## 3. `scope` 與 `locator` 格式

| `scope` | 對應 CSV | `locator` 格式 | `page` 核對方式 |
|---|---|---|---|
| `revenue_item` | `data/<年>/revenue_items.csv` | `<細目編號>:<item_seq>` | `row["page"] == page` |
| `expenditure_item` | `data/<年>/expenditure_items.csv` | `<計畫編號>:<用途別代碼>:<item_seq>` | `row["page"] == page` |
| `plan` | `data/<年>/plans.csv` | `<計畫編號>` | `page_start <= page <= page_end` |
| `summary` | `data/<年>/summary.csv` | `<source_table>:<科目名稱>` | `row["page"] == page` |
| `reference_cell` | `data/<年>/reference_tables.csv` | `r<列>c<欄>`（修正後最終 `row_idx`／`col_idx`） | `row["page"] == page` |
| `page` | 整頁層級 | 空字串 `""` | 該年度任一 CSV 涵蓋該頁碼 |

## 4. 新增備註的步驟

1. 先從 PDF 原圖（或已確認的獨立轉錄）確認原文與書面頁碼，必要時裁切 300 dpi 灰階 PNG（`< 80 KB`）存至 `docs/evidence/<年>/<memo_id>.png`。
2. 查詢對應年度 CSV 的精確 `locator` 與 `data_text`（逐字）。
3. 確認 `data/pdf_sources.csv` 已收錄該區段，依 `pdf_page = page + pdf_page_offset` 計算 `pdf_page`；未核對的區段不得推測。
4. 將新列加入 `data/memos.csv`（注意含半形逗號之欄位須以雙引號包住）。
5. 執行 `python3 scripts/validate.py <年> [--partial]` 與 `python3 -m unittest discover -s tests`，確認規則 V1–V7 與跨年度／CSV 結構檢查全數通過且退出碼為 0：
   - `data/memos.csv` 必須包含所有必要欄位，且每列欄位數須與表頭相符。
   - 每筆備註的 `year` 必須對應存在的 `data/<年>/` 目錄（無資料年度的備註在任一年度執行 `validate.py` 時皆會導致退出碼 1）。
   - 每筆備註的 `year`、`page`、`pdf_page` 欄位前後不得有空白（V1 檢查失敗並回報 `memo_id` 與欄位名）。
   - `evidence` 若有值，必須為 `docs/evidence/` 開頭的相對路徑、不得含 `..`、不得為絕對路徑，且檔案必須存在。
   - `scripts/build.py` 建置時若偵測到 `data_dir/memos.csv`，驗證所讀的檔案必須與輸出所讀的為同一份（`(effective_root / "data").resolve() == data_dir.resolve()`，否則拋出 `ValueError` 且不寫出 `memos.json`）。

## 5. `data/pdf_sources.csv` 說明

記錄各年度 PDF 檔內頁序與書面頁碼的對照區段，僅收錄已對照原圖確認的區段：

`pdf_page = book_page + pdf_page_offset`

欄位：`year,pdf_file,book_page_from,book_page_to,pdf_page_offset,note`。無書面頁碼之扉頁或空白頁（例如 114 Part2 第 77、83 頁扉頁，第 88 頁空白）記載於 `note`。

## 6. 頁碼對照核對紀錄

以下各區段皆已於 2026-11-19 由 PDF 原圖實際渲染並讀取書面印出頁碼獨立確認：

| 年度 | PDF 檔案 | 抽驗 PDF 頁序 | 原圖印出書面頁碼 | 區段偏移（`pdf - book`） | 結果 |
|---|---|---:|---:|---:|---|
| 114 | `114年度萬巒鄉總預算Part1.pdf` | 第 93 頁 | 87 | +6 | 符合 |
| 114 | `114年度萬巒鄉總預算Part2.pdf` | 第 12 頁 | 100 | -88 | 符合 |
| 114 | `114年度萬巒鄉總預算Part2.pdf` | 第 72 頁 | 160 | -88 | 符合 |
| 114 | `114年度萬巒鄉總預算Part2.pdf` | 第 78 頁 | 165 | -87 | 符合 |
| 114 | `114年度萬巒鄉總預算Part2.pdf` | 第 86 頁 | 172 | -86 | 符合 |
| 115 | `115年度總萬巒鄉總預算案.pdf` | 第 11 頁 | 5 | +6 | 符合 |
| 115 | `115年度總萬巒鄉總預算案.pdf` | 第 70 頁 | 60 | +10 | 符合 |
| 116 | `116年度總萬巒鄉總預算案(P1-10).pdf` | 第 16 頁 | 10 | +6 | 符合 |
| 116 | `116年度總萬巒鄉總預算案(P37-175).pdf` | 第 91 頁 | 125 | -34 | 符合 |

## 7. 建置輸出（`scripts/build.py`）

執行 `python3 scripts/build.py` 會讀取 `data/memos.csv`，產生以下決定性輸出：

### `site/data/memos.json`

- 結構：`{"years": {"114": [...], "115": [...], "116": [...]}}`，年度鍵升冪排列，各年度內依 `memo_id` 升冪排列；無備註的年度不輸出。
- 每筆包含 `data/memos.csv` 的全部 17 個欄位（其中 `year`、`page`、`pdf_page` 轉為整數，其餘維持字串）及解析後的 `target` 物件：
  - `revenue_item`：`{"kind":"revenue","search_id":"<年>-revenue-<細目>-<item_seq>","code":"<細目>","item_seq":<int>,"page":<int>}`
  - `expenditure_item`：`{"kind":"expenditure","search_id":"<年>-expenditure-<計畫>-<用途別>-<item_seq>","plan_code":"<計畫>","用途別_code":"<用途別>","item_seq":<int>,"page":<int>}`
  - `plan`：`{"kind":"plan","search_id":"<年>-plan-<計畫編號>","plan_code":"<計畫編號>"}`
  - `summary`：`{"kind":"summary","search_id":"<search.json 對應 id>","source_table":"<表名>","科目名稱":"<科目>","field":"<欄位>","page":<int>}`
  - `reference_cell`：`{"kind":"reference","page":<int>,"row":<int>,"col":<int>}`
  - `page`：`{"kind":"page","page":<int>}`
- 建置時會驗證上述 `search_id` 皆存在於 `site/data/search.json`、`reference_cell` 皆存在於對應 `reference_<年>.json`，找不到即失敗。

### SQLite `memos` 表（`build/budget.sqlite`）

- 包含 `data/memos.csv` 全部 17 欄（`year`、`page`、`pdf_page` 為 `INTEGER`，`memo_id` 為 `PRIMARY KEY`）另加 `target_kind`（`TEXT`）與 `target_search_id`（`TEXT`，`reference_cell` 與 `page` 為 `NULL`）。

### `site/data/index.json`

- 新增 `memo_years` 整數陣列（遞增排序，列出有備註的年度，例如 `[114, 115, 116]`）。其餘欄位與既有建置結果完全相同。

## 8. 網站呈現（`site/`）

### 資料載入與容錯

- 前端僅在 `site/data/index.json` 的 `memo_years` 涵蓋目前年度時才請求 `data/memos.json`；任何載入失敗（404、網路錯誤、JSON 解析失敗）一律回傳 `null` 並快取，不重複請求、不影響既有頁面顯示。
- 沒有備註的列、沒有備註資料的年度或 `memos.json` 載入失敗時，既有畫面與原版完全一致（不出現 `ⓘ`，也不出現「載入失敗」）；僅在直接開啟備註頁且載入失敗時顯示「備註資料無法載入」。

### `ⓘ` 標記掛載規則與詳情面板

有備註的項目旁顯示 `<button type="button" class="memo-btn" data-memo="..." aria-label="...">ⓘ</button>`，點擊開啟單一共用的詳情面板（桌機為右下浮動卡片，手機寬度 ≤ 640px 為貼底卡片；可由關閉鈕、再點同一個 `ⓘ` 或按 `Esc` 關閉）。點擊 `ⓘ` 不會觸發所在列（`tr[data-to]`）的導覽。多筆備註對應同一掛載點時，單一 `ⓘ` 內一次列出全部。

| `target.kind` | 掛載位置 |
|---|---|
| `revenue` | 歲入細目頁 `detailTable` 內 `code` 與 `item_seq` 皆相符的列；上層 `childTable` 中 `level=細目` 且 `code` 相符的列 |
| `expenditure` | 歲出用途別頁 `detailTable` 內 `plan_code`、`用途別_code`、`item_seq` 皆相符的列；`childTable` 中對應 `用途別` 列與 `工作計畫` 列（含其下屬歲出備註） |
| `plan` | 歲出 `childTable` 與頁首的對應 `工作計畫` |
| `summary` | 備註頁與搜尋結果（以搜尋文件 `id == target.search_id` 比對） |
| `reference` | 參考表對應頁碼與 `(r, c)` 的 `<td>`（附加 `has-memo` class，不更動儲存格順序與 rowspan） |
| `page` | 參考表該頁頁首的頁碼／單位說明列 |
| 搜尋結果 | 任何搜尋文件 `id` 等於備註 `target.search_id` 的結果列 |

詳情面板與備註頁共用同一套欄位渲染邏輯，所有文字皆經 `esc()` 跳脫；顯示中文類型、頁碼、原書印刷（`printed_text`）、資料目前存的（`data_text`）、建議寫法（`suggested_text`，空則省略）、說明（`note`）、來源 PDF 檔名與頁序、核對方式與日期、狀態與證據圖。

### 備註頁（`#/<年>/備註`）

- 導覽列「資料備註」連結僅在 `index.memo_years` 含目前年度時顯示；直接開啟無備註年度的 `#/<年>/備註` 時導向該年度總覽。
- 支援 URL 篩選參數 `type`（備註類型）與 `p`（書面頁碼），兩者可組合；卡片依 `memo_id` 穩定排序，並提供連回對應歲入／歲出／搜尋／參考表畫面的連結。

### 搜尋別名（`mergeMemoAliases`）

- 建立 MiniSearch 索引時，純函式 `mergeMemoAliases(docs, memos)` 只將 `type === "print_typo"` 且 `suggested_text` 非空的備註併入對應搜尋文件的 `alias` 欄位，並將 `"alias"` 加入 MiniSearch 的 `fields`（不修改原始文件物件，無對應備註的文件不新增 `alias` 鍵）。
- **只併 `print_typo` 的理由**：其他類型（如 `print_layout`、`print_inconsistent`、`data_gap`）的 `suggested_text` 可能是說明性文字或跨頁組合詞，併入搜尋索引會造成非預期命中並污染搜尋結果；僅收錄 `print_typo` 可精準解決「原書錯字導致正確寫法查不到」（如「自治修例」→「自治條例」）的需求。

### 證據圖部署、降級與本機預覽

- 證據圖版本控管於 `docs/evidence/<年>/<memo_id>.png`，不 commit 進 `site/`；`site/evidence/` 已加入 `.gitignore`。
- GitHub Actions（`.github/workflows/pages.yml`）在 `actions/upload-pages-artifact@v3` 之前執行 `cp -r docs/evidence site/evidence`，使發佈後的網站可由相對路徑 `evidence/<年>/<memo_id>.png` 載入。
- 前端只處理以 `docs/evidence/` 開頭的 `evidence` 路徑；圖片載入失敗時（例如本機預覽未複製圖片）會移除 `<img>` 並優雅降級為只顯示路徑文字，不呈現破圖。
- **本機預覽顯示證據圖**：`cd web && npm run dev` 即可，dev server 會直接提供 `docs/evidence`（建置時複製到 `web/dist/evidence`）。
