# 計畫：逐年趨勢與自選科目獨立比較

狀態：草案，待使用者核准後才實作。
分工：**程式實作 → agy**；**資料檢核與 code review → Claude**。主 session 不採信 agy 自我報告，一律獨立重跑驗證。

## 1. 需求（來自使用者）

- R1 針對**某一個預算項目**，看它**逐年的增減**（金額、差額、增減率）。
- R2 可**指定其他科目**，與該項目做**獨立比較**（不限同層級、同類別，可跨歲入／歲出）。
- R3 計畫要能**平行處理**，讓 AI Coding Agent 能快速執行。
- R4 計畫要包含**資料驗證檢核**與 **code review**。
- R5 程式交給 agy，資料檢核與 code review 交給 Claude。

不在範圍：明細層級（`match_items.py`）跨年配對、參考表、備註表的改動、新增年度資料。

## 2. 現況摘要（探勘結論）

- `build.py::_collect_year_compare_items` 每年輸出歲入（款／項／子目／細目）、歲出（`plan:`、`object:`）項目，key 穩定。
- 目前只輸出相鄰年度對 `compare_<a>_<b>.json`（114→115、115→116），沒有跨三年的時間序列。
- `_remap_compare_item_codes` + `data/crosswalk/codes.csv` 只處理單一年度對的代碼改編。
- 前端 `CompareView` 範圍只能整層排名（plan／object／revenue_kuan／revenue_xiang），沒有自選項目機制。
- `search.json` 已有各年各項目（id、year、kind、code、name、amount_元），可作選取器的資料源之一。

## 3. 設計

### 3.1 資料：`site/data/series.json`（新增，決定性輸出）

```
{
  "years": [114, 115, 116],
  "items": {
    "<canonical_key>": {
      "kind": "revenue|plan|object", "level": "款|項|子目|細目|計畫|用途別",
      "code": "...", "display_name": "最新年度名稱",
      "name": {"114": "...", "115": "...", "116": "..."},   // 該年不存在則省略
      "amount_元": {"114": 123, "115": null, "116": 456},     // 不存在 = null，不是 0
      "page": {"114": {...}, "115": {...}},
      "parent_key": "...", "children": ["..."], "dept": "...",
      "unresolved": false, "name_changed": false
    }
  }
}
```

- canonical key ＝**最新年度**的 key；舊年度項目依序套用 114→115、115→116 的 crosswalk 後併入。
- 缺年份一律 `null`；**不自動補 0**、不猜測對應（對不上就各自獨立成一筆，並列入報告）。
- 差額與增減率**不存入 JSON**，由前端依 `amount_元` 計算（避免兩份真相）。計算規則沿用 `_build_compare_json`：前值為 0 或 null → 增減率 `null`。
- 只含實際有 ≥2 個年度資料或需要顯示的項目；體積需在驗收時回報（預期遠小於 `search.json`）。

### 3.2 前端

- 新頁 `#/<年>/趨勢?items=<key;key…>&mode=amount|yoy|index`
  - `amount`：各年金額折線／群組長條；`yoy`：逐年差額與增減率；`index`：以起始年為 100 的指數（讓不同量級的科目可比）。
  - `items` 第一個為主項目，其餘為自選比較對象；上限 8 個。
- 元件：`ItemPicker.vue`（搜尋＋依款／計畫階層挑選，可用 MiniSearch）、`TrendChart.vue`（ECharts line）、趨勢表（沿用 `DataTable`、匯出沿用 `toCompareExportRows` 風格）。
- 入口：比較頁、歲出／歲入 drill 節點、搜尋結果加「看趨勢」連結（帶入該項目 key）。B3 範圍含這三處。
- 資料層：`web/src/data/types.ts` 加 `SeriesData`；`source.ts` 加 `series()`（載入失敗回 `null`，優雅降級）；`web/src/views/trend/trendModel.ts` 放純函式（取序列、算差額／增減率／指數、缺值處理），可獨立單元測試。
- 只有 1 個年度資料時頁面顯示提示、不報錯。

### 3.3 不改的東西

`raw/**`、`data/*.csv`、`corrections.csv`、既有 `compare_*.json` 格式與既有頁面行為。

## 4. 工作拆解與平行化

先定**契約**（Step 0），之後後端、前端、檢核三條線可同時進行，互不等待實作細節。

```
Step 0  契約（Claude + 使用者核准）
   ├── Lane A 後端 series.json        [agy]      ┐
   ├── Lane B 前端資料層 + trendModel [agy]      ├ 平行（用手寫 fixture 對齊契約）
   ├── Lane C 獨立驗證腳本 / 測試     [Claude]   ┘
   │
Step 1  整合：B 的 UI 元件 B2/B3（Picker、Chart）可再平行 [agy ×2]
Step 2  Gate：Claude 驗證 + code review → 退回修正 → 再驗
Step 3  端到端驗收（瀏覽器）→ 使用者確認 → commit／PR
```

| ID | 工作 | 執行者 | 依賴 | 產出 |
|---|---|---|---|---|
| S0 | 定稿 `series.json` schema、`tests/fixtures/series_sample.json`（3 年、含改碼、缺年、改名案例）、前端 `SeriesData` 型別草稿 | Claude | 使用者核准本計畫 | 契約檔 |
| A1 | `build.py` 新增 `_build_series_json`、`_write_series_file`（鏈式套用 crosswalk、決定性排序、沒有 ≥2 年時不輸出並清除殘留檔，比照 `_write_compare_files`）；`index.json` 加 `series_years` | agy | S0 | build.py 改動 |
| A2 | `tests/test_series.py`：schema、缺年為 null、改碼鏈（114 項 04-03 ↔ 115 04-02）、決定性（跑兩次相同） | agy | S0 | 測試 |
| B1 | `types.ts`、`source.ts`、`trendModel.ts` + `web/tests/trendModel.test.ts`（用 S0 fixture） | agy | S0 | 資料層 |
| B2 | `ItemPicker.vue` + 路由 `趨勢` + URL 參數同步 | agy（獨立 worktree） | B1 型別 | 元件 |
| B3 | `TrendChart.vue`、趨勢表、匯出、各頁「看趨勢」入口 | agy（獨立 worktree） | B1 型別 | 元件 |
| C1 | `scripts/check_series.py`（獨立驗證，見 §5），**不 import build.py 的 series 邏輯** | Claude | S0 | 驗證腳本 |
| R1 | Code review：後端（A1/A2） | Claude | A1、A2 | 審查意見 |
| R2 | Code review：前端（B1–B3） | Claude | B1–B3 | 審查意見 |
| V1 | 整合驗證與端到端檢查 | Claude | 全部 | 驗證報告 |

平行規則：
- 每條 agy 工作用獨立 `git worktree add ../wb-<lane> -b feat/series-<lane> main`，不在同一 checkout 切換；完成後 `git worktree remove`。
- A 與 B 只透過 S0 契約溝通；B 階段用 fixture，不等 A 完成。
- A、B 完成後各自分支先合併到一條整合分支 `feat/series`，再跑全部檢核；不直接推 `main`。
- agy 在 herdr 的**可見 pane** 開啟；選模型前先讀畫面確認游標位置。

## 5. 資料驗證與檢核（Claude 負責）

`scripts/check_series.py`（C1）從 **CSV 與各年 `site/data/<年>.json`** 直接重算，與 `series.json` 逐項比對；不採用 build.py 的中間結果。

| # | 檢核 | 失敗處理 |
|---|---|---|
| D1 | 每個 `items[k].amount_元[年]` 等於該年度來源（歲入細目＝明細加總＋`_known_diff`；plan＝`plans.csv` 總額；object＝用途別小計；款／項＝hierarchy） | 退出碼 1，列出 key／年度／兩邊數值 |
| D2 | 與既有 `compare_<a>_<b>.json` 交叉比對：兩年皆有值者，金額與 `diff_元` 完全一致 | 同上 |
| D3 | 沒有憑空補 0：缺年份必為 `null`；`only_<年>` 與 compare 檔狀態一致 | 同上 |
| D4 | crosswalk：只有 `codes.csv` 登記的年度對被改碼；115→116 不受 114 的規則影響；改碼後無兩個舊 key 併入同一 canonical key | 同上 |
| D5 | 階層一致：`parent_key`／`children` 存在於 items；子項加總＝父項（既有已知差額除外，需列出而非隱藏） | 同上 |
| D6 | 決定性：連跑 `build.py` 兩次，`site/data/` 無差異 | 同上 |
| D7 | 抽樣人工核對：每年隨機 ≥10 項，對照 `raw/` 或 PDF 頁面（114 PDF 不在 git，僅本機） | 結果寫入驗證報告 |
| D8 | 既有基準不退步：`validate.py 114 --partial`／`115`／`116` 數字與 CLAUDE.md 基準相同；`unittest discover` 後 `git status --short` 無意外變動 | 退出碼 1 |

不一致處**不自動修正**，列入報告交使用者。

## 6. Code Review 清單（Claude 負責）

- 正確性：缺值／零值／負值增減率；前值為 0；`null` 不被當 0 畫在圖上；指數基準年缺值的處理。
- 契約：前後端型別與 schema 一致；不新增 `site/data` 以外的輸出、不改既有 JSON 格式。
- 範圍：沒有動 `raw/`、`data/` CSV、既有頁面行為；沒有引入新 Python 套件（只用標準函式庫）或不必要的前端相依。
- 決定性與清除殘留檔邏輯；錯誤降級（`series.json` 缺失頁面不崩潰）。
- 前端：URL 參數非法（未知 key、超過上限、重複）的處理；a11y（圖表需有表格對照）；大量項目時效能。
- 測試：新測試會在沒有修正時失敗；沒有只複述實作的測試。
- 審查結果分級（阻擋／建議），阻擋項退回 agy 修正後由 Claude **重跑 D1–D8** 再放行。

## 7. 驗收標準

1. `python3 scripts/build.py` 兩次無差異；`python3 scripts/check_series.py` 全數通過。
2. `python3 -m unittest discover -s tests` 通過，且 `git status --short` 只剩本功能的預期變更。
3. `cd web && npm ci && npm test && npm run build` 通過。
4. 瀏覽器實測：選一個歲入款＋一個歲出計畫＋一個細目，三個模式（金額／逐年增減／指數）數字與表格一致，重新整理後 URL 還原同一畫面。
5. Claude 的驗證報告與 code review 無未解決的阻擋項。

## 8. 風險與待決定

- 項目跨年改碼或改名但 crosswalk 沒登記時，會被視為不同項目；做法是列出清單給使用者決定，不自動猜。
- 只有 3 個年度，趨勢圖為 3 個點；功能設計成年度增加時自動延伸。
- 已決定（使用者，2026-11-21）：(a) 首版**包含**歲出「用途別」層級；(b) 「看趨勢」入口放**比較頁、歲出／歲入 drill 節點、搜尋結果**；(c) 比較對象上限 **8 個**。

## 9. 流程（遵守 CLAUDE.md）

唯讀探勘（已完成）→ 本計畫 → **獨立審查（Claude／另一個模型審本計畫）** → **使用者核准** → 實作（agy）→ 獨立驗證與 review（Claude）→ 使用者確認 → Conventional Commits（繁中）、新分支、`gh pr create`，**由使用者自行在 GitHub 合併**。commit 前先列出檔案清單與完整訊息。
