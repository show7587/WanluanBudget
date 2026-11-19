import MiniSearch from "minisearch";
import { normalizeExpenditure, normalizeRevenue } from "@/data/normalize";
import type { TreeNode, YearData } from "@/data/types";
import { encodePath } from "@/utils/query";

export type SearchDocKind = "revenue" | "expenditure" | "plan" | "summary";

export type SearchKindFilter = "all" | "歲入" | "歲出" | "總表";

export interface SearchDoc {
  id: string;
  year: number;
  kind: SearchDocKind;
  code: string;
  name: string;
  text: string;
  page?: number | null;
  page_start?: number | null;
  page_end?: number | null;
  amount_元?: number | null;
  dept?: string;
  unresolved?: boolean;
  用途別_code?: string;
  alias?: string;
}

export interface SearchHit extends SearchDoc {
  score: number;
  terms: string[];
}

export interface MemoItem {
  memo_id?: string;
  type?: string;
  suggested_text?: string;
  target?: {
    search_id?: string;
  };
}

export interface MemosFile {
  years?: Record<string, MemoItem[]>;
}

export interface HighlightSegment {
  text: string;
  hit: boolean;
}

export interface YearPathLookup {
  revenue: Map<string, string[]>;
  expenditure: Map<string, string[]>;
}

export interface SearchLinkTarget {
  to: { path: string; query?: Record<string, string> };
  label: string;
}

export const KIND_FILTERS: readonly { key: SearchKindFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "歲入", label: "歲入" },
  { key: "歲出", label: "歲出" },
  { key: "總表", label: "總表" },
];

export const KIND_LABELS: Record<SearchDocKind, string> = {
  revenue: "歲入明細",
  expenditure: "歲出明細",
  plan: "歲出・工作計畫",
  summary: "總表",
};

/**
 * 中文分詞沿用舊版 site/app.js：
 * CJK 以單字 + 相鄰雙字組索引，英數字照一般詞切。
 */
export function tokenize(text: string): string[] {
  const out: string[] = [];
  for (const m of String(text ?? "").toLowerCase().matchAll(/[\u3400-\u9fff]+|[a-z0-9]+/g)) {
    const w = m[0];
    if (/^[a-z0-9]+$/.test(w)) {
      out.push(w);
      continue;
    }
    for (let i = 0; i < w.length; i++) {
      out.push(w[i]);
      if (i + 1 < w.length) out.push(w.slice(i, i + 2));
    }
  }
  return out;
}

/** 將 memos.json 中 print_typo 的 suggested_text 併入對應搜尋文件的 alias 欄位（不修改原陣列） */
export function mergeMemoAliases(docs: SearchDoc[], memos: MemosFile | MemoItem[] | null): SearchDoc[] {
  if (!Array.isArray(docs)) return [];
  const list: MemoItem[] = Array.isArray(memos)
    ? memos
    : memos && memos.years
      ? Object.values(memos.years).flat()
      : [];
  const aliasById = new Map<string, string>();
  for (const m of list) {
    if (!m || m.type !== "print_typo" || !m.suggested_text) continue;
    const sid = m.target?.search_id;
    if (!sid) continue;
    const prev = aliasById.get(sid);
    aliasById.set(sid, prev ? `${prev} ${m.suggested_text}` : m.suggested_text);
  }
  if (!aliasById.size) return docs.slice();
  return docs.map((doc) => {
    const alias = aliasById.get(doc.id);
    return alias ? { ...doc, alias } : doc;
  });
}

/** 將 URL query 的 kind 參數正規化為篩選鍵（同時相容舊版英文參數） */
export function normalizeKindFilter(raw: string | undefined): SearchKindFilter {
  if (!raw) return "all";
  switch (raw.trim()) {
    case "歲入":
    case "revenue":
      return "歲入";
    case "歲出":
    case "expenditure":
    case "plan":
      return "歲出";
    case "總表":
    case "summary":
      return "總表";
    default:
      return "all";
  }
}

export function matchesKindFilter(docKind: SearchDocKind, filter: SearchKindFilter): boolean {
  if (filter === "all") return true;
  if (filter === "歲入") return docKind === "revenue";
  if (filter === "歲出") return docKind === "expenditure" || docKind === "plan";
  if (filter === "總表") return docKind === "summary";
  return true;
}

/** 格式化預算書頁碼（沿用舊版 pageText 規則） */
export function formatPage(doc: Pick<SearchDoc, "page" | "page_start" | "page_end">): string {
  const s = doc.page_start ?? doc.page;
  const e = doc.page_end ?? doc.page;
  if (s === undefined || s === null) return "";
  return s === e || e === undefined || e === null ? `p${s}` : `p${s}–${e}`;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 從查詢字串抽出可用於標示的詞彙（長詞優先；若整詞未命中再退回雙字組／單字） */
export function extractHighlightTerms(query: string): string[] {
  const raw = Array.from(String(query ?? "").matchAll(/[\u3400-\u9fff]+|[a-z0-9]+/gi), (m) => m[0]);
  const uniq = Array.from(new Set(raw.filter(Boolean)));
  uniq.sort((a, b) => b.length - a.length);
  return uniq;
}

function findEffectivePatterns(text: string, query: string): string[] {
  const fullTerms = extractHighlightTerms(query);
  if (!fullTerms.length) return [];

  const lower = text.toLowerCase();
  const matched: string[] = [];
  for (const term of fullTerms) {
    if (lower.includes(term.toLowerCase())) {
      matched.push(term);
      continue;
    }
    // 中文多字查詢若只命中部分詞組，退回雙字組與單字以利標示
    if (/^[\u3400-\u9fff]+$/.test(term) && term.length > 1) {
      let foundBigram = false;
      for (let i = 0; i + 1 < term.length; i++) {
        const bi = term.slice(i, i + 2);
        if (lower.includes(bi)) {
          matched.push(bi);
          foundBigram = true;
        }
      }
      if (!foundBigram) {
        for (const ch of term) {
          if (lower.includes(ch)) matched.push(ch);
        }
      }
    }
  }
  const uniq = Array.from(new Set(matched));
  uniq.sort((a, b) => b.length - a.length);
  return uniq;
}

/** 擷取包含第一個命中詞的說明片段 */
export function buildSnippet(text: string, query: string, maxLen = 160): string {
  const src = String(text ?? "").trim();
  if (!src || src.length <= maxLen) return src;

  const patterns = findEffectivePatterns(src, query);
  let firstIdx = -1;
  if (patterns.length) {
    const lower = src.toLowerCase();
    for (const p of patterns) {
      const idx = lower.indexOf(p.toLowerCase());
      if (idx !== -1 && (firstIdx === -1 || idx < firstIdx)) firstIdx = idx;
    }
  }

  if (firstIdx === -1 || firstIdx < maxLen * 0.6) {
    return `${src.slice(0, maxLen).trimEnd()}…`;
  }

  const start = Math.max(0, firstIdx - Math.floor(maxLen * 0.35));
  const end = Math.min(src.length, start + maxLen);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < src.length ? "…" : "";
  return `${prefix}${src.slice(start, end).trim()}${suffix}`;
}

/** 將文字切分為普通片段與命中片段，供 Vue 以 <mark> 安全渲染（不使用 v-html） */
export function highlightSegments(text: string, query: string): HighlightSegment[] {
  const src = String(text ?? "");
  if (!src) return [];
  const patterns = findEffectivePatterns(src, query);
  if (!patterns.length) return [{ text: src, hit: false }];

  const re = new RegExp(`(${patterns.map(escapeRegExp).join("|")})`, "gi");
  const out: HighlightSegment[] = [];
  let lastIndex = 0;
  for (const m of src.matchAll(re)) {
    const idx = m.index ?? 0;
    if (idx > lastIndex) out.push({ text: src.slice(lastIndex, idx), hit: false });
    if (m[0]) out.push({ text: m[0], hit: true });
    lastIndex = idx + m[0].length;
  }
  if (lastIndex < src.length) out.push({ text: src.slice(lastIndex), hit: false });
  return out;
}

/** 針對單一年度建立「節點 id → 完整 drill-down 路徑」對照表（供 DrillExplorer 精準展開） */
export function buildPathLookup(yearData: YearData): YearPathLookup {
  const revenue = new Map<string, string[]>();
  const expenditure = new Map<string, string[]>();

  const walk = (nodes: TreeNode[], target: Map<string, string[]>, trail: string[]) => {
    for (const n of nodes) {
      const here = [...trail, n.id];
      // 葉節點（children 為空）若直接 drill 會顯示空清單，故導向其父層讓該項目顯示在畫面中
      const navTrail = n.children.length > 0 ? here : trail;
      if (!target.has(n.id)) target.set(n.id, navTrail);
      if (n.children.length > 0) walk(n.children, target, here);
    }
  };

  walk(normalizeRevenue(yearData, null), revenue, []);
  walk(normalizeExpenditure(yearData, null, "政事別"), expenditure, []);

  return { revenue, expenditure };
}

/** 建立連到對應歲入／歲出／總覽頁的 router-link 目標 */
export function resolveHitLink(hit: SearchDoc, lookup?: YearPathLookup): SearchLinkTarget | null {
  if (hit.kind === "revenue") {
    const targetId = `revenue:${hit.code}`;
    const trail = lookup?.revenue.get(targetId);
    const enc = trail ? encodePath(trail) : hit.code ? targetId : undefined;
    return {
      to: { path: `/${hit.year}/歲入`, ...(enc ? { query: { path: enc } } : {}) },
      label: "前往歲入頁",
    };
  }
  if (hit.kind === "plan" || hit.kind === "expenditure") {
    const targetId =
      hit.kind === "expenditure" && hit.用途別_code
        ? `object:${hit.code}|${hit.用途別_code}`
        : `plan:${hit.code}`;
    const trail = lookup?.expenditure.get(targetId) ?? lookup?.expenditure.get(`plan:${hit.code}`);
    const enc = trail ? encodePath(trail) : hit.code ? `plan:${hit.code}` : undefined;
    return {
      to: {
        path: `/${hit.year}/歲出`,
        query: { view: "政事別", ...(enc ? { path: enc } : {}) },
      },
      label: "前往歲出頁",
    };
  }
  if (hit.kind === "summary") {
    return {
      to: { path: `/${hit.year}/總覽` },
      label: "前往總覽頁",
    };
  }
  return null;
}

export interface SearchEngine {
  search: (query: string) => SearchHit[];
  years: number[];
  totalDocs: number;
}

export function createSearchEngine(docs: SearchDoc[], memos: MemosFile | MemoItem[] | null = null): SearchEngine {
  const indexedDocs = mergeMemoAliases(docs, memos);
  const ms = new MiniSearch<SearchDoc>({
    fields: ["name", "text", "code", "dept", "alias"],
    storeFields: [
      "id",
      "kind",
      "year",
      "code",
      "name",
      "text",
      "page",
      "page_start",
      "page_end",
      "amount_元",
      "dept",
      "unresolved",
      "用途別_code",
    ],
    tokenize,
    searchOptions: {
      tokenize,
      combineWith: "AND",
      boost: { name: 2 },
    },
  });
  ms.addAll(indexedDocs);

  const years = Array.from(new Set(indexedDocs.map((d) => Number(d.year)).filter(Boolean))).sort((a, b) => b - a);

  return {
    search(query: string): SearchHit[] {
      const q = query.trim();
      if (!q) return [];
      return ms.search(q) as unknown as SearchHit[];
    },
    years,
    totalDocs: indexedDocs.length,
  };
}

let cachedEngine: Promise<SearchEngine> | null = null;

async function fetchJson<T>(url: string, optional = false): Promise<T | null> {
  const r = await fetch(url);
  if (!r.ok) {
    if (optional && r.status === 404) return null;
    throw new Error(`載入 ${url} 失敗（HTTP ${r.status}）`);
  }
  try {
    return (await r.json()) as T;
  } catch {
    if (optional) return null;
    throw new Error(`載入 ${url} 失敗（內容不是有效的 JSON）`);
  }
}

/** 載入並快取 MiniSearch 搜尋引擎；失敗時清除快取以便重試，memos.json 失敗則優雅降級 */
export function loadSearchEngine(base = import.meta.env?.VITE_DATA_BASE ?? "data/"): Promise<SearchEngine> {
  if (!cachedEngine) {
    cachedEngine = Promise.all([
      fetchJson<SearchDoc[]>(`${base}search.json`, false),
      fetchJson<MemosFile>(`${base}memos.json`, true).catch(() => null),
    ])
      .then(([docs, memos]) => {
        if (!Array.isArray(docs)) {
          throw new Error("搜尋索引格式不正確（預期為陣列）");
        }
        return createSearchEngine(docs, memos);
      })
      .catch((err) => {
        cachedEngine = null;
        throw err;
      });
  }
  return cachedEngine;
}
