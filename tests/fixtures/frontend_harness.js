// 在 Node 的 vm 裡用模擬的 DOM 與 fetch 執行 site/app.js，供 tests/test_frontend.py 呼叫。
// 用法：node frontend_harness.js [app.js 路徑]（預設為 site/app.js）。stdout 輸出各情境結果的 JSON 陣列。
// 不測 CSS、真實版面或 CDN 函式庫（echarts、minisearch）；MiniSearch 以記錄用 stub 替代。
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const siteDir = path.resolve(__dirname, "..", "..", "site");
const appJs = process.argv[2] ? path.resolve(process.argv[2]) : path.join(siteDir, "app.js");

function mkEl(extra = {}) {
  return Object.assign(
    {
      innerHTML: "",
      value: "",
      hidden: false,
      attrs: {},
      dataset: {},
      classList: { toggle() {}, contains() { return false; } },
      listeners: {},
      addEventListener(ev, fn) {
        if (!this.listeners[ev]) this.listeners[ev] = [];
        this.listeners[ev].push(fn);
      },
      setAttribute(k, v) { this.attrs[k] = v; },
      querySelectorAll() { return []; },
      querySelector() { return null; },
      insertAdjacentHTML() {},
    },
    extra
  );
}

// 從真實 site/data/<year>.json 推導歲入細目或子目頁的 hash
function deriveRevenueHash(year, targetFineCode, stopAtSub = false) {
  const data = JSON.parse(fs.readFileSync(path.join(siteDir, "data", `${year}.json`), "utf8"));
  for (const k of data.revenue.hierarchy) {
    for (const h of k.children || []) {
      for (const s of h.children || []) {
        for (const f of s.children || []) {
          if (f.code === targetFineCode) {
            const params = { 款: k.code, 項: h.code, 子目: s.code };
            if (!stopAtSub) params["細目"] = f.code;
            return `#/${year}/歲入?${new URLSearchParams(params).toString()}`;
          }
        }
      }
    }
  }
  throw new Error(`找不到 ${year} 細目 ${targetFineCode}`);
}

// navMode: "current" = 目前的 index.html（有 data-nav="ref" 與 "memo" 的導覽連結）
//          "legacy"  = 舊版 index.html（沒有這兩個連結；舊頁被瀏覽器快取、卻載入新版 app.js 的情況）
async function runScenario(hash, navMode, opts = {}) {
  const hashListeners = [];
  const docListeners = {};
  const location = {
    _h: hash,
    get hash() { return this._h; },
    set hash(v) {
      this._h = v.startsWith("#") ? v : "#" + v;
      setTimeout(() => hashListeners.forEach((f) => f()), 0);
    },
    replace(v) { this.hash = v; },
  };
  const navs = {};
  for (const k of ["overview", "exp", "rev", "ref", "memo"]) {
    navs[k] = mkEl({ dataset: { nav: k }, hidden: k === "ref" || k === "memo" });
  }
  const fakeRows = [];
  const app = mkEl({
    innerHTML: "載入中…",
    querySelectorAll(sel) {
      if (sel === "tr[data-to]") {
        fakeRows.length = 0;
        const re = /<tr\b[^>]*data-to="([^"]+)"/g;
        let m;
        while ((m = re.exec(this.innerHTML)) !== null) {
          fakeRows.push(mkEl({ dataset: { to: m[1] } }));
        }
        return fakeRows;
      }
      return [];
    },
  });
  const memoPanel = mkEl({ hidden: true });
  const yearSel = mkEl();
  yearSel.options = [];
  const byId = { app, yearSel, q: mkEl(), searchForm: mkEl(), memoPanel };
  const brand = mkEl();
  const document = {
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => {
      const m = sel.match(/data-nav="(\w+)"/);
      if (m) {
        if ((m[1] === "ref" || m[1] === "memo") && navMode === "legacy") return null;
        return navs[m[1]] || null;
      }
      if (sel === ".brand") return brand;
      return mkEl();
    },
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => {
      if (!docListeners[ev]) docListeners[ev] = [];
      docListeners[ev].push(fn);
    },
  };

  // 記錄用 MiniSearch stub：記錄建構時的 fields、addAll 收到的文件，並以子字串比對 fields 執行 search
  const searchRecord = { fields: null, docs: null, constructed: 0 };
  class MiniSearchStub {
    constructor(options) {
      searchRecord.constructed += 1;
      searchRecord.fields = options && options.fields ? [...options.fields] : [];
      this._fields = searchRecord.fields;
      this._docs = [];
    }
    addAll(docs) {
      this._docs = docs;
      searchRecord.docs = docs;
    }
    search(query) {
      const q = String(query || "").trim();
      if (!q) return [];
      return this._docs.filter((doc) =>
        this._fields.some((f) => doc[f] !== undefined && doc[f] !== null && String(doc[f]).includes(q))
      );
    }
  }

  let rawSearchDocsRef = null;
  let rawSearchDocsSnapshot = null;

  const ctx = {
    document,
    location,
    window: { addEventListener: (e, f) => { if (e === "hashchange") hashListeners.push(f); }, scrollTo() {} },
    URLSearchParams,
    console,
    setTimeout,
    Promise,
    MiniSearch: MiniSearchStub,
    fetch: async (p) => {
      if (opts.memos404 && p === "data/memos.json") {
        return { ok: false, status: 404 };
      }
      const file = path.join(siteDir, p);
      if (!fs.existsSync(file)) return { ok: false, status: 404 };
      let text = fs.readFileSync(file, "utf8");
      if (opts.injectNote && p === "data/reference_114.json") {
        // 測試跳脫：把 p165 的提示換成一段惡意字串
        const d = JSON.parse(text);
        d.tables.find((x) => x.page === 165).note = opts.injectNote;
        text = JSON.stringify(d);
      }
      if (opts.injectMemoHtml && p === "data/memos.json") {
        const d = JSON.parse(text);
        const m1 = d.years["114"].find((x) => x.memo_id === "M114-0001");
        if (m1) {
          m1.printed_text = opts.injectMemoHtml;
          m1.note = opts.injectMemoHtml;
        }
        text = JSON.stringify(d);
      }
      if (opts.injectMemos && p === "data/memos.json") {
        const d = JSON.parse(text);
        for (const m of opts.injectMemos) {
          const yKey = String(m.year);
          if (!d.years[yKey]) d.years[yKey] = [];
          d.years[yKey].push(m);
        }
        text = JSON.stringify(d);
      }
      if (opts.overrideMemoYears && p === "data/index.json") {
        const d = JSON.parse(text);
        d.memo_years = opts.overrideMemoYears;
        text = JSON.stringify(d);
      }
      if (p === "data/search.json") {
        const parsed = JSON.parse(text);
        rawSearchDocsRef = parsed;
        rawSearchDocsSnapshot = JSON.stringify(parsed);
        return { ok: true, status: 200, json: async () => parsed };
      }
      return { ok: true, status: 200, json: async () => JSON.parse(text) };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(appJs, "utf8"), ctx);
  // 等 render() 完成（innerHTML 不再是「載入中…」或「搜尋中…」），且若有 redirect 也多等一個 tick
  const t0 = Date.now();
  while (
    (app.innerHTML === "載入中…" || app.innerHTML.includes("搜尋中…")) &&
    Date.now() - t0 < 3000
  ) {
    await new Promise((r) => setTimeout(r, 20));
  }
  // 若有 location.replace 觸發 hashchange，多等一次非同步 render
  if (location._h !== hash) {
    await new Promise((r) => setTimeout(r, 60));
    const t1 = Date.now();
    while (app.innerHTML === "載入中…" && Date.now() - t1 < 2000) {
      await new Promise((r) => setTimeout(r, 20));
    }
  }

  let rowClickHashUnchanged = null;
  let rowClickNormalChanged = null;
  if (opts.testRowClickGuard && fakeRows.length > 0) {
    const tr = fakeRows[0];
    const clickFns = tr.listeners.click || [];
    const before = location._h;
    const fakeMemoEvent = {
      target: { closest: (sel) => (sel === ".memo-btn" ? { dataset: { memo: "M114-0001" } } : null) },
      preventDefault() {},
      stopPropagation() {},
    };
    clickFns.forEach((fn) => fn(fakeMemoEvent));
    rowClickHashUnchanged = location._h === before;
    // 也驗證一般點擊（非 .memo-btn）仍會導覽
    const fakeNormalEvent = { target: { closest: () => null } };
    clickFns.forEach((fn) => fn(fakeNormalEvent));
    rowClickNormalChanged = location._h !== before;
    location._h = before;
  }

  if (opts.clickMemoId) {
    const appClicks = app.listeners.click || [];
    const fakeEvent = {
      target: {
        closest: (sel) => (sel === ".memo-btn" ? { dataset: { memo: opts.clickMemoId } } : null),
      },
      preventDefault() {},
      stopPropagation() {},
    };
    appClicks.forEach((fn) => fn(fakeEvent));
  }

  let searchStub = null;
  if (searchRecord.constructed > 0) {
    const docs = searchRecord.docs || [];
    const d116 = docs.find((d) => d.id === "116-revenue-12120010204-1") || null;
    const d114 = docs.find((d) => d.id === "114-revenue-12120010204-1") || null;
    const sampleNoMemo = docs.find((d) => d.id === "114-revenue-01120011401-1") || null;
    const rawMutated = rawSearchDocsRef ? JSON.stringify(rawSearchDocsRef) !== rawSearchDocsSnapshot : false;
    const inspectedDocs = {};
    for (const docId of opts.inspectDocIds || []) {
      const foundDoc = docs.find((d) => d.id === docId) || null;
      inspectedDocs[docId] = {
        found: Boolean(foundDoc),
        hasAliasKey: foundDoc ? Object.prototype.hasOwnProperty.call(foundDoc, "alias") : false,
        alias: foundDoc ? (foundDoc.alias ?? null) : null,
      };
    }
    searchStub = {
      constructed: searchRecord.constructed,
      fields: searchRecord.fields,
      docCount: docs.length,
      doc116Alias: d116 ? d116.alias ?? null : null,
      doc114Alias: d114 ? d114.alias ?? null : null,
      sampleNoMemoHasAliasKey: sampleNoMemo ? Object.prototype.hasOwnProperty.call(sampleNoMemo, "alias") : null,
      rawSearchMutated: rawMutated,
      inspectedDocs,
    };
  }

  return {
    id: opts.id || null,
    hash,
    navMode,
    injected: Boolean(opts.injectNote),
    finalHash: location._h,
    html: app.innerHTML,
    failed: app.innerHTML.includes("載入失敗"),
    refHidden: navs.ref.hidden,
    refHref: navs.ref.attrs.href || null,
    memoHidden: navs.memo.hidden,
    memoHref: navs.memo.attrs.href || null,
    overviewHref: navs.overview.attrs.href || null,
    panelHidden: memoPanel.hidden,
    panelHtml: memoPanel.innerHTML,
    rowClickHashUnchanged,
    rowClickNormalChanged,
    searchStub,
  };
}

(async () => {
  const rev114Memo = deriveRevenueHash(114, "12120010204");
  const rev114NoMemo = deriveRevenueHash(114, "01120011401");
  const rev114Sub = deriveRevenueHash(114, "12120010204", true);
  const rev115Memo = deriveRevenueHash(115, "12120010204");
  const rev116Memo = deriveRevenueHash(116, "12120010204");

  const scenarios = [
    // 既有情境（保留原狀）
    ["#/114/總覽", "current"],
    ["#/115/總覽", "current"],
    ["#/114/總覽", "legacy"],
    ["#/115/總覽", "legacy"],
    ["#/116/歲入", "legacy"],
    ["#/114/參考表?p=170", "legacy"],
    ["#/114/參考表?p=154", "current"],
    ["#/114/參考表?p=165", "current"],
    ["#/114/參考表?p=168", "current"],
    ["#/114/參考表?p=165", "current", { injectNote: "<img src=x onerror=alert(1)>" }],

    // 新增：S2 備註相關情境
    [rev114Memo, "current", { id: "rev114_memo", clickMemoId: "M114-0001" }],
    [rev114NoMemo, "current", { id: "rev114_nomemo" }],
    [rev114Sub, "current", { id: "rev114_sub_rowguard", testRowClickGuard: true }],
    [rev115Memo, "current", { id: "rev115_memo" }],
    [rev116Memo, "current", { id: "rev116_memo" }],
    ["#/114/參考表?p=159", "current", { id: "ref114_p159" }],
    ["#/114/備註", "current", { id: "memo_page_114" }],
    ["#/114/備註?type=print_typo", "current", { id: "memo_page_114_typo" }],
    ["#/114/備註?p=159", "current", { id: "memo_page_114_p159" }],
    ["#/115/備註", "current", { id: "memo_page_115" }],
    ["#/116/備註", "current", { id: "memo_page_116" }],
    ["#/116/總覽", "current", { id: "nav_116" }],
    ["#/114/備註", "current", { id: "memo_year_excluded_redirect", overrideMemoYears: [115, 116] }],
    ["#/114/總覽", "current", { id: "memo_year_excluded_nav", overrideMemoYears: [115, 116] }],
    ["#/116/搜尋?q=" + encodeURIComponent("自治條例"), "current", { id: "search_116_alias" }],
    ["#/114/歲入", "current", { id: "memos404_rev", memos404: true }],
    ["#/114/參考表?p=165", "current", { id: "memos404_ref", memos404: true }],
    ["#/114/搜尋?q=" + encodeURIComponent("廢棄物"), "current", { id: "memos404_search", memos404: true }],
    ["#/114/備註", "current", { id: "memos404_page", memos404: true }],
    ["#/114/備註", "current", { id: "memo_escape_page", injectMemoHtml: "<img src=x onerror=alert(1)>" }],
    [rev114Memo, "current", { id: "memo_escape_panel", injectMemoHtml: "<img src=x onerror=alert(1)>", clickMemoId: "M114-0001" }],
    [
      "#/114/搜尋?q=" + encodeURIComponent("ZZYESALIAS"),
      "current",
      {
        id: "search_alias_type_filter",
        injectMemos: [
          {
            memo_id: "M114-TEST-NON-TYPO",
            year: 114,
            scope: "revenue_item",
            page: 39,
            locator: "01120010201:1",
            field: "note",
            type: "print_inconsistent",
            printed_text: "orig",
            data_text: "orig",
            suggested_text: "ZZNOALIAS",
            note: "測試非 print_typo 不應併入 alias",
            pdf_file: "test.pdf",
            pdf_page: 45,
            verified_method: "測試",
            verified_on: "2026-11-19",
            evidence: "",
            status: "confirmed",
            target: {
              kind: "revenue",
              search_id: "114-revenue-01120010201-1",
              code: "01120010201",
              item_seq: 1,
              page: 39,
            },
          },
          {
            memo_id: "M114-TEST-TYPO",
            year: 114,
            scope: "revenue_item",
            page: 39,
            locator: "01120010202:1",
            field: "note",
            type: "print_typo",
            printed_text: "orig",
            data_text: "orig",
            suggested_text: "ZZYESALIAS",
            note: "測試 print_typo 應併入 alias",
            pdf_file: "test.pdf",
            pdf_page: 45,
            verified_method: "測試",
            verified_on: "2026-11-19",
            evidence: "",
            status: "confirmed",
            target: {
              kind: "revenue",
              search_id: "114-revenue-01120010202-1",
              code: "01120010202",
              item_seq: 1,
              page: 39,
            },
          },
        ],
        inspectDocIds: ["114-revenue-01120010201-1", "114-revenue-01120010202-1"],
      },
    ],
  ];
  const out = [];
  for (const [hash, mode, opts] of scenarios) out.push(await runScenario(hash, mode, opts));
  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
