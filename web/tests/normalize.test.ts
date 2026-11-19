import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { CompareData, ExpenditureView, TreeNode, YearData } from "../src/data/types";
import { computeDiff, flatten, normalizeExpenditure, normalizeRevenue, sumAmount } from "../src/data/normalize";
import { diffBandKey } from "../src/data/diffScale";
import { fmtCompact, fmtInt, fmtPct, fmtSignedPct } from "../src/data/format";

const dir = resolve(__dirname, "../../site/data");
const load = <T>(f: string): T => JSON.parse(readFileSync(resolve(dir, f), "utf8")) as T;
const year = (y: number) => load<YearData>(`${y}.json`);
const compare = (from: number, to: number) => load<CompareData>(`compare_${from}_${to}.json`);

const VIEWS: ExpenditureView[] = ["政事別", "機關別", "用途別"];

describe("總額與 overview 一致", () => {
  for (const y of [114, 115, 116]) {
    const data = year(y);
    it(`${y} 歲入`, () => {
      expect(sumAmount(normalizeRevenue(data, null))).toBe(data.overview.revenue_total_元);
    });
    for (const v of VIEWS) {
      it(`${y} 歲出（${v}）`, () => {
        expect(sumAmount(normalizeExpenditure(data, null, v))).toBe(data.overview.expenditure_total_元);
      });
    }
  }

  it("116 金額為 312,678,000／321,081,000 元", () => {
    const d = year(116);
    expect(sumAmount(normalizeRevenue(d, null))).toBe(312_678_000);
    expect(sumAmount(normalizeExpenditure(d, null, "政事別"))).toBe(321_081_000);
  });
});

describe("階層加總", () => {
  const walk = (nodes: TreeNode[], fn: (n: TreeNode) => void) =>
    nodes.forEach((n) => {
      fn(n);
      walk(n.children, fn);
    });

  for (const v of VIEWS) {
    it(`歲出（${v}）：有子節點者，子節點加總＝父節點`, () => {
      walk(normalizeExpenditure(year(116), compare(115, 116), v), (n) => {
        if (n.children.length) expect(sumAmount(n.children), `${n.level} ${n.name}`).toBe(n.amount);
      });
    });
  }

  it("歲入：款／項層子節點加總＝父節點", () => {
    walk(normalizeRevenue(year(116), compare(115, 116)), (n) => {
      if (n.children.length) expect(sumAmount(n.children), `${n.level} ${n.name}`).toBe(n.amount);
    });
  });

  it("節點 id 在同一父節點下不重複", () => {
    for (const v of VIEWS) {
      walk(normalizeExpenditure(year(116), compare(115, 116), v), (n) => {
        const ids = n.children.map((c) => c.id);
        expect(new Set(ids).size, `${n.name} 的子節點 id 重複`).toBe(ids.length);
      });
    }
  });
});

describe("增減", () => {
  it("computeDiff 基本情形", () => {
    expect(computeDiff(110, 100)).toMatchObject({ diff: 10, pct: 10, status: "up" });
    expect(computeDiff(90, 100)).toMatchObject({ diff: -10, pct: -10, status: "down" });
    expect(computeDiff(100, 100)).toMatchObject({ diff: 0, pct: 0, status: "flat" });
    expect(computeDiff(100, 0)).toMatchObject({ status: "new", pct: null });
    expect(computeDiff(5, null, true)).toMatchObject({ prev: 0, status: "new" });
    expect(computeDiff(5, null)).toMatchObject({ prev: null, status: "unknown" });
    expect(computeDiff(0, 0)).toMatchObject({ status: "flat", pct: 0 });
  });

  it("工作計畫的 pct 與 compare.json 一致（四捨五入至 2 位）", () => {
    const cmp = compare(115, 116);
    const tree = normalizeExpenditure(year(116), cmp, "機關別");
    const plans = flatten(tree).filter((r) => r.level === "工作計畫");
    expect(plans.length).toBe(49);
    let checked = 0;
    for (const e of Object.values(cmp.entries)) {
      if (e.kind !== "plan" || e.status !== "both" || e.pct == null) continue;
      const row = plans.find((r) => r.name === e.display_name && r.amount === e.amount_元["116"]);
      if (!row) continue;
      expect(row.pct).toBeCloseTo(e.pct, 2);
      checked++;
    }
    expect(checked).toBeGreaterThan(30);
  });

  it("114 沒有比較資料時，款／項仍使用書上的上年度數字", () => {
    const rev = normalizeRevenue(year(114), null);
    expect(rev[0].prev).not.toBeNull();
    expect(rev[0].status).not.toBe("unknown");
  });

  it("色階邊界", () => {
    expect(diffBandKey("up", 4.99)).toBe("up0");
    expect(diffBandKey("up", 5)).toBe("up1");
    expect(diffBandKey("up", 25)).toBe("up5");
    expect(diffBandKey("down", -25.01)).toBe("down5");
    expect(diffBandKey("flat", 0)).toBe("flat");
    expect(diffBandKey("new", null)).toBe("new");
    expect(diffBandKey("unknown", null)).toBe("unknown");
  });
});

describe("格式", () => {
  it("千分位與百分比", () => {
    expect(fmtInt(312678000)).toBe("312,678,000");
    expect(fmtPct(9.2)).toBe("9.20%");
    expect(fmtSignedPct(9.27)).toBe("+9.27%");
    expect(fmtSignedPct(-3.1)).toBe("-3.10%");
    expect(fmtPct(null)).toBe("—");
    expect(fmtCompact(312678000)).toBe("3.13 億元");
    expect(fmtCompact(25000)).toBe("2.5 萬元");
  });
});
