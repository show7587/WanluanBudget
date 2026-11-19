# 萬巒鄉預算資料庫

把**屏東縣萬巒鄉公所**的年度總預算書（PDF／OCR 轉檔）整理成**可查詢、可驗證、可跨年度比較**的資料庫，並提供公開的靜態網站。

- 網站：<https://show7587.github.io/WanluanBudget/>
- 目前收錄：**114、115、116** 三個年度的總預算案

## 這個專案要解決什麼問題

預算書是掃描 PDF，OCR 後的文字充滿合併儲存格、數字黏連與換行斷字，沒辦法直接搜尋或比較。這個專案做三件事：

1. **正規化**：把 OCR 原文解析成結構化的 CSV，每一筆資料都記錄它在預算書的**第幾頁**。
2. **驗證**：用預算書自己的加總關係（細目 → 子目 → 項 → 款 → 總計、用途別 → 計畫 → 政事別 → 總計）與跨表對照，找出 OCR 錯誤與原書本身的不一致，結果寫成報告，**對不上的不自動修正**。
3. **呈現**：做成靜態網站，可逐層展開歲入、歲出，跨年度比較增減，並以關鍵字搜尋說明欄。

## 資料內容

| 資料 | 說明 |
|---|---|
| `summary.csv` | 各種總表（歲入來源別、歲出政事別、歲出機關別、收支簡明比較等）的本年度、上年度、前年度決算，**單位已統一為元** |
| `revenue_items.csv` | 歲入明細（款 → 項 → 子目 → 細目，含單位、數量、單價、金額、說明、頁碼） |
| `plans.csv` | 歲出工作計畫（編號、名稱、機關、政事別、總額、起訖頁） |
| `expenditure_items.csv` | 歲出明細（計畫 → 用途別 → 明細，含說明與經費來源、頁碼） |
| `reference_tables.csv`（僅 114） | 預算書最後的參考表（各機關用途別分析、人事費彙計、公務車輛明細等）的儲存格資料 |
| `crosswalk/codes.csv` | 跨年度科目／計畫編號對照（預算書改編號時使用） |
| `corrections.csv` | 人工修正 OCR 的登記表，每一筆都附依據 |
| `memos.csv` | 資料備註表：如實記錄原書印刷錯字、前後不一致、版面限制與資料缺口，附 PDF 頁序與證據截圖 |
| `pdf_sources.csv` | 已核對之各年度 PDF 檔內頁序與書面頁碼對照區段 |

各年度資料放在 `data/<年度>/`。OCR 原文放在 `raw/<年度>/`，**永遠不修改**。

## 網站功能

- **總覽**：收支簡明、歲入來源別與歲出政事別、經常門與資本門比例。
- **歲出／歲入瀏覽**：政事別 → 機關 → 工作計畫 → 用途別 → 明細逐層展開，每一列都標示預算書頁碼；篩選條件放在 URL，可以直接分享連結。
- **比較**：相鄰年度（114 vs 115、115 vs 116）在款、項、細目、計畫等層級的金額增減與增減百分比；只出現在其中一年的項目會標示「僅 115」之類的標籤。
- **搜尋**：跨年度搜尋說明、名稱與編號，可依年度與歲入／歲出篩選；原書錯字備註的建議寫法也會併入搜尋別名，輸入正確寫法同樣查得到。
- **參考表**（僅 114）：依原書頁碼瀏覽 p154–p173 的參考表。
- **資料備註**：有備註的明細列、工作計畫、搜尋結果與參考表儲存格旁顯示 `ⓘ` 標記，點開可查看原書印刷、目前資料值、建議寫法、來源 PDF 頁序與證據截圖；亦可至「資料備註」頁依類型與頁碼篩選並連回對應畫面。
- 手機寬度可正常使用。

## 快速開始

需求：Python 3.14（只用標準函式庫，不需要安裝套件）；跑前端測試需要 Node.js（沒有時該項測試會自動略過）。

```bash
# 1. 解析 raw → data/<年度>/*.csv
python3 scripts/parse_book.py 116
python3 scripts/parse_book.py 115
python3 scripts/parse_book.py 114 --partial --reference-tables   # 114 需 --partial，詳見 CLAUDE.md

# 2. 驗證 → reports/validate_<年度>.md（有任何失敗會以退出碼 1 結束）
python3 scripts/validate.py 116
python3 scripts/validate.py 115
python3 scripts/validate.py 114 --partial

# 3. 建置 SQLite（build/budget.sqlite）與網站資料（site/data/*.json）
python3 scripts/build.py

# 4. 測試
python3 -m unittest discover -s tests

# 5. 本機預覽
cd site && python3 -m http.server 8000     # 開 http://127.0.0.1:8000
```

SQLite 只供本機查詢，不部署。例如查某個細目的頁碼：

```bash
sqlite3 build/budget.sqlite "select page, amount_元 from revenue_items where code='01120011701'"
```

## 專案結構

```
raw/<年度>/              OCR 原文（唯讀，永不修改）
data/<年度>/             正規化 CSV（source of truth）
data/corrections.csv     OCR 修正登記表
data/memos.csv           資料備註表（原書錯字、不一致、版面限制與資料缺口）
data/pdf_sources.csv     PDF 頁序與書面頁碼對照表
data/crosswalk/          跨年度代碼對照
scripts/                 parse_book.py / validate.py / build.py / memos.py / match_items.py
reports/                 validate_<年度>.md 驗證報告
site/                    純靜態網站（index.html、app.js、style.css、data/）
tests/                   unittest
docs/                    PLAN.md（原始規格）、TODO.md（已知問題與待辦）、MEMOS.md、evidence/（證據截圖）
.github/workflows/       pages.yml（push 到 main 自動部署）
```

## 資料品質

- 歲入、歲出的各層加總與總表對照都在 `reports/validate_<年度>.md`；三個年度目前都通過。
- 預算書本身有少數**原書印刷的不一致**（例如同一個數字在 p1 與 p6 不同），這些保留原樣並列在報告與 `docs/TODO.md`，等待向公所確認。
- 114 年度有一部分頁面沒有書面原件可對照，詳見 `CLAUDE.md` 的「已知限制」。

## 部署

push 到 `main` 會觸發 GitHub Actions，把 `site/` 發佈到 GitHub Pages。變更一律走分支與 Pull Request。

## 其他

- 根目錄的 `議事記錄_依科室分類.md` 是鄉民代表會議事記錄的整理筆記，不屬於預算資料庫。
- 授權：尚未指定。資料來源為屏東縣萬巒鄉公所公開之總預算書。

## 給開發者與 AI 助手

程式架構、資料流程、修正機制、已知限制與踩過的坑，請看 [`CLAUDE.md`](CLAUDE.md)。
