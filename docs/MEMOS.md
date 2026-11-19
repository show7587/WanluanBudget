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
5. 執行 `python3 scripts/validate.py <年> [--partial]` 與 `python3 -m unittest discover -s tests`，確認規則 V1–V7 全數通過且退出碼為 0。

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
