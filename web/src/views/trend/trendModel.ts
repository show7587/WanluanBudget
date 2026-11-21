import type { SeriesData, SeriesDerived, SeriesItem, SeriesKind, SeriesLevel } from "@/data/types";

export const MAX_TREND_ITEMS = 8;

export type TrendMode = "amount" | "yoy" | "index";

export const TREND_MODES: ReadonlyArray<{ key: TrendMode; label: string; desc: string }> = [
  { key: "amount", label: "金額", desc: "各年度原編預算金額（元）" },
  { key: "yoy", label: "逐年增減", desc: "與前一年度之差額與增減率" },
  { key: "index", label: "指數", desc: "以第一個非零有值年度為 100" },
];

export const TREND_MODE_KEYS = TREND_MODES.map((m) => m.key) as readonly TrendMode[];

const hasOwn = (obj: Record<string, unknown>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(obj, key);

const round2 = (x: number): number => {
  const r = Math.round(x * 100) / 100;
  return Object.is(r, -0) ? 0 : r;
};

/**
 * 解析項目 key（契約 §3）：
 * 先查 aliases["<年>:<原始key>"]（或 aliases[rawKey]），查不到才去掉 "<年>:" 前綴當 canonical key 使用。
 * 絕對不能先查 items[k] 再查 aliases，否則 114:revenue:04-02 會誤命中 revenue:04-02。
 */
export function resolveSeriesKey(data: SeriesData, rawKey: string): string | null {
  const trimmed = String(rawKey ?? "").trim();
  if (!trimmed) return null;

  if (data.aliases && hasOwn(data.aliases, trimmed)) {
    const mapped = data.aliases[trimmed];
    return hasOwn(data.items, mapped) ? mapped : null;
  }

  const m = /^\d+:(.+)$/.exec(trimmed);
  const candidate = m ? m[1] : trimmed;
  return hasOwn(data.items, candidate) ? candidate : null;
}

/** 給定年度 Y 與原始 key k（例：114, "revenue:04-02"），經 aliases 解析成 canonical key */
export function resolveYearRawKey(data: SeriesData, year: number | string, rawKey: string): string | null {
  return resolveSeriesKey(data, `${year}:${rawKey}`);
}

export interface ParsedTrendItems {
  keys: string[];
  notices: string[];
  droppedUnknown: string[];
  droppedDuplicate: string[];
  droppedOverflow: string[];
}

/** 解析 URL 的 items 參數（以 ; 分隔）；過濾未知 key、重複項與超過 8 項者，並產生提示訊息 */
export function parseTrendItemsParam(data: SeriesData, rawParam: string | undefined): ParsedTrendItems {
  const tokens = String(rawParam ?? "")
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);

  const keys: string[] = [];
  const seen = new Set<string>();
  const droppedUnknown: string[] = [];
  const droppedDuplicate: string[] = [];
  const droppedOverflow: string[] = [];

  for (const tok of tokens) {
    const resolved = resolveSeriesKey(data, tok);
    if (!resolved) {
      droppedUnknown.push(tok);
      continue;
    }
    if (seen.has(resolved)) {
      droppedDuplicate.push(tok);
      continue;
    }
    if (keys.length >= MAX_TREND_ITEMS) {
      droppedOverflow.push(tok);
      continue;
    }
    seen.add(resolved);
    keys.push(resolved);
  }

  const notices: string[] = [];
  if (droppedUnknown.length) {
    notices.push(`已略過 ${droppedUnknown.length} 個無法辨識的項目代碼：${droppedUnknown.join("、")}`);
  }
  if (droppedDuplicate.length) {
    notices.push(`已合併 ${droppedDuplicate.length} 個重複項目。`);
  }
  if (droppedOverflow.length) {
    notices.push(`最多同時比較 ${MAX_TREND_ITEMS} 個項目，已略過超出上限的 ${droppedOverflow.length} 個項目。`);
  }

  return { keys, notices, droppedUnknown, droppedDuplicate, droppedOverflow };
}

export function encodeTrendItemsParam(keys: readonly string[]): string | undefined {
  return keys.length ? keys.join(";") : undefined;
}

/** 產生前往趨勢頁的路由目標（一律使用 <年>:<原始key> 形式交由趨勢頁經 aliases 解析） */
export function buildTrendRoute(
  year: number,
  yearPrefixedKey: string,
): { path: string; query: { items: string } } {
  return {
    path: `/${year}/趨勢`,
    query: { items: yearPrefixedKey },
  };
}

/**
 * 依契約 §4 計算單一項目的差額、增減率與指數：
 * - diff_元[Y]：第一年為 null；v[Y] 或 v[P] 為 null → null；否則 v[Y] - v[P]
 * - pct[Y]：第一年為 null；v[Y] 或 v[P] 為 null → null；兩者皆 0 → 0；v[P] 為 0 → null；否則 round2((v[Y]-v[P])/v[P]*100)
 * - index[Y]：基準年 B = 第一個非 null 且非 0 的年度；找不到則 index_base_year=null 且整條為 null
 */
export function computeSeriesDerived(item: SeriesItem, years: readonly number[]): SeriesDerived {
  const diff_元: Record<string, number | null> = {};
  const pct: Record<string, number | null> = {};
  const index: Record<string, number | null> = {};

  for (let i = 0; i < years.length; i++) {
    const yKey = String(years[i]);
    const cur = item.amount_元[yKey] ?? null;
    if (i === 0) {
      diff_元[yKey] = null;
      pct[yKey] = null;
      continue;
    }
    const prevKey = String(years[i - 1]);
    const prev = item.amount_元[prevKey] ?? null;
    if (cur === null || prev === null) {
      diff_元[yKey] = null;
      pct[yKey] = null;
    } else {
      const diff = cur - prev;
      diff_元[yKey] = diff;
      if (cur === 0 && prev === 0) {
        pct[yKey] = 0;
      } else if (prev === 0) {
        pct[yKey] = null;
      } else {
        pct[yKey] = round2((diff / prev) * 100);
      }
    }
  }

  let index_base_year: number | null = null;
  let baseVal: number | null = null;
  for (const y of years) {
    const v = item.amount_元[String(y)] ?? null;
    if (v !== null && v !== 0) {
      index_base_year = y;
      baseVal = v;
      break;
    }
  }

  for (const y of years) {
    const yKey = String(y);
    if (index_base_year === null || baseVal === null) {
      index[yKey] = null;
    } else {
      const v = item.amount_元[yKey] ?? null;
      index[yKey] = v === null ? null : round2((v / baseVal) * 100);
    }
  }

  return { diff_元, pct, index_base_year, index };
}

/** 回傳該項目有資料（非 null）的年度清單 */
export function activeYearsOf(item: SeriesItem, years: readonly number[]): number[] {
  return years.filter((y) => item.amount_元[String(y)] != null);
}

/** 格式化項目標籤，區分 @<年> 斷鏈項目、同名工作計畫與計畫下用途別 */
export function formatSeriesItemLabel(key: string, item: SeriesItem, allItems?: Record<string, SeriesItem>): string {
  const atIdx = key.indexOf("@");
  if (atIdx !== -1) {
    const suffix = key.slice(atIdx + 1);
    return `${item.display_name}（${item.code}@${suffix}）`;
  }
  if (item.kind === "object") {
    const planCode = item.code.split("|")[0] ?? "";
    const parentPlan = allItems?.[`plan:${planCode}`];
    if (parentPlan) {
      return `${parentPlan.display_name} / ${item.display_name}`;
    }
    return `${item.display_name}（${item.code}）`;
  }
  if (item.kind === "plan") {
    return `${item.display_name}（${item.code.slice(-5)}）`;
  }
  return item.display_name;
}

/** 取得項目最新有資料年度的機關／政事別摘要 */
export function latestMetaOf(item: SeriesItem, years: readonly number[]): { dept: string; category: string } {
  const active = activeYearsOf(item, years);
  for (let i = active.length - 1; i >= 0; i--) {
    const yKey = String(active[i]);
    const dept = item.dept[yKey] ?? "";
    const category = item.政事別?.[yKey] ?? "";
    if (dept || category) return { dept, category };
  }
  return { dept: "", category: "" };
}

/** 取得項目所有曾出現過的舊名稱（不含目前 display_name） */
export function historicalNamesOf(item: SeriesItem): string[] {
  const names = new Set<string>();
  for (const n of Object.values(item.name)) {
    if (n && n !== item.display_name) names.add(n);
  }
  return [...names];
}

export interface SeriesSearchOption {
  key: string;
  item: SeriesItem;
  label: string;
  activeYears: number[];
  dept: string;
  category: string;
}

export type PickerFilterKey = "all" | "revenue_款" | "revenue_項" | "revenue_子目" | "revenue_細目" | "plan" | "object";

export const PICKER_FILTERS: ReadonlyArray<{ key: PickerFilterKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "revenue_款", label: "歲入：款" },
  { key: "revenue_項", label: "歲入：項" },
  { key: "revenue_子目", label: "歲入：子目" },
  { key: "revenue_細目", label: "歲入：細目" },
  { key: "plan", label: "歲出：工作計畫" },
  { key: "object", label: "歲出：用途別" },
];

function matchesPickerFilter(item: SeriesItem, filter: PickerFilterKey): boolean {
  if (filter === "all") return true;
  if (filter === "plan") return item.kind === "plan";
  if (filter === "object") return item.kind === "object";
  if (filter.startsWith("revenue_")) {
    return item.kind === "revenue" && item.level === filter.slice("revenue_".length);
  }
  return true;
}

/** 依關鍵字（空白分隔 AND）與層級篩選可選項目 */
export function searchSeriesItems(
  data: SeriesData,
  query: string,
  filter: PickerFilterKey = "all",
): SeriesSearchOption[] {
  const terms = String(query ?? "")
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);

  const out: SeriesSearchOption[] = [];
  for (const [key, item] of Object.entries(data.items)) {
    if (!matchesPickerFilter(item, filter)) continue;
    const label = formatSeriesItemLabel(key, item, data.items);
    const { dept, category } = latestMetaOf(item, data.years);

    if (terms.length) {
      const hay = [
        key,
        item.code,
        item.display_name,
        label,
        ...Object.values(item.name),
        ...Object.values(item.dept),
        ...(item.政事別 ? Object.values(item.政事別) : []),
      ]
        .join(" ")
        .toLowerCase();
      if (!terms.every((t) => hay.includes(t))) continue;
    }

    out.push({
      key,
      item,
      label,
      activeYears: activeYearsOf(item, data.years),
      dept,
      category,
    });
  }
  return out;
}

export interface PickerTreeNode {
  key: string | null;
  label: string;
  level: string;
  code?: string;
  activeYears?: number[];
  nameChanged?: boolean;
  children: PickerTreeNode[];
}

/** 建立「依階層挑選」樹狀清單：歲入依款→項→子目→細目，歲出依政事別→工作計畫→用途別；確保所有項目皆可選取 */
export function buildPickerTree(data: SeriesData): { revenue: PickerTreeNode[]; expenditure: PickerTreeNode[] } {
  const items = data.items;
  const years = data.years;

  // 1) 歲入：合併所有年度的 children 邊（避免漏掉只出現在部分年度的子項）
  const revKeys = Object.keys(items).filter((k) => items[k].kind === "revenue");
  const childSet = new Set<string>();
  const childrenMap = new Map<string, Set<string>>();

  for (const k of revKeys) {
    const it = items[k];
    const set = childrenMap.get(k) ?? new Set<string>();
    for (const arr of Object.values(it.children)) {
      for (const c of arr) {
        if (hasOwn(items, c) && items[c].kind === "revenue") {
          set.add(c);
          childSet.add(c);
        }
      }
    }
    childrenMap.set(k, set);
  }

  const visited = new Set<string>();
  const buildRevNode = (k: string): PickerTreeNode => {
    visited.add(k);
    const it = items[k];
    const kids = [...(childrenMap.get(k) ?? [])].filter((c) => !visited.has(c)).sort();
    return {
      key: k,
      label: formatSeriesItemLabel(k, it, items),
      level: it.level,
      code: it.code,
      activeYears: activeYearsOf(it, years),
      nameChanged: it.name_changed,
      children: kids.map(buildRevNode),
    };
  };

  const revRoots = revKeys.filter((k) => !childSet.has(k));
  const revenue = revRoots.map(buildRevNode);
  // 若有環狀或未被走訪到的歲入項目，補列在頂層確保不遺漏
  for (const k of revKeys) {
    if (!visited.has(k)) revenue.push(buildRevNode(k));
  }

  // 2) 歲出：依政事別分組 → 工作計畫 → 計畫下用途別
  const planKeys = Object.keys(items).filter((k) => items[k].kind === "plan");
  const objKeys = Object.keys(items).filter((k) => items[k].kind === "object");
  const objByPlan = new Map<string, string[]>();
  const orphanObjs: string[] = [];

  for (const ok of objKeys) {
    const it = items[ok];
    const parentCandidates = Object.values(it.parent_key).filter((p): p is string => Boolean(p && hasOwn(items, p)));
    const pKey = parentCandidates[parentCandidates.length - 1];
    if (pKey) {
      const list = objByPlan.get(pKey) ?? [];
      list.push(ok);
      objByPlan.set(pKey, list);
    } else {
      orphanObjs.push(ok);
    }
  }

  const byCategory = new Map<string, PickerTreeNode[]>();
  for (const pk of planKeys) {
    const it = items[pk];
    const { category } = latestMetaOf(it, years);
    const cat = category || "未分類政事別";
    const objs = (objByPlan.get(pk) ?? []).sort().map((ok) => {
      const o = items[ok];
      return {
        key: ok,
        label: o.display_name,
        level: o.level,
        code: o.code.includes("|") ? o.code.split("|")[1] : o.code,
        activeYears: activeYearsOf(o, years),
        nameChanged: o.name_changed,
        children: [],
      };
    });
    const planNode: PickerTreeNode = {
      key: pk,
      label: formatSeriesItemLabel(pk, it, items),
      level: it.level,
      code: it.code,
      activeYears: activeYearsOf(it, years),
      nameChanged: it.name_changed,
      children: objs,
    };
    const arr = byCategory.get(cat) ?? [];
    arr.push(planNode);
    byCategory.set(cat, arr);
  }

  const expenditure: PickerTreeNode[] = [...byCategory.entries()].map(([cat, plans]) => ({
    key: null,
    label: cat,
    level: "政事別",
    children: plans,
  }));

  if (orphanObjs.length) {
    expenditure.push({
      key: null,
      label: "其他用途別",
      level: "政事別",
      children: orphanObjs.sort().map((ok) => {
        const o = items[ok];
        return {
          key: ok,
          label: formatSeriesItemLabel(ok, o, items),
          level: o.level,
          code: o.code,
          activeYears: activeYearsOf(o, years),
          nameChanged: o.name_changed,
          children: [],
        };
      }),
    });
  }

  return { revenue, expenditure };
}

export interface TrendExportRow {
  key: string;
  role: "主項目" | "比較對象";
  kind: SeriesKind;
  level: SeriesLevel;
  code: string;
  name: string;
  index_base_year: number | null;
  amount_元: Record<string, number | null>;
  diff_元: Record<string, number | null>;
  pct: Record<string, number | null>;
  index: Record<string, number | null>;
}

/** 產出匯出列（比照 toCompareExportRows） */
export function toTrendExportRows(data: SeriesData, keys: readonly string[]): TrendExportRow[] {
  const out: TrendExportRow[] = [];
  keys.forEach((key, idx) => {
    const item = data.items[key];
    if (!item) return;
    const derived = computeSeriesDerived(item, data.years);
    out.push({
      key,
      role: idx === 0 ? "主項目" : "比較對象",
      kind: item.kind,
      level: item.level,
      code: item.code,
      name: formatSeriesItemLabel(key, item, data.items),
      index_base_year: derived.index_base_year,
      amount_元: { ...item.amount_元 },
      diff_元: derived.diff_元,
      pct: derived.pct,
      index: derived.index,
    });
  });
  return out;
}

const csvCell = (v: unknown): string => {
  const s = v == null ? "" : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function trendRowsToCsv(rows: readonly TrendExportRow[], years: readonly number[]): string {
  const head = [
    "角色",
    "類別",
    "層級",
    "代碼",
    "名稱",
    "指數基準年",
    ...years.flatMap((y) => [`${y}金額(元)`, `${y}差額(元)`, `${y}增減%`, `${y}指數`]),
  ];
  const lines = rows.map((r) =>
    [
      r.role,
      r.kind,
      r.level,
      r.code,
      r.name,
      r.index_base_year ?? "",
      ...years.flatMap((y) => {
        const yk = String(y);
        return [r.amount_元[yk] ?? "", r.diff_元[yk] ?? "", r.pct[yk] ?? "", r.index[yk] ?? ""];
      }),
    ]
      .map(csvCell)
      .join(","),
  );
  return "\uFEFF" + [head.map(csvCell).join(","), ...lines].join("\r\n");
}

export function trendRowsToJson(rows: readonly TrendExportRow[]): string {
  return JSON.stringify(rows, null, 2);
}
