// 在 Node 的 vm 裡用模擬的 DOM 與 fetch 執行 site/app.js，供 tests/test_frontend.py 呼叫。
// 用法：node frontend_harness.js [app.js 路徑]（預設為 site/app.js）。stdout 輸出各情境結果的 JSON 陣列。
// 不測 CSS、真實版面或 CDN 函式庫（echarts、minisearch）；只測路由、導覽與錯誤處理邏輯。
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
      classList: { toggle() {} },
      listeners: {},
      addEventListener(ev, fn) { this.listeners[ev] = fn; },
      setAttribute(k, v) { this.attrs[k] = v; },
      querySelectorAll() { return []; },
      querySelector() { return null; },
      insertAdjacentHTML() {},
    },
    extra
  );
}

// navMode: "current" = 目前的 index.html（有 data-nav="ref" 的導覽連結）
//          "legacy"  = 舊版 index.html（沒有該連結；舊頁被瀏覽器快取、卻載入新版 app.js 的情況）
async function runScenario(hash, navMode) {
  const hashListeners = [];
  const location = {
    _h: hash,
    get hash() { return this._h; },
    set hash(v) { this._h = v.startsWith("#") ? v : "#" + v; setTimeout(() => hashListeners.forEach((f) => f()), 0); },
    replace(v) { this.hash = v; },
  };
  const navs = {};
  for (const k of ["overview", "exp", "rev", "ref"]) {
    navs[k] = mkEl({ dataset: { nav: k }, hidden: k === "ref" });
  }
  const app = mkEl({ innerHTML: "載入中…" });
  const yearSel = mkEl();
  yearSel.options = [];
  const byId = { app, yearSel, q: mkEl(), searchForm: mkEl() };
  const brand = mkEl();
  const document = {
    getElementById: (id) => byId[id],
    querySelector: (sel) => {
      const m = sel.match(/data-nav="(\w+)"/);
      if (m) return m[1] === "ref" && navMode === "legacy" ? null : navs[m[1]];
      if (sel === ".brand") return brand;
      return mkEl();
    },
    querySelectorAll: () => [],
  };
  const ctx = {
    document,
    location,
    window: { addEventListener: (e, f) => { if (e === "hashchange") hashListeners.push(f); }, scrollTo() {} },
    URLSearchParams,
    console,
    setTimeout,
    Promise,
    MiniSearch: null,
    fetch: async (p) => {
      const file = path.join(siteDir, p);
      if (!fs.existsSync(file)) return { ok: false, status: 404 };
      const text = fs.readFileSync(file, "utf8");
      return { ok: true, status: 200, json: async () => JSON.parse(text) };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(appJs, "utf8"), ctx);
  // 等 render() 完成（innerHTML 不再是「載入中…」），最多 3 秒
  const t0 = Date.now();
  while (app.innerHTML === "載入中…" && Date.now() - t0 < 3000) {
    await new Promise((r) => setTimeout(r, 20));
  }
  return {
    hash,
    navMode,
    finalHash: location._h,
    html: app.innerHTML,
    failed: app.innerHTML.includes("載入失敗"),
    refHidden: navs.ref.hidden,
    refHref: navs.ref.attrs.href || null,
    overviewHref: navs.overview.attrs.href || null,
  };
}

(async () => {
  const scenarios = [
    ["#/114/總覽", "current"],
    ["#/115/總覽", "current"],
    ["#/114/總覽", "legacy"],
    ["#/115/總覽", "legacy"],
    ["#/116/歲入", "legacy"],
    ["#/114/參考表?p=170", "legacy"],
  ];
  const out = [];
  for (const [hash, mode] of scenarios) out.push(await runScenario(hash, mode));
  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
