import type { RouteLocationRaw } from "vue-router";
import { normalizeExpenditure, normalizeRevenue } from "@/data/normalize";
import type { TreeNode, YearData } from "@/data/types";
import { encodePath } from "@/utils/query";

export type MemoType = "print_typo" | "print_inconsistent" | "print_layout" | "data_gap";

export interface MemoTarget {
  kind?: string;
  search_id?: string;
  code?: string;
  plan_code?: string;
  用途別_code?: string;
  item_seq?: number;
  source_table?: string;
  科目名稱?: string;
  field?: string;
  page?: number;
  row?: number;
  col?: number;
}

export interface MemoItem {
  memo_id: string;
  year: number;
  scope: string;
  page: number | string;
  locator: string;
  field: string;
  type: MemoType | string;
  printed_text: string;
  data_text: string;
  suggested_text: string;
  note: string;
  pdf_file: string;
  pdf_page: number | string;
  verified_method: string;
  verified_on: string;
  evidence: string;
  status: string;
  target?: MemoTarget;
}

export interface MemosFile {
  years: Record<string, MemoItem[]>;
}

export const MEMO_TYPE_ORDER: readonly MemoType[] = [
  "print_typo",
  "print_inconsistent",
  "print_layout",
  "data_gap",
];

export const MEMO_TYPES: Record<string, string> = {
  print_typo: "原書錯字",
  print_inconsistent: "原書前後不一致",
  print_layout: "原書版面",
  data_gap: "資料缺口",
};

export const MEMO_STATUSES: Record<string, string> = {
  confirmed: "已對照原圖",
  pending_publisher: "待公所確認",
};

export const MEMO_SCOPES: Record<string, string> = {
  revenue_item: "歲入明細",
  expenditure_item: "歲出明細",
  plan: "工作計畫",
  summary: "總表",
  reference_cell: "參考表儲存格",
  page: "整頁",
};

let cachedMemos: MemosFile | null = null;
let inflightMemos: Promise<MemosFile> | null = null;

/** 載入 data/memos.json；成功後快取，失敗不快取以便重試 */
export async function fetchMemosFile(base = import.meta.env?.VITE_DATA_BASE ?? "data/"): Promise<MemosFile> {
  if (cachedMemos) return cachedMemos;
  if (!inflightMemos) {
    inflightMemos = fetch(`${base}memos.json`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`載入 memos.json 失敗（HTTP ${res.status}）`);
        }
        let parsed: unknown;
        try {
          parsed = await res.json();
        } catch {
          throw new Error("載入 memos.json 失敗（內容不是有效的 JSON）");
        }
        if (!parsed || typeof parsed !== "object" || !("years" in parsed)) {
          throw new Error("載入 memos.json 失敗（資料格式不符）");
        }
        cachedMemos = parsed as MemosFile;
        return cachedMemos;
      })
      .finally(() => {
        inflightMemos = null;
      });
  }
  return inflightMemos;
}

export function sortMemos(items: readonly MemoItem[]): MemoItem[] {
  return [...items].sort((a, b) => String(a.memo_id).localeCompare(String(b.memo_id)));
}

export function memoTypeLabel(type: string): string {
  return MEMO_TYPES[type] ?? type;
}

export function memoStatusLabel(status: string): string {
  return MEMO_STATUSES[status] ?? status;
}

export function memoScopeLabel(scope: string): string {
  return MEMO_SCOPES[scope] ?? (scope || "未標示");
}

/** 還原證據截圖的相對路徑（docs/evidence/... -> evidence/...），避免不安全路徑 */
export function resolveEvidenceSrc(evidence: string | undefined): string | null {
  const raw = String(evidence ?? "").trim();
  if (!raw || raw.includes("..")) return null;
  if (raw.startsWith("docs/evidence/")) return raw.slice("docs/".length);
  if (raw.startsWith("evidence/")) return raw;
  return null;
}

export function memoLocationText(m: MemoItem): string {
  const t = m.target ?? {};
  const fieldSuffix = m.field ? `（${m.field}）` : "";
  if (m.scope === "revenue_item") {
    return `歲入明細 ${t.code || m.locator}${t.item_seq ? ` 第 ${t.item_seq} 筆` : ""}${fieldSuffix}`;
  }
  if (m.scope === "expenditure_item") {
    return `歲出明細 ${t.plan_code || ""} / ${t.用途別_code || ""}${t.item_seq ? ` 第 ${t.item_seq} 筆` : ""}${fieldSuffix}`;
  }
  if (m.scope === "plan") {
    return `工作計畫 ${t.plan_code || m.locator}${fieldSuffix}`;
  }
  if (m.scope === "summary") {
    return `總表 ${t.source_table || ""} — ${t.科目名稱 || ""}${fieldSuffix}`;
  }
  if (m.scope === "reference_cell") {
    return `參考表 p${t.page ?? m.page} 第 ${t.row} 列第 ${t.col} 欄`;
  }
  if (m.scope === "page") {
    return `整頁 p${t.page ?? m.page}`;
  }
  return m.locator || `p${m.page}`;
}

function findNodeIdPath(nodes: readonly TreeNode[], targetId: string, trail: string[] = []): string[] | null {
  for (const node of nodes) {
    const next = [...trail, node.id];
    if (node.id === targetId) return next;
    if (node.children.length) {
      const found = findNodeIdPath(node.children, targetId, next);
      if (found) return found;
    }
  }
  return null;
}

/** 建立可連往對應頁面的路由目標（若無法對應則回傳 null） */
export function memoTargetRoute(
  year: number,
  m: MemoItem,
  yearData: YearData | null,
  hasReference: boolean,
): RouteLocationRaw | null {
  const t = m.target;
  if (!t || !year) return null;

  if (t.kind === "revenue" && t.code && yearData) {
    const roots = normalizeRevenue(yearData, null);
    const ids = findNodeIdPath(roots, `revenue:${t.code}`);
    const enc = ids ? encodePath(ids) : undefined;
    if (enc) return { path: `/${year}/歲入`, query: { path: enc } };
  }

  if (t.kind === "expenditure" && t.plan_code && yearData) {
    const roots = normalizeExpenditure(yearData, null, "政事別");
    const targetId = t.用途別_code ? `object:${t.plan_code}|${t.用途別_code}` : `plan:${t.plan_code}`;
    const ids = findNodeIdPath(roots, targetId) ?? findNodeIdPath(roots, `plan:${t.plan_code}`);
    const enc = ids ? encodePath(ids) : undefined;
    if (enc) return { path: `/${year}/歲出`, query: { view: "政事別", path: enc } };
  }

  if (t.kind === "plan" && t.plan_code && yearData) {
    const roots = normalizeExpenditure(yearData, null, "政事別");
    const ids = findNodeIdPath(roots, `plan:${t.plan_code}`);
    const enc = ids ? encodePath(ids) : undefined;
    if (enc) return { path: `/${year}/歲出`, query: { view: "政事別", path: enc } };
  }

  if (t.kind === "summary" && t.科目名稱) {
    return { path: `/${year}/搜尋`, query: { q: t.科目名稱 } };
  }

  if ((t.kind === "reference" || t.kind === "page") && hasReference) {
    const pg = t.page ?? m.page;
    return { path: `/${year}/參考表`, query: pg !== undefined && pg !== "" ? { p: String(pg) } : {} };
  }

  return null;
}
