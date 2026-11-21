# 計畫：逐年趨勢與自選科目獨立比較

狀態：草案 v3（2026-11-21 併入第二輪審查意見：分支基底、S0 完成判定、停止條件／回復／預算、修正迴圈上限），待使用者核准後才實作。
分工：**程式實作 → agy**；**契約、資料檢核與 code review → Claude**。主 session 不採信 agy 自我報告，一律獨立重跑驗證。
執行環境：**使用者本機**（agy、herdr、browsermcp、114 PDF 都只在本機；雲端 session 無法執行本計畫的 agy 分工）。

## 1. 需求（來自使用者）

- R1 針對**某一個預算項目**，看它**逐年的增減**（金額、差額、增減率）。
- R2 可**指定其他科目**，與該項目做**獨立比較**（不限同層級、同類別，可跨歲入／歲出）。
- R3 計畫要能**平行處理**，讓 AI Coding Agent 能快速執行。
- R4 計畫要包含**資料驗證檢核**與 **code review**。
- R5 程式交給 agy，資料檢核與 code review 交給 Claude。

不在範圍：明細層級（`match_items.py`）跨年配對、參考表、備註表的改動、新增年度資料、`summary.csv` 的「上年度／前年度決算」欄延伸到 112–113 年（預算數與決算數混畫會誤導，列為下一版再議）、114 追加（減）預算書。

## 2. 現況摘要（探勘結論，已用 `site/data` 核對）

- `build.py::_collect_year_compare_items` 每年輸出歲入（款／項／子目／細目）、歲出（`plan:`、`object:`）項目。key 格式：`revenue:<code>`（款 `04`、項 `04-02`、子目／細目 11 碼）、`plan:<11碼>`、`object:<計畫碼>|<用途別碼>`。
- 目前只輸出相鄰年度對 `compare_<a>_<b>.json`（114→115、115→116），各約 230KB、約 420 個 key；沒有跨三年的時間序列。
- `_remap_compare_item_codes` + `data/crosswalk/codes.csv` 只處理單一年度對，且方向是**把新年度的碼換成舊年度的碼**（`scripts/build.py` 的 `_write_compare_files`：`to_code → from_code`）。`codes.csv` 目前只有一列：114 項 `04-03` ＝ 115 項 `04-02`（廢舊物資售價）。
- **陷阱**：114 本身另有項 `04-02`（財產售價，115、116 沒有）。若把 114 的 `04-03` 往新年度改成 `04-02`，會和 114 自己的 `04-02` 撞 key，`_remap_compare_item_codes` 會 `raise ValueError`。
- 跨年代碼大致穩定：只出現一年的計畫／細目都是真的新增或刪除（例如計畫 `37120010105` 選舉業務只有 115；`51120019101`、`59120019201` 有 114、116，115 沒有）；用途別有同名但掛在不同計畫的情形，不是漏登記的改碼。
- **中間年缺值的真實案例**：細目 `09120010101`（上級政府補助收入-一般性補助收入）114、116 有，115 沒有；計畫 `51120019101`、`59120019201` 同樣是 114／116 有、115 沒有。
- `search.json` 是逐筆陣列：`{id, year, kind, code, name, …}`，`kind` ∈ `revenue`（明細）｜`expenditure`（明細）｜`plan`｜`summary`；沒有 series key。
- 前端 `CompareView` 只能整層排名，沒有自選項目機制；`web/src/router.ts` 的 catch-all 正規式列舉了頁面名稱（加新頁要同步改）。

## 3. 設計

### 3.1 資料：`site/data/series.json`（新增，決定性輸出）

```jsonc
{
  "years": [114, 115, 116],
  "items": {
    "<canonical_key>": {
      "kind": "revenue|plan|object",
      "level": "款|項|子目|細目|工作計畫|用途別",
      "code": "<canonical 代碼>",
      "display_name": "最新有資料年度的名稱",
      "name":       {"114": "...", "116": "..."},        // 該年不存在則省略此年
      "amount_元":  {"114": 123, "115": null, "116": 456}, // 每個 years 都有鍵；不存在 = null，不是 0
      "page":       {"114": {"page": 1, "page_start": 1, "page_end": 2}},
      "parent_key": {"114": "<canonical>", "116": "<canonical>"},  // 逐年；最上層為 null
      "children":   {"114": ["<canonical>", "..."]},     // 逐年，canonical key，決定性排序
      "dept":       {"114": "..."},                       // 逐年（機關可能改組）
      "政事別":      {"114": "..."},                       // 只有 plan／object
      "unresolved": {"114": false},                       // 逐年
      "name_changed": false                               // 有資料的年度中名稱不只一種
    }
  },
  "aliases": {
    "114:revenue:04-03": "revenue:04-02",
    "114:revenue:04-02": "revenue:04-02@114"
  }
}
```

**canonical key 演算法**（取代 v1 的「直接用最新年度 key」）：

1. 對每個相鄰年度對 (Y, Y+1)，從 `codes.csv` 取 `from_year=Y, to_year=Y+1` 的列，定義單步映射 `f_Y(code)`：
   - `code` 是某列的 `from_code` → 回傳該列的 `to_code`；
   - 否則若 `code` 是某列的 `to_code`（Y+1 的這個代碼已被別的舊代碼「認領」）→ **斷鏈**；
   - 否則回傳 `code`（沿用同碼）。
2. 某年度 Y 的項目從 Y 開始依序套用 `f_Y, f_{Y+1}, …` 直到最新年度：
   - 全程沒斷鏈 → canonical key ＝ `<kind>:<最終代碼>`；
   - 在進入 Z 年時斷鏈 → canonical key ＝ `<kind>:<斷鏈前的代碼>@<Z-1>`（例：114 的財產售價 `revenue:04-02@114`）。
3. 不同年度但 canonical key 相同的項目合併成同一條序列；**同一年度有兩個項目得到同一個 canonical key → 直接報錯**，不靜默覆蓋。
4. `parent_key`、`children` 一律換成 canonical key。
5. `aliases` 記錄所有「原始 key ≠ canonical key」的 `"<年>:<原始key>"`；原始 key 等於 canonical key 的不列。**前端解析順序：先查 `aliases`，查不到才直接用原始 key**（因為像 `114:revenue:04-02` 這種，直接拿原始 key 會誤命中另一條序列）。
6. 只對 `kind=revenue` 套用 crosswalk。若 `codes.csv` 出現與某個計畫代碼相同的 `from_code`／`to_code`，build **直接報錯**並說明「plan 改碼需連帶改寫 object key，尚未實作」，不默默略過。
7. `codes.csv` 出現非相鄰年度的列（`to_year != from_year+1`）→ build 報錯。鏈式改碼（A→B 在 114→115、B→C 在 115→116）依上面的逐步規則自然處理，要有測試。

其他規則：

- **全部項目都輸出**（包含只出現一年的），因為 R2 可能選到任何項目。
- 缺年份一律 `null`；**不自動補 0**、不猜測對應（對不上就各自獨立成一筆，並列入檢核報告）。
- 差額、增減率、指數**不存入 JSON**，由前端計算（避免兩份真相）。
- 體積上限 **350KB**（預估 250–300KB），測試要 assert，驗收時回報實際大小。
- `index.json` 加 `series_years`（少於 2 年時不輸出 `series.json` 並清除殘留檔，比照 `_write_compare_files`）。

### 3.2 前端計算規則（`trendModel.ts`，純函式）

- **差額**（Y 對 Y-1）：兩年皆非 `null` 才計算，否則 `null`。注意：這與 `compare_*.json` 的 `diff_元`（缺值當 0）**刻意不同**，畫面與文件都要寫清楚。
- **增減率**：沿用 `_build_compare_json`：兩年皆為 0 → `0`；前一年為 `null` 或 0 → `null`；否則 `round(diff/prev*100, 2)`。缺值年**不跳過去比更早的年度**（116 對 115 為 `null` 時，不改拿 114 比）。
- **指數**：基準年 ＝ 序列中第一個「非 `null` 且非 0」的年度，基準年 ＝ 100；找不到基準年時整條為 `null`。基準年要顯示在圖表／表格上。
- **折線**：`null` 處斷開（ECharts `connectNulls: false`），不畫成 0。
- 只有 1 個年度有資料時，頁面顯示提示、不報錯。

### 3.3 前端頁面與入口

- 新頁 `#/<年>/趨勢?items=<key;key…>&mode=amount|yoy|index`
  - `<年>` 只決定導覽列的年度情境與圖表上高亮哪一年，不影響資料範圍（永遠是 `series.json` 的全部年度）。
  - `items` 第一個為主項目，其餘為比較對象，上限 **8 個**；非法參數（未知 key、重複、超過上限）要過濾並提示，不崩潰。URL 的 key 可以是 canonical key，也可以是 `<年>:<原始key>`（經 `aliases` 解析）。
  - `amount`：各年金額折線；`yoy`：逐年差額與增減率；`index`：以基準年為 100 的指數。
  - 圖表下方一律有數字表格（a11y），並可匯出（比照 `toCompareExportRows` 的風格）。
  - 頁面註明「各年皆為原編預算，不含追加（減）預算與決算」。
- `router.ts` 加路由、catch-all 正規式加 `趨勢`、導覽列加入口。`series.json` 載入失敗時導覽列隱藏入口或頁面顯示降級訊息。
- **「看趨勢」入口與 key 解析**（都要經 `aliases`）：

| 位置 | 顯示入口的節點 | 對應 key |
|---|---|---|
| 歲入 drill | 款、項、子目、細目 | `<年>:revenue:<code>` |
| 歲出 drill（政事別／機關別視角） | 工作計畫、計畫下的用途別 | `<年>:plan:<code>`、`<年>:object:<計畫>\|<用途別>` |
| 歲出 drill | 政事別、機關、用途別視角的跨計畫彙總節點 | **不顯示**（series 裡沒有這些項目） |
| 比較頁 | 每一列 | 比較頁的 key 是年度對**舊年度**的代碼：`<a>:<key>` |
| 搜尋 | `revenue` 明細 → 細目；`expenditure` 明細與 `plan` → 工作計畫；`summary` 只限款／項：`search.json` 的 summary 沒有 `source_table` 欄位，判斷方式為 `text.split(' ')[0] == '歲入來源別預算總表'`（注意不是「歲入來源別預算**比較**總表」）且 `code` 非空 | 同上 |
| 搜尋 | 其他 `summary` 表 | 不顯示 |

### 3.4 層級範圍

首版包含：歲入款／項／子目／細目、歲出工作計畫、計畫下用途別。
**首版不含（使用者 2026-11-21 確認，見 §8）**：政事別合計、機關合計、跨計畫用途別合計（例如全鄉「人事費」）、歲入／歲出總計。

### 3.5 不改的東西

`raw/**`、`data/*.csv`、`corrections.csv`、`codes.csv`、既有 `compare_*.json` 與其他 JSON 的格式、既有頁面行為（只新增「看趨勢」連結）。

## 4. 工作拆解與平行化

```
Step 0  契約 S0（Claude）→ 使用者核准
   ├── Lane A 後端：series.json + 測試          [agy #1]  ┐
   ├── Lane B 前端：資料層 → 頁面 → 入口         [agy #2]  ├ 平行，只透過 S0 契約與 fixture 溝通
   └── Lane C 獨立檢核：check_series.py          [agy #3]  ┘
Step 1  整合到 feat/series → Gate：Claude 跑 D1–D9 + code review → 退回修正 → 再驗
Step 2  端到端驗收（瀏覽器）→ 使用者確認 → commit／PR（使用者自行合併）
```

v1 的 5 條線（A1/A2/B1/B2/B3）縮成 2 條 agy 線：整個功能只有 3 個年度、約 420 個 key，拆太細的協調與合併成本高於省下的時間；B2／B3 也一定會同時改 `router.ts` 與各頁而衝突。

| ID | 工作 | 執行者 | 依賴 | 產出 |
|---|---|---|---|---|
| S0 | 見下方「S0 契約」 | Claude | 使用者核准本計畫 | 契約檔（commit 在 `feat/series`） |
| A | `build.py`：`_build_series_json`、`_write_series_file`、`index.json.series_years`；`tests/test_series.py`：schema、缺年為 null、改碼與擠掉案例、同年撞 key 報錯、plan 代碼列報錯、非相鄰年度列報錯、鏈式改碼、決定性（跑兩次相同）、體積 < 350KB | agy #1 | S0 | 後端改動＋測試 |
| B | ① `types.ts`（`SeriesData`、`index.series_years`）、`source.ts` 的 `series()`（失敗回 `null`）、`web/src/views/trend/trendModel.ts`＋`web/tests/trendModel.test.ts`（用 S0 fixture 與期望值）；② `TrendView.vue`、`ItemPicker.vue`、`TrendChart.vue`、趨勢表、匯出、路由與導覽；③ 各頁「看趨勢」入口（§3.3 表格） | agy #2 | S0 | 前端改動＋測試 |
| C | `scripts/check_series.py`（見 §5），**不 import `build.py` 的 series 邏輯**；輸出 `reports/check_series.md`；**不得讀 Lane A 的 worktree（`../wb-series-a`）或 `feat/series-a` 分支** | agy #3（Claude Sonnet） | S0 | 檢核腳本＋報告 |
| R1 | Code review：Lane A | Claude | A | 審查意見 |
| R2 | Code review：Lane B | Claude | B | 審查意見 |
| R3 | Code review：Lane C（含確認沒有 import `build.py` 的 series 邏輯） | Claude | C | 審查意見 |
| V1 | 整合驗證與端到端檢查 | Claude | 全部 | 驗證報告 |

### S0 契約

- **產出（路徑固定）**
  - `docs/series-contract.md`：§3.1 schema 定稿、canonical 演算法、§3.2 計算規則、前端 `SeriesData` TypeScript 型別草稿（Lane B 照抄進 `web/src/data/types.ts`，S0 不碰 `web/**`），以及「必備案例 → fixture key」對照表。
  - `tests/fixtures/series_sample.json`：符合 §3.1 schema 的 3 年 fixture（`years`、`items`、`aliases`）。
  - `tests/fixtures/series_expected.json`：每個 fixture 項目逐年的差額／增減率／指數期望值。由 Claude 依 §3.2 **手算**（不從任何實作產生）。
  - `tests/test_series_fixture.py`：只用標準函式庫，檢查 fixture 本身（不測實作）。
- **必備案例**：114 `04-03`→`04-02` 改碼；被擠掉的 `revenue:04-02@114`（含 `aliases` 兩列）；中間年缺值（`09120010101`）；只出現一年；改名（`name_changed=true`）；0 值（含前一年為 0、兩年皆 0）；負增減；鏈式改碼（合成案例，用不存在的代碼，標明為合成）；指數基準年不是第一年（第一年為 `null` 或 0）。
- **完成判定**（全部成立才算完成）：
  1. `python3 -m unittest tests.test_series_fixture` 通過，至少檢查：兩檔都是合法 JSON；每個項目都有 §3.1 的必填欄位，且 `amount_元` 的年度鍵和 `years` 相同；`aliases` 的值都存在於 `items`；`parent_key`／`children` 逐年互相一致；上列每個必備案例在 `series-contract.md` 對照表中都有一個 fixture key 存在；`series_expected.json` 的 key 集合等於 `series_sample.json` 的 `items`。
  2. 契約文件裡的 TS 型別能描述 fixture：Claude 在 `web/` 外的 scratchpad 用 `npx tsc --noEmit` 對「型別＋`import` fixture」做型別檢查並通過（不改 `web/**`）。
  3. 使用者看過契約文件與 fixture 並明確同意。
- **回復**：S0 只是 `feat/series` 上的一個本機 commit（未 push），`git reset --hard <base>` 或刪除 `feat/series`（刪除前需使用者同意）即可回到計畫狀態。
- **預算**：Claude 自己做，預計 1 個工作段；fixture 不超過約 15 個項目。
- **停止條件**：必備案例中任何一個無法用 §3.1 的規則表達（表示 schema 有洞）→ 停下修計畫並重新給使用者核准；使用者對契約有異議 → 停下修改，不派工。

**分支與基底**（所有 lane 都從含契約的 commit 出發）：

1. 使用者核准後：`git switch -c feat/series docs/plan-series`（基底含本計畫）。
2. Claude 在 `feat/series` 完成 S0 → 經使用者同意後 commit（記為 `S0_COMMIT`）。驗證：`git ls-tree -r --name-only S0_COMMIT tests/fixtures/` 要列出兩個 fixture 檔。
3. 從 `S0_COMMIT` 開 agy 的 worktree：`git worktree add ../wb-series-a -b feat/series-a feat/series`、`git worktree add ../wb-series-b -b feat/series-b feat/series`、`git worktree add ../wb-series-c -b feat/series-c feat/series`。
4. Lane C 由 agy #3（模型 Claude Sonnet，2026-11-21 使用者指定）在 `../wb-series-c` 做；為了保持檢核獨立，agy #3 不得讀 Lane A 的 worktree 或分支，只能依契約、CSV 與既有 `site/data` 寫腳本。Claude 審查後 commit 到 `feat/series-c`，與 A、B 一起合併進 `feat/series`。
5. A、B、C 完成並通過 R1／R2／R3 後，`git merge --no-ff feat/series-a`、`feat/series-b`、`feat/series-c` 進 `feat/series`，再跑 Gate。
6. 最後的 PR 是 `feat/series` → `main`，內含本計畫、契約、A、B、C 的全部 commit。
7. **commit 權限**：CLAUDE.md 規定 commit 前要列檔案清單與訊息並等使用者確認。核准本計畫時，使用者可以另外授權「`feat/series*` 本機分支的 commit 不必逐次確認（不含 push／PR）」；沒有授權就每次都問。agy 在自己的 worktree **不 commit**，由 Claude 審查 diff 後依上述規則 commit。

**檔案擁有權**（避免衝突；超出自己範圍的檔案一律不碰，需要時回報主 session）：

| Lane | 可以改的檔案 |
|---|---|
| S0（Claude） | `docs/series-contract.md`、`tests/fixtures/series_sample.json`、`tests/fixtures/series_expected.json`、`tests/test_series_fixture.py`、本計畫 |
| A（agy #1） | `scripts/build.py`、`tests/test_series.py`、`site/data/series.json`、`site/data/index.json`（由 build 產生） |
| B（agy #2） | `web/**`（含 `router.ts`、導覽、各 view 的入口連結） |
| C（agy #3） | `scripts/check_series.py`、`reports/check_series.md` |

平行規則：

- 每條 agy 線用獨立 worktree，基底一律是 `S0_COMMIT`（見上方「分支與基底」），不是 `main`；不在同一個 checkout 切換；合併後 `git worktree remove`。
- A 與 B 只透過 S0 契約溝通；B 用 fixture，不等 A 完成。
- A、B 完成後合併到整合分支 `feat/series`，再跑全部檢核；不直接推 `main`。
- agy 在 herdr 的**可見 pane** 開啟；選模型前先讀畫面確認游標位置。

## 5. 資料驗證與檢核（Claude 負責）

`scripts/check_series.py` 直接從 **CSV** 重算，與 `series.json` 逐項比對，不採用 `build.py` 的中間結果或 `site/data/<年>.json`。

| # | 檢核 | 失敗處理 |
|---|---|---|
| D1 | 每個 `items[k].amount_元[年]` 等於從 CSV 重算的值：款／項 ＝ `summary.csv` 中 `source_table=歲入來源別預算總表` 的本年度（與 `validate.py` 同一張表）；子目 ＝ 其下細目加總；細目 ＝ `revenue_items.csv` 明細加總 − `_known_diff`；plan ＝ `plans.csv` 總額；object ＝ `expenditure_items.csv` 依計畫＋用途別加總 | 退出碼 1，列出 key／年度／兩邊數值 |
| D2 | 與 `compare_<a>_<b>.json` 交叉比對：compare 的 key `k` 對應 series 的 `aliases.get("<a>:"+k, k)`；兩年皆有值者金額必須相同；series 自行計算的差額要等於 compare 的 `diff_元`（只比兩年皆有值者） | 同上 |
| D3 | 沒有憑空補 0：缺年份必為 `null`；有無資料與 compare 檔的 `status`（`both`／`only_<年>`）一致 | 同上 |
| D4 | crosswalk：只有 `codes.csv` 登記的年度對被改碼；115→116 不受 114 規則影響；被擠掉的項目（`@<年>` 後綴）正確；同年無兩項併入同一 canonical key；鏈式與非相鄰年度列的行為符合 §3.1 | 同上 |
| D5 | 階層一致（**逐年**）：每年的 `parent_key[年]`／`children[年]` 都存在於 items 且該年有值；該年子項加總 ＝ 父項（既有已知差額要列出，不隱藏） | 同上 |
| D6 | 決定性：連跑 `build.py` 兩次，`site/data/` 無差異 | 同上 |
| D7 | 抽樣人工核對：**固定 seed**，每年抽 ≥10 項，對照 `raw/` 或 PDF（114 PDF 只在本機），抽樣清單與結果寫入報告 | 寫入報告 |
| D8 | 既有基準不退步：`validate.py 114 --partial`／`115`／`116` 的數字與 CLAUDE.md 基準相同；`unittest discover` 後 `git status --short` 無意外變動 | 退出碼 1 |
| D9 | 可解析性：每個 `<年>.json` 歲入／歲出 drill 中應有入口的節點、每筆 `compare_*.json` 的 key、`search.json` 中應有入口的筆，都能經 `aliases` 解析到**恰好一個**存在的 canonical key | 退出碼 1 |

不一致處**不自動修正**，列入報告交使用者。

## 6. Code Review 清單（Claude 負責）

- 正確性：缺值／零值／負值增減率；前一年為 0；`null` 不被當 0 畫在圖上；指數基準年的選擇；差額與 compare `diff_元` 的語意差異有寫清楚。
- canonical：先查 `aliases` 再用原始 key 的順序在前端所有入口都一致；`@<年>` 後綴的項目能被正確選取與顯示。
- 契約：前後端型別與 schema 一致；不新增 `site/data` 以外的輸出、不改既有 JSON 格式。
- 範圍：沒有動 `raw/`、`data/` CSV、既有頁面行為；沒有引入新 Python 套件（只用標準函式庫）或不必要的前端相依；各 lane 沒有改到擁有權以外的檔案。
- 決定性與清除殘留檔邏輯；錯誤降級（`series.json` 缺失頁面不崩潰）。
- 前端：URL 參數非法的處理；a11y（圖表有表格對照）；8 個項目時的效能與圖例可讀性。
- 測試：新測試在沒有實作時會失敗；沒有只複述實作的測試。
- 審查結果分級（阻擋／建議），阻擋項退回 agy 修正後由 Claude **重跑 D1–D9** 再放行。
- **修正迴圈上限**：每條 lane 的「退回 agy 修正 → 重跑 D1–D9＋review」最多 **2 輪**。第 2 輪後仍有阻擋項 → 該 lane 標為暫停，不再派 agy，向使用者報告阻擋項、證據與選項（Claude 接手修正／縮小範圍／放棄該 lane），等使用者決定。每一輪都必須有實質改動；同樣的程式碼不重驗。建議項不觸發新一輪，列入報告。
- **獨立驗證**：Gate 通過後，再由一個全新的 `verifier` 依 §7 驗收標準獨立驗證一次（本功能涉及序列化輸出，屬必要步驟）。驗證後若有必要的修改，重跑 §7 主要驗收並再做一次全新驗證。

## 7. 驗收標準

1. `python3 scripts/build.py` 兩次無差異；`python3 scripts/check_series.py` 全數通過；`series.json` < 350KB（回報實際大小）。
2. `python3 -m unittest discover -s tests` 通過，且 `git status --short` 只剩本功能的預期變更。
3. `cd web && npm ci && npm test && npm run build` 通過。
4. 瀏覽器實測：選一個歲入款＋一個歲出計畫＋一個細目，三種模式（金額／逐年增減／指數）的數字與表格一致；另測 `revenue:04-02`（廢舊物資售價，114 值來自 114 的 04-03）、`revenue:04-02@114`（財產售價）、`09120010101`（115 斷線）；重新整理後 URL 還原同一畫面；從四種入口各點一次「看趨勢」都能帶入正確項目。
5. Claude 的驗證報告與 code review 沒有未解決的阻擋項。

## 8. 風險與待決定

- 項目跨年改碼或改名但 crosswalk 沒登記時，會被當成不同項目；做法是列清單給使用者決定，不自動猜。
- 只有 3 個年度，趨勢圖只有 3 個點；功能設計成年度增加時自動延伸。
- 已決定（使用者，2026-11-21）：(a) 首版**包含**歲出「用途別」層級；(b) 「看趨勢」入口放在**比較頁、歲出／歲入 drill 節點、搜尋結果**；(c) 比較對象上限 **8 個**；(d) 審查意見全部採納（v2）。
- 已決定（使用者，2026-11-21）：(e) 政事別合計、機關合計、跨計畫用途別合計、歲入／歲出總計**首版不含**。

## 8.1 停止條件、回復與預算

**停止條件**（發生時暫停受影響的 lane，向使用者報告並等決定；不自行繞過）：

| # | 情況 | 處理 |
|---|---|---|
| X1 | 真實資料跑 canonical 演算法時同年撞 key，或出現 §3.1 第 6／7 條的報錯 | 停 Lane A；列出撞號項目，交使用者決定（例如補 `codes.csv`，屬資料變更需另行核准） |
| X2 | `series.json` ≥ 350KB | 停；回報大小與組成，請使用者決定放寬上限或瘦身方式 |
| X3 | D8 既有基準退步，或 `unittest` 後出現非預期的檔案變動 | 停全部 lane；先查原因，不合併 |
| X4 | 任何 lane 需要改 `raw/**`、`data/*.csv`、`corrections.csv`、`codes.csv`，或改到擁有權以外的檔案 | 停該 lane；回報需求，請使用者決定 |
| X5 | agy 同一 lane 連續 2 次無法完成或產出不可用 | 不第 3 次重派；請使用者決定由 Claude 接手或縮小範圍 |
| X6 | §6 修正迴圈達 2 輪上限 | 見 §6 |
| X7 | D1–D9 發現資料本身對不上（不是程式錯誤） | 不自動修正；列入 `reports/check_series.md` 交使用者 |

**回復**（全部在本機分支，尚未 push 前都可完全撤回）：

- S0：見「S0 契約」。
- Lane A／B／C：`git worktree remove ../wb-series-<a|b|c>`，不合併該分支（刪除分支需使用者同意）。
- 整個功能：不開 PR 或關閉 PR；`main` 不受影響。若已合併到 `main`，由使用者在 GitHub revert 該 PR（會觸發重新部署）。

**預算**：

- agy：3 個 lane，每個最多 1 次初次派工＋§6 的 2 輪修正（另受 X5 限制）。
- 獨立審查：計畫結案審查 1 次；Gate 後全新 `verifier` 1 次（驗證後有必要修改時最多再 1 次）。
- 不新增 npm／Python 相依；不使用雲端付費服務。

## 9. 流程（遵守 CLAUDE.md）

唯讀探勘（已完成）→ 本計畫 v1 → 獨立審查（已完成，併入 v2）→ 第二輪審查（已完成，併入 v3）→ 結案審查 → **使用者核准 v3** → S0 → 實作（agy）＋檢核腳本（Claude）平行 → 獨立驗證與 review（Claude）→ 使用者確認 → Conventional Commits（繁中）、新分支、`gh pr create`，**由使用者自行在 GitHub 合併**。commit 前先列出檔案清單與完整訊息。
