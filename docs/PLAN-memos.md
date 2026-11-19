# 計畫：資料備註表（memos）— 如實記錄 PDF 的錯字、語意問題與頁碼，同時保持數字與查詢語意正確

Repo：/Users/wadelin/Github/WanluanBudget（main = b6f7ec0 起，另有未合併 PR #11）。語言：繁體中文。

## 1. 為什麼做（目標）
使用者查資料時會被原書本身的問題誤導：
- 原書印刷錯字（例：114 與 116 的 p59「自治**修**例」，法規名稱應為「條例」）：用正確詞搜尋會查無資料；若偷偷改字，資料又與原書對不上。
- 原書前後不一致（例：114 稅課收入前年度決算 p1 為 219,572、p6 為 219,573；p5 與 p6 的雜項收入項碼不同；116 的 T4）。
- 原書版面造成的資料限制（例：「資本移轉」被頁面切開、p159 的「備註」欄沒有資料所以不列出）。
目前這些資訊只散在 `corrections.csv` 的 reason、`docs/TODO.md`、`CLAUDE.md`，網站使用者看不到。

三項原則（使用者指定）：
- P-A **數字正確**：備註絕不改動任何數字欄位；既有 CSV 的金額、數量、單價完全不變。
- P-B **查詢語意正確**：資料文字保持「原書怎麼印就怎麼存」；用「別名」讓正確寫法也搜得到；網站在該列顯示備註說明。
- P-C **如實保存**：每筆備註都要同時記錄 (1) 原書印刷的原文、(2) OCR／資料目前存的文字、(3) 正確／通順的寫法、(4) 書面頁碼與 PDF 檔案頁序、(5) 如何核對的（方法、日期）、(6) 證據截圖（可選）。

## 2. 非目標
不自動偵測錯字；不改任何數字；不改跨年度比較邏輯；不動 `raw/`；不引入後端或新的前端依賴；不處理 `ocr_corrected` 自動檢視（列為選配切片 S3，需使用者另外決定）。

## 3. 資料模型
### `data/memos.csv`（人工維護、進版控；UTF-8）
欄位：`memo_id,year,scope,page,locator,field,type,printed_text,data_text,suggested_text,note,pdf_file,pdf_page,verified_method,verified_on,evidence,status`
- `memo_id`：穩定 ID，例 `M114-0001`，全表唯一。
- `scope` ∈ `revenue_item`｜`expenditure_item`｜`plan`｜`summary`｜`reference_cell`｜`page`。
- `locator`（與資料列一一對應）：revenue_item=`<細目編號>:<item_seq>`；expenditure_item=`<計畫編號>:<用途別代碼>:<item_seq>`（item_seq 為 CSV 內該用途別的序號）；plan=`<計畫編號>`；summary=`<source_table>:<科目名稱>`；reference_cell=`r<列>c<欄>`（使用修正後的最終 row_idx／col_idx，`page` 欄為頁碼）；page=空字串（整頁層級，例如缺欄）。
- `field`：備註所針對的欄位（例：`note`、`說明`、`科目名稱`、`本年度`、`text`；page 層級可空）。
- `type` ∈ `print_typo`（原書印刷錯字）｜`print_inconsistent`（原書前後不一致）｜`print_layout`（原書版面造成的資料限制）｜`data_gap`（OCR 或資料缺漏／限制）。
- `printed_text`：原書印刷原文（逐字）。數字型不一致可寫成 `p1:219,572｜p6:219,573`。
- `data_text`：目前 CSV 該欄位的實際值（逐字）。**是檢查資料是否被改動的 guard**。
- `suggested_text`：正確／通順的寫法（`print_typo` 必填；其他類型可空）。
- `note`：繁體中文說明，描述原書狀況與使用者應注意之處。
- `pdf_file`、`pdf_page`：來源 PDF 檔名與 PDF 檔內頁序（掃描檔，無文字層）；`page` 為書面頁碼。
- `verified_method`：例 `人工對照原圖`、`獨立轉錄比對（agy）＋原圖裁決`；`verified_on`：`YYYY-MM-DD`。
- `evidence`：選填，repo 內相對路徑，指向小尺寸裁切圖（`docs/evidence/<年>/<memo_id>.png`，單張建議 < 80 KB）。
- `status` ∈ `confirmed`（已對照原圖）｜`pending_publisher`（待公所確認，例如 T4）。

### `data/pdf_sources.csv`（PDF 頁序與書面頁碼的對照，如實保存）
欄位：`year,pdf_file,book_page_from,book_page_to,pdf_page_offset,note`；PDF 頁序 = 書面頁碼 + offset。**區段與偏移（均已用原圖印出的頁碼確認過，S0 須重新抽驗）**：
- 114 `114年度萬巒鄉總預算Part1.pdf`（96 頁，掃描）：p1–p90 偏移 +6（PDF 第 7 頁 = p1；p87 → 第 93 頁；p59 → 第 65 頁）。
- 114 `114年度萬巒鄉總預算Part2.pdf`（88 頁，掃描）：p89–p164 偏移 −88（PDF 第 1 頁 = p89；p154 → 第 66 頁；p164 → 第 76 頁）；第 77 頁為只印標題的扉頁（無書面頁碼，須在 note 註明）；p165–p169 偏移 −87（p165 → 第 78 頁；p169 → 第 82 頁）；第 83 頁為扉頁；p170–p173 偏移 −86（p170 → 第 84 頁；p173 → 第 87 頁）；第 88 頁空白。
- 115 `115年度總萬巒鄉總預算案.pdf`（180 頁，掃描）：p1–p10 偏移 +6（p1 → 第 7 頁，p10 → 第 16 頁）；p37–p146 偏移 +10（p60 → 第 70 頁；p146 → 第 156 頁）；其餘頁碼尚未核對，**不收錄**（不得推測）。
- 116 `116年度總萬巒鄉總預算案(P1-10).pdf`（16 頁）：p1–p10 偏移 +6（p10 → 第 16 頁）；`…(P37-175).pdf`（144 頁）：p37–p175 偏移 −34（PDF 第 1–2 頁為封面，p37 → 第 3 頁；p125 → 第 91 頁；p156 → 第 122 頁）；`…(P11-36).pdf` 尚未核對，不收錄。
這是為了讓日後任何人都能由備註的書面頁碼找到 PDF 頁。表內只收「已核對」的區段。

## 4. 不變量（每個切片都要遵守）
- I1：既有 `site/data/*.json`（`114.json`、`115.json`、`116.json`、`compare*.json`、`search.json`、`reference_114.json`）與 `data/*/*.csv` **位元組不變**，除非該切片明列要改。`index.json` 只允許新增 `memo_years` 鍵。
- I2：`validate.py 114 --partial`、`115`、`116` 的既有結果與報告段落不變（只允許新增備註段落）。
- I3：備註資料只做「註記」，不得回寫到任何數字欄位或影響彙總、比較、搜尋以外的計算。
- I4：既有 74 個測試全過。

## 5. 切片

### S0 資料模型、種子資料與驗證（不動網站）
範圍：新增 `data/memos.csv`、`data/pdf_sources.csv`、`docs/MEMOS.md`（欄位定義、類型定義、新增方式）、`scripts/memos.py`（載入與定位資料列的共用模組）、`scripts/validate.py` 新增「備註檢查」段落（報告新增一節，並計入退出碼）、`tests/test_memos.py`。證據截圖（若使用者同意）放 `docs/evidence/`。
驗證規則（任一失敗 → validate 退出碼 1）：V1 欄位與列舉值合法、`memo_id` 唯一；V2 `locator`（依 scope）能在對應年度資料中**恰好定位到一列**，且 `page` 與該列頁碼一致；V3 若 `data_text` 非空，必須與該列欄位目前的值逐字相等（資料日後被改動時備註會被標示過期）；V4 `print_typo` 必須有 `printed_text`、`suggested_text` 且兩者不同；V5 `pdf_file` 必須在 `pdf_sources.csv` 內，且 `pdf_page` 與 `page` 依對照表一致；V6 `evidence` 若有值，檔案必須存在；V7 `verified_on` 為合法日期。
種子資料（只收**已有原圖或使用者確認依據**者；沒有依據的不得杜撰，列在報告的「待補」）：114 p59、115 p58、116 p59 的「自治修例」（print_typo；114、116 已有原圖截圖，115 須由執行者先用原圖確認後才收）；114 p5／p6 雜項收入項碼 01／02（print_inconsistent）；114 稅課收入前年度決算 p1 219,572／p6 219,573、其他收入 p1 7,322／p6 7,321（print_inconsistent）；116 T4-a、T4-b（print_inconsistent，`pending_publisher`）；114 參考表 p170／p172「資」與 p171／p173「本移轉」被頁面切開、「商品及勞務購買支出」由兩直行組合（print_layout）；114 p160／p161「員」「工」分組標題（print_layout）；114 參考表 p165／p167 表頭「燃料使用費(全年))」兩個右括號（print_typo）；114 參考表 p159 缺「備註」欄（data_gap）；其餘使用者先前確認為原書印刷者（p97 役政說明、p55 第 10／17 筆、p44／p53 括號）由執行者自 `docs/TODO.md`、`CLAUDE.md`、`data/corrections.csv` reason 蒐集；查不到逐字依據的先不收並列入「待補」。
另含**選配決定 S0-D**：114 `data/corrections.csv` 中鍵為 `(114, 59, 12120010204:2, note)` 的那一筆（目前約在第 217 行，**以鍵定位，不以行號**）同時做了兩件事：把「修」改成「條」，並把半形「,」改成全形「，」。原圖（`114年度萬巒鄉總預算Part1.pdf` 第 65 頁）印的是「…徵收自治修例，辦理…」，所以「修例」與全形逗號都是原書原文。若使用者同意，S0-D **原地修改該筆**（不得刪除，否則會退回 OCR 的半形逗號）：把 `new` 改為逐字的原書印刷 `依據屏東縣萬巒鄉一般廢棄物暨無害事業廢棄物代清除處理費徵收自治修例，辦理廢棄物清潔規費徵收、資源回收物品出售收入。`，並改寫 `reason`（說明：原書自身印「修例」，保留印刷原文，不再校正為「條例」；全形逗號為原書所印），再依序執行 `python3 scripts/parse_book.py 114 --partial --reference-tables`、`python3 scripts/validate.py 114 --partial`、`python3 scripts/build.py` 重新產生 `data/114/revenue_items.csv`、`reports/validate_114.md`、`site/data/114.json`、`search.json`。這是本計畫唯一允許改動資料的地方。
驗收：(a) `validate.py` 114／115／116 退出碼 0，備註段落列出每筆結果；(b) 負向測試：把某筆 `data_text` 改錯一字 → validate 退出碼 1；把 `locator` 改成不存在 → 退出碼 1；(c) `pdf_sources.csv` 的**每一個區段**至少抽驗 1 頁，用該 PDF 頁的原圖讀出「印出的書面頁碼」來獨立確認（不得只靠表本身）：114 Part1 p87→第 93 頁；114 Part2 p100→第 12 頁、p160→第 72 頁、p165→第 78 頁、p172→第 86 頁；115 p5→第 11 頁、p60→第 70 頁；116 P1-10 p10→第 16 頁、P37-175 p125→第 91 頁。結果（含印出的頁碼）寫入 S0 PR 說明；主 session 與 verifier 會重新渲染這些頁獨立確認；(d) I1–I4；(e) 若同意 S0-D：`data/114/revenue_items.csv` 中細目 12120010204 的第 1 筆 `note` 逐字等於上述原書印刷字串（含全形「，」、不含半形「,」）；`parse_book.py 114` 顯示套用 N／未套用 0／未登記異常 0；114 其餘 CSV 與基準位元組相同；該筆備註（M114 p59）的 `data_text` 與此字串逐字相符（V3 通過）。
回復：revert PR。

### S1 建置輸出（不動前端）
範圍：`scripts/build.py` 讀 `data/memos.csv`，輸出 `site/data/memos.json`（依年度分組；每筆含解析後的目標鍵：歲入／歲出為搜尋索引 `id`，例 `114-revenue-12120010204-2`、`114-expenditure-<計畫>-<用途別>-<序>`；其他 scope 帶頁碼與定位字串）、SQLite 新增 `memos` 表、`site/data/index.json` 新增 `memo_years`。輸出需決定性（重跑位元組相同）。
驗收：I1（除 `index.json` 的新鍵外其餘 JSON 與 HEAD 位元組相同；以 sha 比對）；`memos.json` 的每筆都解析到唯一目標；SQLite 可用 `select * from memos where year=114 and type='print_typo'` 查詢；`tests/test_build.py` 新增測試；`validate`／測試全過。
回復：revert PR。

### S2 網站呈現與搜尋別名
範圍：`site/app.js`、`site/style.css`、`site/index.html`（導覽新增「資料備註」）。(1) 歲出／歲入明細列、計畫與細目階層、總表列、參考表儲存格，若有備註則顯示「ⓘ」標記，點開顯示：原書印刷、資料目前存的文字、建議寫法、頁碼與 PDF 頁序、核對方式與日期、證據圖（若有）、狀態；(2) 新頁面 `#/<年>/備註`：列出該年度全部備註，可依類型與頁碼篩選，每筆連結回對應頁面；(3) 搜尋：載入 `memos.json` 後，把 `suggested_text` 併入對應文件的「別名」搜尋欄位，使搜「自治條例」也找得到印成「修例」的項目，結果旁顯示「ⓘ」；(4) 沒有備註的列、沒有 `memos.json` 的年度，畫面與目前完全相同。
驗收：`tests/test_frontend.py`（Node vm，harness 內 `MiniSearch` 目前為 null、不載入 CDN 函式庫，因此**不在 vm 內跑真實搜尋**）採以下可測方式：把「把 `suggested_text` 依搜尋文件 `id` 併入 `alias` 欄位」寫成 `app.js` 內的**純函式**（例如 `mergeMemoAliases(docs, memos)`），並在 harness 提供**記錄用的 MiniSearch stub**（記錄建構時的 `fields` 與 `addAll` 收到的文件）；新增案例涵蓋：備註標記出現／不出現、備註頁渲染與篩選、`fields` 包含 `"alias"`（移除就會失敗）、文件 `116-revenue-12120010204-1` 的 `alias` 含「自治條例」（沒有就失敗）、`memos.json` 載入失敗時不影響既有頁面。**真實搜尋命中**由瀏覽器驗證：在 116 搜尋「自治條例」與「自治修例」皆回傳 `116-revenue-12120010204-1`（114 僅在 S0-D 完成後才以 `114-revenue-12120010204-1` 驗證）；另驗證 p59 列的 ⓘ、備註頁、手機寬度；`site/data` 其餘檔案位元組不變（I1）。注意此驗收依賴 116 的 20 處修正 PR 已合併（使 p59 三列的說明各自獨立）。
回復：revert PR。

### S3（選配，需使用者另外決定）`ocr_corrected` 檢視
把 `corrections.csv` 的修正紀錄（OCR 原文、修正後、依據、頁碼）唯讀地呈現在備註頁的另一個分頁，不新增人工維護資料。因筆數多（114 約 180、116 約 200），UI 需分頁／篩選；本計畫不含實作。

## 6. 執行者與流程
- 規劃與整合：主 session。實作：agy（Gemini 4 Hydrogen），每個切片一份固定規格任務檔；主 session 在乾淨 worktree 上**獨立重跑**所有驗收，再叫全新的獨立 `verifier`；使用者以 PR 合併（合併會觸發 Pages 部署，不自動合併）。
- **前置條件（S0 開始前）**：目前有未合併的資料 PR，都會改到 `data/corrections.csv`、`reports/validate_*.md`、`site/data`：PR #11（分支 `fix/116-text-fixes`，檔案：`.gitignore`、`data/corrections.csv`、`data/116/expenditure_items.csv`、`reports/validate_116.md`、`site/data/116.json`、`site/data/search.json`）、疊在其上、尚未開 PR 的 116 的 20 處修正（分支 `fix/116-text-fixes-2`，檔案：`data/corrections.csv`、`data/116/expenditure_items.csv`、`data/116/revenue_items.csv`、`reports/validate_116.md`、`site/data/116.json`、`search.json`），以及 115 完整比對之後可能產生的 115 修正 PR。**S0 必須在這些資料 PR 都已合併後（或使用者明確決定順序後）才開始**，並在開始時記錄當時的 `origin/main` SHA 作為 I1／I2 的**固定基準**；S0 分支由該 SHA 建立；每個後續切片也以其開始時的 `origin/main` SHA 為基準。
- 切片相依：S0 → S1 → S2，逐片 PR；每片合併後才開下一片，避免 `corrections.csv`、`validate_*.md`、`site/data` 衝突。
- 停止條件：V2／V3 在種子資料上失敗；既有 JSON 位元組變動；使用者對「證據截圖是否進版控」「S0-D 是否還原」「是否做 S3」尚未決定時，相關部分不動。

## 7. 使用者已決定（2026-11-19）
1. 證據截圖**進版控**（`docs/evidence/<年>/<memo_id>.png`）。
2. **採用 S0-D**：114 p59 保留該筆修正但內容改為原書逐字印刷（「修例」＋全形「，」），並以備註說明。
3. **S3 不納入**。
4. 執行者：agy，coding model 為 **Gemini 4 Hydrogen**；每個切片一份任務檔、一個 PR，由使用者合併。
5. 所有資料 PR 合併後才開始 S0（見第 6 節前置條件）。

## 7b.（原待決事項，已於上方決定）
1. 證據截圖是否進版控：建議**要**（`docs/evidence/`，僅裁切該行、300 dpi 灰階 PNG，單張 < 80 KB，預估 < 1 MB）。原因：PDF 不在 git 內，截圖是「原書真的這樣印」唯一能被日後驗證的證據。
2. S0-D：114 p59 是否還原為原書印刷的「修例」（建議還原，並以備註說明）。
3. S3 是否納入。
