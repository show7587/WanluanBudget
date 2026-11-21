# series.json 契約（S0）

本檔是 `docs/PLAN-series.md` §3 的定稿，Lane A（後端）、Lane B（前端）、Lane C（檢核）一律以本檔為準。和計畫衝突時以本檔為準，並回報主 session。

相關檔案：

- `tests/fixtures/series_sample.json`：符合本檔 schema 的節錄範例（§6）。
- `tests/fixtures/series_expected.json`：範例每個項目的差額、增減率、指數期望值（§4），手算。
- `tests/test_series_fixture.py`：檢查上面兩個檔案彼此一致、符合本檔（不測任何實作）。

## 1. 檔案與格式

- 路徑：`site/data/series.json`。由 `scripts/build.py` 產生，決定性輸出（重跑位元組相同）。
- 序列化方式比照既有 JSON：`json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"`。
- 年度少於 2 個時不輸出，並刪除殘留的 `series.json`（比照 `_write_compare_files`）。
- `site/data/index.json` 新增 `"series_years": [114, 115, 116]`（不輸出 series 時為 `[]`）。
- 體積上限 350KB（計畫 §8.1 X2）。

## 2. Schema

```text
{
  "years":   [int, ...]                     遞增
  "items":   { <canonical_key>: Item, ... }
  "aliases": { "<年>:<原始key>": <canonical_key>, ... }
}
```

`Item` 欄位（「逐年」表示 `{ "<年>": 值 }`，**只列該年有此項目的年度**，唯一例外是 `amount_元`）：

| 欄位 | 型別 | 規則 |
|---|---|---|
| `kind` | `"revenue"`｜`"plan"`｜`"object"` | |
| `level` | `"款"`｜`"項"`｜`"子目"`｜`"細目"`｜`"工作計畫"`｜`"用途別"` | revenue 用前四種；plan＝工作計畫；object＝用途別 |
| `code` | string | canonical 代碼，即 canonical key 去掉 `<kind>:` 與 `@<年>` 後綴（`revenue:04-02@114` 的 code 是 `04-02`）。object 的 code 為 `<計畫碼>\|<用途別碼>` |
| `display_name` | string | 最新一個有資料年度的名稱 |
| `name` | 逐年 string | |
| `amount_元` | `{年: int \| null}` | **`years` 每一年都有鍵**；該年沒有此項目為 `null`，不是 0 |
| `page` | 逐年 `{page, page_start, page_end}` | 與 `compare_*.json` 同結構 |
| `parent_key` | 逐年 canonical key 或 `null` | 最上層（款、工作計畫）為 `null`；不在歲入階層內的細目也是 `null` |
| `children` | 逐年 canonical key 陣列 | 依 canonical key 字串遞增排序；沒有子項為 `[]` |
| `dept` | 逐年 string | 沒有則 `""` |
| `政事別` | 逐年 string | **只有** plan／object 有此欄位 |
| `unresolved` | 逐年 bool | |
| `name_changed` | bool | 有資料的年度中名稱不只一種 |

`items` 的順序：`kind`（revenue → plan → object）→ revenue 的 `level`（款 → 項 → 子目 → 細目）→ canonical key 字串遞增。

金額來源與既有 `_collect_year_compare_items` 相同：歲入款／項／子目取各年 `<年>.json` 的歲入階層，細目＝明細加總 − `_known_diff`；plan＝計畫總額；object＝計畫下用途別小計。

**收錄範圍**：所有年度 `_collect_year_compare_items` 產生的項目全部收錄（包含只出現一年的）。不含政事別合計、機關合計、跨計畫用途別合計、歲入／歲出總計。

## 3. canonical key 與 aliases

原始 key 格式沿用既有：`revenue:<code>`、`plan:<11碼>`、`object:<計畫碼>|<用途別碼>`。

1. 對每個相鄰年度對 (Y, Y+1)，取 `codes.csv` 中 `from_year=Y, to_year=Y+1` 的列，定義 `f_Y(code)`：
   - `code` 是某列 `from_code` → 回傳該列 `to_code`；
   - 否則 `code` 是某列 `to_code` → **斷鏈**；
   - 否則回傳 `code`。
2. Y 年的項目依序套用 `f_Y, f_{Y+1}, …` 到最新年度：
   - 全程沒斷鏈 → `<kind>:<最終代碼>`；
   - 進入 Z 年時斷鏈 → `<kind>:<斷鏈前的代碼>@<Z-1>`。
3. canonical key 相同的跨年項目合併成一條；**同一年度有兩個項目得到同一個 canonical key → 報錯**。
4. `parent_key`、`children` 都換成 canonical key。
5. `aliases` 收錄所有「原始 key ≠ canonical key」的 `"<年>:<原始key>"`，依字串遞增排序；相同的不列。
6. 只對 `kind=revenue` 套用。`codes.csv` 的 `from_code` 或 `to_code` 等於任何年度的計畫代碼 → 報錯（plan 改碼需連帶改寫 object key，尚未實作）。
7. `codes.csv` 有 `to_year != from_year + 1` 的列 → 報錯。

**解析順序（前端與檢核共用）**：給定年度 Y 與原始 key k，先查 `aliases["Y:k"]`，查不到才把 k 當 canonical key 直接使用。不能先查 `items[k]`：例如 `114:revenue:04-02` 必須解析成 `revenue:04-02@114`（財產售價），直接用 `revenue:04-02` 會誤命中廢舊物資售價。

**與 compare 的對應**：`compare_<a>_<b>.json` 的 key 用年度對中**舊年度**的代碼（`_write_compare_files` 是把新年度代碼換成舊年度代碼）。所以 compare key `k` 對應 series 的 `aliases.get("<a>:" + k, k)`。

## 4. 前端計算規則（不存入 JSON）

設某項目逐年金額 `v[Y]`，`Y` 依 `years` 排列，`P` 為前一個年度（不是前一個有值的年度）。

- **差額** `diff_元[Y]`：`Y` 是第一年 → `null`；`v[Y]` 或 `v[P]` 為 `null` → `null`；否則 `v[Y] − v[P]`。
  與 `compare_*.json` 的 `diff_元`（缺值當 0）**刻意不同**。
- **增減率** `pct[Y]`（%）：`Y` 是第一年 → `null`；`v[Y]` 或 `v[P]` 為 `null` → `null`；兩者皆 0 → `0`；`v[P]` 為 0 → `null`；否則 `round((v[Y]−v[P]) / v[P] × 100, 2)`。缺值年不跳過去比更早的年度。
- **指數** `index[Y]`：基準年 `B` ＝ 第一個 `v` 非 `null` 且非 0 的年度；找不到 → 整條 `null`、`index_base_year=null`。否則 `v[Y]` 為 `null` → `null`，其餘 `round(v[Y] / v[B] × 100, 2)`（基準年之前的 0 值年度得 0）。
- 捨入：小數 2 位、四捨五入。範例中的數值都避開了 `.xx5` 的邊界，因此 JS `Math.round(x*100)/100` 與 Python `round` 結果相同。
- 比對期望值時，`100` 與 `100.0` 視為相同（數值相等）。

## 5. 趨勢頁 URL（Lane B 定義，其他 lane 只產生連結）

`#/<年>/趨勢?items=<key>;<key>…&mode=amount|yoy|index`

- `<key>` 可以是 canonical key，或 `<年>:<原始key>`（經 §3 解析）；用 `encodeURIComponent` 編碼。
- 第一個是主項目；最多 8 個；未知 key、重複、超過上限要過濾並提示。
- `mode` 省略時為 `amount`。

## 6. 範例 fixture（節錄）

`series_sample.json` 是從 114–116 真實資料節錄 13 個項目，再加 3 個合成項目（代碼 `99-xx`，真實資料沒有）。節錄規則：

- `children` 只列 fixture 內有的 key（例如 `revenue:04` 在 114 的真實子項還有 `revenue:04-01`，這裡省略）。
- `parent_key` 指向 fixture 外的項目時寫 `null`（`revenue:05120010104` 與 `revenue:09120010101` 的真實父項子目不在 fixture 內）。
- 因此 fixture 內**父子金額加總不保證相等**；加總檢查（D5）只在真實資料上做。

合成項目假設的 `codes.csv` 列（只用於 fixture 與 Lane A 的單元測試，**不寫進真實 `data/crosswalk/codes.csv`**）：

```csv
from_year,from_code,to_year,to_code,note
114,04-03,115,04-02,（真實存在的那一列）
114,99-01,115,99-02,合成：鏈式改碼第一步
115,99-02,116,99-03,合成：鏈式改碼第二步
```

### 必備案例對照

| 案例 | fixture key | 看哪裡 |
|---|---|---|
| 114 `04-03` → 115 `04-02` 改碼 | `revenue:04-02` | 114 的值 20000 來自 114 的 04-03；`aliases["114:revenue:04-03"]` |
| 被擠掉的 114 `04-02` | `revenue:04-02@114` | `aliases["114:revenue:04-02"]`；其子目 `revenue:07120010200` 的 `parent_key` 指向它 |
| 改碼後父子關係換成 canonical key | `revenue:07120010500` | 114 的 `parent_key` 是 `revenue:04-02`（原始為 04-03） |
| 中間年缺值 | `revenue:09120010101`、`plan:51120019101` | 115 為 `null`；116 的差額不拿 114 比 |
| 只出現一年 | `plan:37120010105`、`revenue:04-02@114`、`object:51120019101\|3035` | |
| 改名 | `revenue:99-10`（合成） | `name_changed=true`，`display_name` 取 116 |
| 0 值、前一年為 0、兩年皆 0 | `revenue:99-10`（合成）、`revenue:05120010104` | 99-10：115 對 114 兩年皆 0 → 0%；116 對 115 前一年 0 → `null` |
| 負增減 | `revenue:99-03`（合成） | 116：−30、−20% |
| 鏈式改碼 | `revenue:99-03`（合成） | `aliases` 有 114 與 115 兩列 |
| 指數基準年不是第一年 | `revenue:99-20`（第一年 `null`）、`revenue:99-10`（第一年 0） | 基準年 115、116 |
| 沒有任何非 0 值 | `revenue:05120010104` | `index_base_year=null` |
| plan／object 的 `政事別` 欄位 | `plan:51120019101`、`object:51120019101\|3010` | |

## 7. 前端型別草稿（Lane B 照抄進 `web/src/data/types.ts`）

```ts
export type SeriesKind = "revenue" | "plan" | "object";
export type SeriesLevel = "款" | "項" | "子目" | "細目" | "工作計畫" | "用途別";

/** 以年度字串為 key；只含該年有此項目的年度 */
export type ByYear<T> = Record<string, T>;

export interface SeriesPage {
  page: number;
  page_start: number;
  page_end: number;
}

export interface SeriesItem {
  kind: SeriesKind;
  level: SeriesLevel;
  code: string;
  display_name: string;
  name: ByYear<string>;
  /** years 每一年都有鍵；沒有資料為 null（不是 0） */
  amount_元: Record<string, number | null>;
  page: ByYear<SeriesPage>;
  parent_key: ByYear<string | null>;
  children: ByYear<string[]>;
  dept: ByYear<string>;
  /** 只有 plan / object 有 */
  政事別?: ByYear<string>;
  unresolved: ByYear<boolean>;
  name_changed: boolean;
}

export interface SeriesData {
  years: number[];
  items: Record<string, SeriesItem>;
  /** "<年>:<原始key>" → canonical key */
  aliases: Record<string, string>;
}

/** 前端計算結果（trendModel.ts），不在 JSON 裡 */
export interface SeriesDerived {
  diff_元: Record<string, number | null>;
  pct: Record<string, number | null>;
  index_base_year: number | null;
  index: Record<string, number | null>;
}
```

`index.json` 的型別加上 `series_years?: number[]`（舊資料沒有此欄位時視為 `[]`）。

前端測試用 `import` 載入 fixture 時，TypeScript 會把 `kind`、`level` 放寬成 `string`，請以 `as SeriesData` 轉型；合法值已由 `tests/test_series_fixture.py` 檢查。S0 已用 `tsc --strict` 確認本型別能描述兩個 fixture。
