import { describe, expect, it, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { SeriesData, SeriesDerived } from "../src/data/types";
import { createHttpSource } from "../src/data/source";
import {
  buildPickerTree,
  buildTrendRoute,
  computeSeriesDerived,
  encodeTrendItemsParam,
  formatSeriesItemLabel,
  MAX_TREND_ITEMS,
  parseTrendItemsParam,
  resolveSeriesKey,
  resolveYearRawKey,
  searchSeriesItems,
  toTrendExportRows,
  trendRowsToCsv,
  trendRowsToJson,
} from "../src/views/trend/trendModel";
import { resolveHitTrendKey, type SearchDoc } from "../src/views/search/searchModel";

const fixtureDir = resolve(__dirname, "../../tests/fixtures");
const sample = JSON.parse(readFileSync(resolve(fixtureDir, "series_sample.json"), "utf8")) as SeriesData;
const expected = JSON.parse(readFileSync(resolve(fixtureDir, "series_expected.json"), "utf8")) as {
  items: Record<string, SeriesDerived>;
};

describe("computeSeriesDerived 與 S0 fixture 期望值完全一致", () => {
  const sampleKeys = Object.keys(sample.items);
  const expectedKeys = Object.keys(expected.items);

  it("fixture 項目集合與期望值完全一致", () => {
    expect(new Set(sampleKeys)).toEqual(new Set(expectedKeys));
  });

  for (const key of sampleKeys) {
    it(`項目 ${key}`, () => {
      const actual = computeSeriesDerived(sample.items[key], sample.years);
      expect(actual).toEqual(expected.items[key]);
    });
  }
});

describe("resolveSeriesKey 與 aliases 解析順序（契約 §3）", () => {
  it("先查 aliases，避免 114:revenue:04-02 誤命中 revenue:04-02", () => {
    expect(resolveSeriesKey(sample, "114:revenue:04-02")).toBe("revenue:04-02@114");
    expect(resolveYearRawKey(sample, 114, "revenue:04-02")).toBe("revenue:04-02@114");
  });

  it("114 改碼項目 04-03 解析為 canonical key revenue:04-02", () => {
    expect(resolveSeriesKey(sample, "114:revenue:04-03")).toBe("revenue:04-02");
  });

  it("115/116 原碼不在 aliases 時，去掉年度前綴直接命中 items", () => {
    expect(resolveSeriesKey(sample, "115:revenue:04-02")).toBe("revenue:04-02");
    expect(resolveSeriesKey(sample, "116:revenue:04-02")).toBe("revenue:04-02");
    expect(resolveSeriesKey(sample, "114:revenue:04")).toBe("revenue:04");
    expect(resolveSeriesKey(sample, "114:plan:51120019101")).toBe("plan:51120019101");
    expect(resolveSeriesKey(sample, "116:object:51120019101|3035")).toBe("object:51120019101|3035");
  });

  it("鏈式改碼（114:99-01 與 115:99-02）皆解析至 revenue:99-03", () => {
    expect(resolveSeriesKey(sample, "114:revenue:99-01")).toBe("revenue:99-03");
    expect(resolveSeriesKey(sample, "115:revenue:99-02")).toBe("revenue:99-03");
    expect(resolveSeriesKey(sample, "116:revenue:99-03")).toBe("revenue:99-03");
  });

  it("直接給 canonical key（含 @<年> 後綴）也能解析", () => {
    expect(resolveSeriesKey(sample, "revenue:04-02")).toBe("revenue:04-02");
    expect(resolveSeriesKey(sample, "revenue:04-02@114")).toBe("revenue:04-02@114");
    expect(resolveSeriesKey(sample, "object:51120019101|3010")).toBe("object:51120019101|3010");
  });

  it("未知 key、空白與原型屬性回傳 null", () => {
    expect(resolveSeriesKey(sample, "")).toBeNull();
    expect(resolveSeriesKey(sample, "   ")).toBeNull();
    expect(resolveSeriesKey(sample, "114:revenue:does-not-exist")).toBeNull();
    expect(resolveSeriesKey(sample, "toString")).toBeNull();
    expect(resolveSeriesKey(sample, "constructor")).toBeNull();
  });
});

describe("parseTrendItemsParam（URL 參數過濾與提示）", () => {
  it("解析 canonical 與 <年>:<原始key> 混用，並維持順序（第一個為主項目）", () => {
    const parsed = parseTrendItemsParam(sample, "114:revenue:04-03;114:revenue:04-02;plan:51120019101");
    expect(parsed.keys).toEqual(["revenue:04-02", "revenue:04-02@114", "plan:51120019101"]);
    expect(parsed.notices).toEqual([]);
  });

  it("過濾未知 key 並給出提示", () => {
    const parsed = parseTrendItemsParam(sample, "revenue:04;bogus:999;114:revenue:nope");
    expect(parsed.keys).toEqual(["revenue:04"]);
    expect(parsed.droppedUnknown).toEqual(["bogus:999", "114:revenue:nope"]);
    expect(parsed.notices.length).toBe(1);
  });

  it("同一個 canonical key 透過 alias 與原碼重複指定時會去重並提示", () => {
    const parsed = parseTrendItemsParam(sample, "114:revenue:04-03;revenue:04-02;115:revenue:04-02");
    expect(parsed.keys).toEqual(["revenue:04-02"]);
    expect(parsed.droppedDuplicate).toEqual(["revenue:04-02", "115:revenue:04-02"]);
    expect(parsed.notices.length).toBe(1);
  });

  it(`超過 ${MAX_TREND_ITEMS} 個項目時截斷並提示`, () => {
    const allKeys = Object.keys(sample.items).slice(0, 10);
    const parsed = parseTrendItemsParam(sample, allKeys.join(";"));
    expect(parsed.keys.length).toBe(MAX_TREND_ITEMS);
    expect(parsed.keys).toEqual(allKeys.slice(0, MAX_TREND_ITEMS));
    expect(parsed.droppedOverflow).toEqual(allKeys.slice(MAX_TREND_ITEMS));
    expect(parsed.notices.some((n) => n.includes(String(MAX_TREND_ITEMS)))).toBe(true);
  });

  it("encodeTrendItemsParam 與 buildTrendRoute", () => {
    expect(encodeTrendItemsParam([])).toBeUndefined();
    expect(encodeTrendItemsParam(["revenue:04", "plan:51120019101"])).toBe("revenue:04;plan:51120019101");
    expect(buildTrendRoute(116, "114:revenue:04-02")).toEqual({
      path: "/116/趨勢",
      query: { items: "114:revenue:04-02" },
    });
  });
});

describe("搜尋、階層挑選與匯出", () => {
  it("searchSeriesItems 可搜到改名項目的舊名與 @114 項目", () => {
    const byOldName = searchSeriesItems(sample, "合成舊名");
    expect(byOldName.map((o) => o.key)).toEqual(["revenue:99-10"]);

    const byAt = searchSeriesItems(sample, "04-02@114");
    expect(byAt.map((o) => o.key)).toEqual(["revenue:04-02@114"]);
  });

  it("buildPickerTree 收錄所有 fixture 項目且不遺漏 @114 與孤立細目", () => {
    const tree = buildPickerTree(sample);
    const collected = new Set<string>();
    const walk = (nodes: typeof tree.revenue) => {
      for (const n of nodes) {
        if (n.key) collected.add(n.key);
        walk(n.children);
      }
    };
    walk(tree.revenue);
    walk(tree.expenditure);
    expect(collected).toEqual(new Set(Object.keys(sample.items)));
  });

  it("formatSeriesItemLabel 區分 @114 項目與一般項目", () => {
    expect(formatSeriesItemLabel("revenue:04-02@114", sample.items["revenue:04-02@114"], sample.items)).toBe(
      "財產售價（04-02@114）",
    );
    expect(formatSeriesItemLabel("revenue:04-02", sample.items["revenue:04-02"], sample.items)).toBe("廢舊物資售價");
  });

  it("toTrendExportRows / CSV / JSON 輸出正確欄位與數值", () => {
    const rows = toTrendExportRows(sample, ["revenue:04", "revenue:09120010101"]);
    expect(rows.length).toBe(2);
    expect(rows[0].role).toBe("主項目");
    expect(rows[1].role).toBe("比較對象");
    expect(rows[1].amount_元["115"]).toBeNull();
    expect(rows[1].diff_元["116"]).toBeNull();

    const csv = trendRowsToCsv(rows, sample.years);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv).toContain("114金額(元)");
    expect(csv).toContain("財產收入");

    const parsedJson = JSON.parse(trendRowsToJson(rows)) as typeof rows;
    expect(parsedJson[0].key).toBe("revenue:04");
    expect(parsedJson[1].index["116"]).toBe(2.63);
  });
});

describe("resolveHitTrendKey（搜尋結果「看趨勢」入口規則）", () => {
  const base: Omit<SearchDoc, "kind" | "code" | "text"> = {
    id: "x",
    year: 114,
    name: "測試",
  };

  it("revenue 明細 → <年>:revenue:<code>", () => {
    expect(resolveHitTrendKey({ ...base, kind: "revenue", code: "01120010201", text: "說明" })).toBe(
      "114:revenue:01120010201",
    );
  });

  it("expenditure 明細與 plan → <年>:plan:<code>", () => {
    expect(
      resolveHitTrendKey({ ...base, kind: "expenditure", code: "33120010101", 用途別_code: "1015", text: "說明" }),
    ).toBe("114:plan:33120010101");
    expect(resolveHitTrendKey({ ...base, kind: "plan", code: "33120010101", text: "說明" })).toBe(
      "114:plan:33120010101",
    );
  });

  it("summary 只限 text.split(' ')[0] === '歲入來源別預算總表' 且 code 非空", () => {
    expect(
      resolveHitTrendKey({ ...base, kind: "summary", code: "04-02", text: "歲入來源別預算總表 財產售價" }),
    ).toBe("114:revenue:04-02");
    // 歲入合計 code 為空 → null
    expect(
      resolveHitTrendKey({ ...base, kind: "summary", code: "", text: "歲入來源別預算總表 歲入合計" }),
    ).toBeNull();
    // 歲入來源別預算比較總表 → null
    expect(
      resolveHitTrendKey({ ...base, kind: "summary", code: "04-02", text: "歲入來源別預算比較總表 財產售價" }),
    ).toBeNull();
    // 其他總表 → null
    expect(
      resolveHitTrendKey({ ...base, kind: "summary", code: "01", text: "歲出政事別預算總表 一般政務支出" }),
    ).toBeNull();
  });
});

describe("DataSource.series() 載入失敗快取 null 與優雅降級", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("HTTP 404 時回傳 null 且快取（不重複發請求）", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("Not Found", { status: 404 }));
    const src = createHttpSource("data/");
    expect(await src.series()).toBeNull();
    expect(await src.series()).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("網路錯誤時回傳 null 且快取", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));
    const src = createHttpSource("data/");
    expect(await src.series()).toBeNull();
    expect(await src.series()).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("非 JSON（如 vite dev fallback HTML）時回傳 null", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html></html>", { status: 200 }));
    const src = createHttpSource("data/");
    expect(await src.series()).toBeNull();
  });

  it("合法 series.json 時回傳資料並快取", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(sample), { status: 200 }));
    const src = createHttpSource("data/");
    const a = await src.series();
    const b = await src.series();
    expect(a).toEqual(sample);
    expect(b).toBe(a);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
