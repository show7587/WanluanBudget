/** 圖表元件只吃這份正規化結構；金額一律是「元」。 */
export type DiffStatus = "up" | "down" | "flat" | "new" | "removed" | "unknown";

export interface TreeNode {
  id: string;
  name: string;
  level: string;
  code?: string;
  dept?: string;
  amount: number;
  /** 上年度金額；沒有可比資料時為 null */
  prev: number | null;
  /** amount - prev；prev 為 null 時為 null */
  diff: number | null;
  /** 增減百分比（小數 2 位以內）；prev 為 0 或 null 時為 null */
  pct: number | null;
  status: DiffStatus;
  /** 預算書頁碼（若有） */
  page?: number;
  children: TreeNode[];
}

/** 來自 site/data/<年>.json 的原始階層節點（只列用到的欄位） */
export interface RawNode {
  level?: string;
  code?: string;
  name?: string;
  dept?: string;
  amount_元?: number;
  上年度_元?: number;
  page?: number;
  用途別_code?: string;
  children?: RawNode[];
  [k: string]: unknown;
}

export interface YearData {
  year: number;
  overview: {
    revenue_total_元: number;
    expenditure_total_元: number;
    balance_元: number;
    prior_surplus_used_元: number;
    current_account: { revenue_元: number; expenditure_元: number; surplus_元: number };
    capital_account: { revenue_元: number; expenditure_元: number; shortfall_元: number };
  };
  revenue: { total_元: number; hierarchy: RawNode[] };
  expenditure: { total_元: number; hierarchy: RawNode[] };
  summary_tables: Record<string, Array<Record<string, unknown>>>;
}

export interface CompareEntry {
  key: string;
  kind: "revenue" | "plan" | "object";
  level: string;
  code: string;
  display_name: string;
  amount_元: Record<string, number>;
  diff_元: number | null;
  pct: number | null;
  status: "both" | string;
}

export interface CompareData {
  years: number[];
  from_year: number;
  to_year: number;
  entries: Record<string, CompareEntry>;
}

export interface IndexData {
  years: number[];
  default_year: number;
  year_summaries: Array<{ year: number; revenue_total_元: number; expenditure_total_元: number }>;
  reference_years: number[];
  memo_years: number[];
}

export type ExpenditureView = "政事別" | "機關別" | "用途別";
