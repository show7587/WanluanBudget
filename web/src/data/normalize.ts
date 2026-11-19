import type {
  CompareData,
  CompareEntry,
  DiffStatus,
  ExpenditureView,
  RawNode,
  TreeNode,
  YearData,
} from "./types";

const round2 = (n: number): number => Math.round(n * 100) / 100;

/** 依本年度與上年度算出增減；isNew 表示比較資料標示只有本年度才有 */
export function computeDiff(
  amount: number,
  prev: number | null,
  isNew = false,
): Pick<TreeNode, "prev" | "diff" | "pct" | "status"> {
  if (isNew) return { prev: 0, diff: amount, pct: null, status: "new" };
  if (prev == null) return { prev: null, diff: null, pct: null, status: "unknown" };
  if (prev === 0) {
    return amount === 0
      ? { prev, diff: 0, pct: 0, status: "flat" }
      : { prev, diff: amount, pct: null, status: "new" };
  }
  const diff = amount - prev;
  const pct = round2((diff / prev) * 100);
  const status: DiffStatus = diff === 0 ? "flat" : diff > 0 ? "up" : "down";
  return { prev, diff, pct, status };
}

interface Ctx {
  compare: CompareData | null;
}

function entryPrev(entry: CompareEntry | undefined, ctx: Ctx): { prev: number | null; isNew: boolean } {
  if (!entry || !ctx.compare) return { prev: null, isNew: false };
  const from = String(ctx.compare.from_year);
  const to = String(ctx.compare.to_year);
  const hasPrev = entry.amount_元[from] !== undefined;
  const hasCur = entry.amount_元[to] !== undefined;
  if (hasCur && !hasPrev) return { prev: null, isNew: true };
  return { prev: hasPrev ? entry.amount_元[from] : null, isNew: false };
}

function make(
  base: Pick<TreeNode, "id" | "name" | "level" | "amount"> & Partial<TreeNode>,
  prev: number | null,
  isNew: boolean,
  children: TreeNode[],
): TreeNode {
  return { ...base, ...computeDiff(base.amount, prev, isNew), children };
}

/** 父節點沒有自己的上年度數字時，由子節點加總；任一子節點未知就整體未知（不猜） */
function aggregatePrev(children: TreeNode[]): number | null {
  if (!children.length) return null;
  let sum = 0;
  for (const c of children) {
    if (c.prev == null) return null;
    sum += c.prev;
  }
  return sum;
}

const isDetail = (n: RawNode): boolean => n.level === "明細";

function revenueNode(raw: RawNode, ctx: Ctx): TreeNode {
  const code = String(raw.code ?? "");
  const children = (raw.children ?? []).filter((c) => !isDetail(c)).map((c) => revenueNode(c, ctx));
  const amount = raw.amount_元 ?? 0;
  const entry = ctx.compare?.entries[`revenue:${code}`];
  let prev: number | null = null;
  let isNew = false;
  if (typeof raw.上年度_元 === "number") prev = raw.上年度_元;
  else {
    ({ prev, isNew } = entryPrev(entry, ctx));
    if (prev == null && !isNew) prev = aggregatePrev(children);
  }
  return make(
    { id: `revenue:${code}`, name: raw.name ?? code, level: raw.level ?? "", code, dept: raw.dept, amount, page: raw.page },
    prev,
    isNew,
    children,
  );
}

export function normalizeRevenue(data: YearData, compare: CompareData | null): TreeNode[] {
  const ctx: Ctx = { compare };
  return data.revenue.hierarchy.map((n) => revenueNode(n, ctx));
}

/** 政事別 → 機關 → 工作計畫 → 用途別（原階層，丟掉「明細」層） */
function expenditureNode(raw: RawNode, ctx: Ctx, trail: string): TreeNode {
  const level = raw.level ?? "";
  const code = String(raw.code ?? "");
  const amount = raw.amount_元 ?? 0;
  const name = raw.name ?? raw.dept ?? code;
  const children = (raw.children ?? [])
    .filter((c) => !isDetail(c))
    .map((c) => expenditureNode(c, ctx, level === "工作計畫" ? code : trail));
  let id: string;
  let entry: CompareEntry | undefined;
  if (level === "工作計畫") {
    id = `plan:${code}`;
    entry = ctx.compare?.entries[id];
  } else if (level === "用途別") {
    id = `object:${trail}|${code}`;
    entry = ctx.compare?.entries[id];
  } else if (level === "機關") {
    id = `dept:${raw.dept ?? name}|${trail}`;
  } else {
    id = `${level}:${code || name}`;
  }
  let prev: number | null = null;
  let isNew = false;
  if (typeof raw.上年度_元 === "number") prev = raw.上年度_元;
  else if (entry) ({ prev, isNew } = entryPrev(entry, ctx));
  else prev = aggregatePrev(children);
  return make({ id, name, level, code: code || undefined, dept: raw.dept, amount, page: raw.page }, prev, isNew, children);
}

function aggregate(id: string, name: string, level: string, children: TreeNode[]): TreeNode {
  const amount = children.reduce((s, c) => s + c.amount, 0);
  return make({ id, name, level, amount }, aggregatePrev(children), false, children);
}

/** 用途別大類：以用途別代碼第 1 碼分類（1 人事費、2 業務費、3 設備及投資、4 獎補助費、6 預備金）。
 *  這只是名稱分類，不是經常／資本拆分。 */
export const USE_CLASS_NAMES: Record<string, string> = {
  "1": "人事費",
  "2": "業務費",
  "3": "設備及投資",
  "4": "獎補助費",
  "5": "債務費",
  "6": "預備金",
};

export function normalizeExpenditure(
  data: YearData,
  compare: CompareData | null,
  view: ExpenditureView,
): TreeNode[] {
  const ctx: Ctx = { compare };
  const byFunction = data.expenditure.hierarchy.map((n) => expenditureNode(n, ctx, ""));
  if (view === "政事別") return byFunction;

  // 取出所有工作計畫節點（附上原本的機關）
  const plans: TreeNode[] = [];
  const collect = (n: TreeNode): void => {
    if (n.level === "工作計畫") plans.push(n);
    else n.children.forEach(collect);
  };
  byFunction.forEach(collect);

  if (view === "機關別") {
    const groups = new Map<string, TreeNode[]>();
    for (const p of plans) {
      const dept = p.dept ?? "（未標示機關）";
      (groups.get(dept) ?? groups.set(dept, []).get(dept)!).push(p);
    }
    return [...groups.entries()]
      .map(([dept, ps]) => aggregate(`agency:${dept}`, dept, "機關", ps))
      .sort((a, b) => b.amount - a.amount);
  }

  // 用途別：大類 → 用途別（跨計畫彙總）→ 工作計畫
  const uses = new Map<string, { name: string; parts: TreeNode[] }>();
  for (const p of plans) {
    for (const u of p.children) {
      const key = u.code ?? u.name;
      const slot = uses.get(key) ?? uses.set(key, { name: u.name, parts: [] }).get(key)!;
      slot.parts.push({ ...u, id: `use:${key}|${p.code}`, name: p.name, level: "工作計畫", dept: p.dept, children: [] });
    }
  }
  const classes = new Map<string, TreeNode[]>();
  for (const [code, { name, parts }] of uses) {
    const node = aggregate(`use:${code}`, name, "用途別", parts.sort((a, b) => b.amount - a.amount));
    node.code = code;
    const cls = code.slice(0, 1);
    (classes.get(cls) ?? classes.set(cls, []).get(cls)!).push(node);
  }
  return [...classes.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([cls, nodes]) =>
      aggregate(`useclass:${cls}`, USE_CLASS_NAMES[cls] ?? `用途別 ${cls}xxx`, "用途別大類", nodes.sort((a, b) => b.amount - a.amount)),
    );
}

export const sumAmount = (nodes: TreeNode[]): number => nodes.reduce((s, n) => s + n.amount, 0);

/** 沿 id 路徑找節點；找不到回傳 null */
export function findByPath(roots: TreeNode[], ids: string[]): { node: TreeNode | null; trail: TreeNode[] } {
  let level = roots;
  const trail: TreeNode[] = [];
  let node: TreeNode | null = null;
  for (const id of ids) {
    node = level.find((n) => n.id === id) ?? null;
    if (!node) return { node: null, trail };
    trail.push(node);
    level = node.children;
  }
  return { node, trail };
}

/** 攤平成表格列（供 DataTable 與匯出使用） */
export interface FlatRow {
  path: string[];
  name: string;
  level: string;
  amount: number;
  prev: number | null;
  diff: number | null;
  pct: number | null;
  status: DiffStatus;
}
export function flatten(nodes: TreeNode[], parentPath: string[] = []): FlatRow[] {
  return nodes.flatMap((n) => {
    const path = [...parentPath, n.name];
    return [
      { path, name: n.name, level: n.level, amount: n.amount, prev: n.prev, diff: n.diff, pct: n.pct, status: n.status },
      ...flatten(n.children, path),
    ];
  });
}
