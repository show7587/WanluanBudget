import { computeDiff, type FlatRow } from "@/data/normalize";
import type { CompareData, CompareEntry, DiffStatus, TreeNode } from "@/data/types";

export type CompareScope = "plan" | "object" | "revenue_kuan" | "revenue_xiang";
export type CompareFilter = "all" | "new" | "up" | "down";
export type CompareSort = "abs_diff" | "diff_desc" | "diff_asc" | "pct_desc" | "pct_asc" | "amount";

export const COMPARE_SCOPES: ReadonlyArray<{ key: CompareScope; group: "歲出" | "歲入"; label: string; shortLabel: string }> = [
  { key: "plan", group: "歲出", label: "歲出：工作計畫", shortLabel: "工作計畫" },
  { key: "object", group: "歲出", label: "歲出：用途別", shortLabel: "用途別" },
  { key: "revenue_kuan", group: "歲入", label: "歲入：款", shortLabel: "歲入款" },
  { key: "revenue_xiang", group: "歲入", label: "歲入：項", shortLabel: "歲入項" },
];

export const COMPARE_SCOPE_KEYS = COMPARE_SCOPES.map((s) => s.key) as readonly CompareScope[];

export const COMPARE_FILTERS: ReadonlyArray<{ key: CompareFilter; label: string; symbol?: string }> = [
  { key: "all", label: "全部" },
  { key: "new", label: "新增", symbol: "★" },
  { key: "up", label: "增加", symbol: "▲" },
  { key: "down", label: "減少", symbol: "▼" },
];

export const COMPARE_FILTER_KEYS = COMPARE_FILTERS.map((f) => f.key) as readonly CompareFilter[];

export const COMPARE_SORTS: ReadonlyArray<{ key: CompareSort; label: string }> = [
  { key: "abs_diff", label: "增減金額幅度（大→小）" },
  { key: "diff_desc", label: "增減金額（增加最多優先）" },
  { key: "diff_asc", label: "增減金額（減少最多優先）" },
  { key: "pct_desc", label: "增減 %（增加最多優先）" },
  { key: "pct_asc", label: "增減 %（減少最多優先）" },
  { key: "amount", label: "本年度金額（高→低）" },
];

export const COMPARE_SORT_KEYS = COMPARE_SORTS.map((s) => s.key) as readonly CompareSort[];

const round2 = (n: number): number => Math.round(n * 100) / 100;

function resolveDiff(
  rawPrev: number | null | undefined,
  rawCur: number | null | undefined,
): { amount: number; prev: number | null; diff: number | null; pct: number | null; status: DiffStatus } {
  const hasPrev = typeof rawPrev === "number";
  const hasCur = typeof rawCur === "number";
  const amount = hasCur ? rawCur : 0;
  const prev = hasPrev ? rawPrev : 0;

  if (hasCur && !hasPrev) {
    return amount === 0
      ? { amount: 0, prev: 0, diff: 0, pct: 0, status: "flat" }
      : { amount, prev: 0, diff: amount, pct: null, status: "new" };
  }
  if (!hasCur && hasPrev) {
    return prev === 0
      ? { amount: 0, prev: 0, diff: 0, pct: 0, status: "flat" }
      : { amount: 0, prev, diff: -prev, pct: -100, status: "removed" };
  }
  if (!hasCur && !hasPrev) {
    return { amount: 0, prev: null, diff: null, pct: null, status: "unknown" };
  }
  if (amount === 0 && prev > 0) {
    return { amount: 0, prev, diff: -prev, pct: -100, status: "removed" };
  }
  return { amount, ...computeDiff(amount, prev, false) };
}

function entryToNode(entry: CompareEntry, fromKey: string, toKey: string): TreeNode {
  const rawPrev = entry.amount_元[fromKey] as number | null | undefined;
  const rawCur = entry.amount_元[toKey] as number | null | undefined;
  const { amount, prev, diff, pct, status } = resolveDiff(rawPrev, rawCur);
  return {
    id: entry.key,
    // 工作計畫有同名者（例如「一般行政-行政管理」），加上代碼末 5 碼以便區分
    name: entry.kind === "plan" ? `${entry.display_name}（${entry.code.slice(-5)}）` : entry.display_name,
    level: entry.level,
    code: entry.code,
    amount,
    prev,
    diff,
    pct,
    status,
    children: [],
  };
}

function buildObjectNodes(entries: CompareEntry[], fromKey: string, toKey: string): TreeNode[] {
  const groups = new Map<
    string,
    { code: string; name: string; prevSum: number; curSum: number; hasPrev: boolean; hasCur: boolean }
  >();

  for (const e of entries) {
    if (e.kind !== "object" || e.level !== "用途別") continue;
    const objCode = e.code.includes("|") ? e.code.split("|")[1] : e.code;
    const rawPrev = e.amount_元[fromKey] as number | null | undefined;
    const rawCur = e.amount_元[toKey] as number | null | undefined;
    const slot = groups.get(objCode) ?? {
      code: objCode,
      name: e.display_name,
      prevSum: 0,
      curSum: 0,
      hasPrev: false,
      hasCur: false,
    };
    if (typeof rawPrev === "number") {
      slot.prevSum += rawPrev;
      slot.hasPrev = true;
    }
    if (typeof rawCur === "number") {
      slot.curSum += rawCur;
      slot.hasCur = true;
    }
    groups.set(objCode, slot);
  }

  return [...groups.values()].map((g) => {
    const { amount, prev, diff, pct, status } = resolveDiff(
      g.hasPrev ? g.prevSum : null,
      g.hasCur ? g.curSum : null,
    );
    return {
      id: `object:${g.code}`,
      name: g.name,
      level: "用途別",
      code: g.code,
      amount,
      prev,
      diff,
      pct,
      status,
      children: [],
    };
  });
}

/** 依指定比較面向抽出正規化節點（金額單位一律為元） */
export function buildCompareNodes(compare: CompareData, scope: CompareScope): TreeNode[] {
  const fromKey = String(compare.from_year);
  const toKey = String(compare.to_year);
  const entries = Object.values(compare.entries);

  if (scope === "object") {
    return buildObjectNodes(entries, fromKey, toKey);
  }

  const predicate: (e: CompareEntry) => boolean =
    scope === "plan"
      ? (e) => e.kind === "plan" && e.level === "工作計畫"
      : scope === "revenue_kuan"
        ? (e) => e.kind === "revenue" && e.level === "款"
        : (e) => e.kind === "revenue" && e.level === "項";

  return entries.filter(predicate).map((e) => entryToNode(e, fromKey, toKey));
}

export function filterCompareNodes(nodes: TreeNode[], filter: CompareFilter): TreeNode[] {
  if (filter === "all") return nodes;
  if (filter === "new") return nodes.filter((n) => n.status === "new");
  if (filter === "up") return nodes.filter((n) => n.status === "up");
  return nodes.filter((n) => n.status === "down" || n.status === "removed");
}

function pctSortValue(n: TreeNode, desc: boolean): number {
  if (n.status === "new") return desc ? Number.POSITIVE_INFINITY : Number.POSITIVE_INFINITY;
  if (n.pct == null) return desc ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY;
  return n.pct;
}

export function sortCompareNodes(nodes: TreeNode[], sort: CompareSort): TreeNode[] {
  const copy = [...nodes];
  copy.sort((a, b) => {
    const da = a.diff ?? 0;
    const db = b.diff ?? 0;
    let cmp = 0;
    if (sort === "abs_diff") {
      cmp = Math.abs(db) - Math.abs(da) || db - da;
    } else if (sort === "diff_desc") {
      cmp = db - da;
    } else if (sort === "diff_asc") {
      cmp = da - db;
    } else if (sort === "pct_desc") {
      const pa = pctSortValue(a, true);
      const pb = pctSortValue(b, true);
      cmp = pb === pa ? db - da : pb - pa;
    } else if (sort === "pct_asc") {
      const pa = pctSortValue(a, false);
      const pb = pctSortValue(b, false);
      cmp = pa === pb ? da - db : pa - pb;
    } else {
      cmp = b.amount - a.amount;
    }
    return cmp || b.amount - a.amount || a.name.localeCompare(b.name, "zh-Hant-TW");
  });
  return copy;
}

export interface CompareSummary {
  total: number;
  newCount: number;
  upCount: number;
  downCount: number;
  flatCount: number;
  curTotal: number;
  prevTotal: number;
  netDiff: number;
  netPct: number | null;
}

export function summarizeCompareNodes(nodes: TreeNode[]): CompareSummary {
  let newCount = 0;
  let upCount = 0;
  let downCount = 0;
  let flatCount = 0;
  let curTotal = 0;
  let prevTotal = 0;

  for (const n of nodes) {
    curTotal += n.amount;
    prevTotal += n.prev ?? 0;
    if (n.status === "new") newCount++;
    else if (n.status === "up") upCount++;
    else if (n.status === "down" || n.status === "removed") downCount++;
    else if (n.status === "flat") flatCount++;
  }

  const netDiff = curTotal - prevTotal;
  const netPct = prevTotal > 0 ? round2((netDiff / prevTotal) * 100) : null;

  return {
    total: nodes.length,
    newCount,
    upCount,
    downCount,
    flatCount,
    curTotal,
    prevTotal,
    netDiff,
    netPct,
  };
}

export function toCompareExportRows(nodes: TreeNode[], scopeLabel: string): FlatRow[] {
  return nodes.map((n) => ({
    path: [scopeLabel, n.name],
    name: n.name,
    level: n.level,
    amount: n.amount,
    prev: n.prev,
    diff: n.diff,
    pct: n.pct,
    status: n.status,
  }));
}
