// 萬巒鄉預算查詢：純靜態、無 build。資料來自 site/data/*.json（由 scripts/build.py 產生）。
const $app = document.getElementById("app");
const cache = {};
let charts = [];

const REV_LEVELS = [["款", "款"], ["項", "項"], ["子目", "子目"], ["細目", "細目"]];
const EXP_LEVELS = [["政事別", "政事別"], ["機關", "機關"], ["工作計畫", "計畫"], ["用途別", "用途別"]];
const SECTIONS = {
  "歲入": { key: "revenue", levels: REV_LEVELS, nav: "rev" },
  "歲出": { key: "expenditure", levels: EXP_LEVELS, nav: "exp" },
};

// ---------- 工具 ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n === null || n === undefined || n === "" ? "" : Number(n).toLocaleString("en-US"));
const fmtBig = (n) => {
  const v = Number(n) || 0, a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(2) + " 億";
  if (a >= 1e4) return fmt(Math.round(v / 1e4)) + " 萬";
  return fmt(v);
};
const pageText = (n) => {
  const s = n.page_start ?? n.page, e = n.page_end ?? n.page;
  if (s === undefined || s === null || s === "") return "";
  return s === e || e === undefined ? `p${s}` : `p${s}–${e}`;
};
const nodeKey = (n) => (n.level === "政事別" || n.level === "機關" ? n.name : n.code || n.name);
const href = (year, section, params) => {
  const q = new URLSearchParams(params).toString();
  return `#/${year}/${section}${q ? "?" + q : ""}`;
};

async function loadJson(path) {
  if (!cache[path]) {
    cache[path] = fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    });
  }
  return cache[path];
}

// 比較資料依相鄰年度對（如 "114-115"）取得；404 或失敗視為沒有比較。
const comparePromises = {};
async function getCompare(pair) {
  if (!pair) return null;
  if (!comparePromises[pair]) {
    comparePromises[pair] = fetch(`data/compare_${pair.replace("-", "_")}.json`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return comparePromises[pair];
}

// 相鄰年度對：由 index.years 推出，如 ["114-115", "115-116"]
function adjacentPairs(index) {
  const ys = index.years.map(Number).sort((a, b) => a - b);
  return ys.slice(1).map((y, i) => `${ys[i]}-${y}`);
}

// 年度 Y 預設的比較對：(Y, Y+1) 若存在，否則 (Y-1, Y)；都沒有則 null
function defaultPair(index, year) {
  const y = Number(year), pairs = adjacentPairs(index);
  return pairs.find((p) => p.startsWith(`${y}-`)) || pairs.find((p) => p.endsWith(`-${y}`)) || null;
}

// 比較頁可用 pair=a-b 指定比較對；無效或缺少時用預設規則
function pickPair(index, year, params) {
  const want = params && params.get("pair");
  if (want && adjacentPairs(index).includes(want)) return want;
  return defaultPair(index, year);
}

function hasCompareEntry(compare, kind, code) {
  if (!compare || !compare.entries || !kind || !code) return false;
  return Boolean(compare.entries[`${kind}:${code}`]);
}

function compareBtn(year, compare, kind, code) {
  if (!hasCompareEntry(compare, kind, code)) return "";
  const url = href(year, "比較", { kind, code });
  return ` <a class="btn btn-sm" href="${esc(url)}">比較</a>`;
}

const fmtDiff = (n) => {
  if (n === null || n === undefined || n === "") return "—";
  const v = Number(n);
  return (v > 0 ? "+" : "") + fmt(v);
};

const fmtPct = (entry, y1, y2) => {
  if (entry.status === `only_${y1}`) return `僅${y1}`;
  if (entry.status === `only_${y2}`) return `僅${y2}`;
  if (entry.pct === null || entry.pct === undefined) return "—";
  const v = Number(entry.pct);
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
};

// ---------- 路由 ----------
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [pathPart, query = ""] = raw.split("?");
  const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  return { year: parts[0] || null, view: parts[1] || "總覽", params: new URLSearchParams(query) };
}

async function render() {
  charts.forEach((c) => c.dispose());
  charts = [];
  try {
    const index = await loadJson("data/index.json");
    const r = parseHash();
    const year = String(r.year && /^\d+$/.test(r.year) ? r.year : index.default_year);
    if (!index.years.map(String).includes(year)) {
      $app.innerHTML = `<p class="warn">找不到年度 ${esc(year)}。</p>`;
      return;
    }
    const pair = pickPair(index, year, r.view === "比較" ? r.params : null);
    const [data, compare] = await Promise.all([
      loadJson(`data/${year}.json`),
      getCompare(pair),
    ]);
    setNav(r.view, year, index);
    if (r.view === "歲入" || r.view === "歲出") renderDrill(year, r.view, data, r.params, compare);
    else if (r.view === "搜尋") await renderSearch(year, data, r.params, compare);
    else if (r.view === "比較") renderCompare(year, data, r.params, compare, pair, defaultPair(index, year));
    else renderOverview(year, data);
    window.scrollTo(0, 0);
  } catch (e) {
    $app.innerHTML = `<p class="warn">載入失敗：${esc(e.message)}。請用 <code>python3 -m http.server</code> 從 site/ 目錄開啟，不要直接開檔案。</p>`;
  }
}

const $yearSel = document.getElementById("yearSel");
$yearSel.addEventListener("change", () => {
  // 換年度：保留目前的畫面（總覽／歲出／歲入／搜尋／比較）；搜尋保留關鍵字，比較保留 kind 與 code
  const r = parseHash();
  const view = r.view || "總覽";
  let params = {};
  if (view === "搜尋" && r.params.get("q")) params = { q: r.params.get("q") };
  else if (view === "比較") { params = Object.fromEntries(r.params.entries()); delete params.pair; } // pair 依新年度重新決定
  location.hash = href($yearSel.value, view, params);
});

function setNav(view, year, index) {
  if (!$yearSel.options.length) {
    $yearSel.innerHTML = index.years.map((y) => `<option value="${esc(y)}">${esc(y)} 年度</option>`).join("");
  }
  $yearSel.value = year;
  // 導覽連結跟著目前年度走，不寫死
  document.querySelector('.nav a[data-nav="overview"]').setAttribute("href", href(year, "總覽"));
  document.querySelector('.nav a[data-nav="exp"]').setAttribute("href", href(year, "歲出"));
  document.querySelector('.nav a[data-nav="rev"]').setAttribute("href", href(year, "歲入"));
  document.querySelector(".brand").setAttribute("href", href(year, "總覽"));
  document.querySelectorAll(".nav a").forEach((a) => {
    const on = (a.dataset.nav === "exp" && view === "歲出") || (a.dataset.nav === "rev" && view === "歲入") || (a.dataset.nav === "overview" && view === "總覽");
    a.classList.toggle("on", on);
  });
}

// ---------- 總覽 ----------
function warnBox(year, data) {
  const items = data.overview.unresolved_items || [];
  if (!items.length) return "";
  const lis = items
    .map((u) => {
      const link = href(year, "歲入", { 款: u.code.slice(0, 2), 項: `${u.code.slice(0, 2)}-${u.code.slice(2, 4)}`, 細目: u.code });
      return `<li><a href="#" data-find="${esc(u.code)}">${esc(u.code)} ${esc(u.name)}</a>（${esc(pageText(u))}）：明細加總 ${fmt(u.detail_amount_元)} 元，與表頭 ${fmt(u.amount_元)} 元差 ${fmt(u.diff_元)} 元，待核對 PDF。</li>`;
    })
    .join("");
  return `<div class="warn"><strong>資料尚有未解決的差額</strong>：以下項目的明細加總與預算書表頭不一致，轉檔疑似漏列，數字僅供參考。<ul>${lis}</ul></div>`;
}

function renderOverview(year, data) {
  const o = data.overview;
  const cur = o.current_account, cap = o.capital_account;
  $app.innerHTML = `
    <h1>${esc(year)} 年度總預算</h1>
    ${warnBox(year, data)}
    <div class="cards">
      <div class="card"><div class="k">歲入總額</div><div class="v">${fmtBig(o.revenue_total_元)}</div><div class="s">${fmt(o.revenue_total_元)} 元</div></div>
      <div class="card"><div class="k">歲出總額</div><div class="v">${fmtBig(o.expenditure_total_元)}</div><div class="s">${fmt(o.expenditure_total_元)} 元</div></div>
      <div class="card"><div class="k">收支差短</div><div class="v">${fmtBig(o.balance_元)}</div><div class="s">以前年度賸餘彌補 ${fmt(o.prior_surplus_used_元)} 元</div></div>
      <div class="card"><div class="k">經常門歲出 / 資本門歲出</div><div class="v">${fmtBig(cur.expenditure_元)} / ${fmtBig(cap.expenditure_元)}</div><div class="s">p${esc(cur.page)}</div></div>
    </div>
    <h2>歲入來源（點選款別往下查）</h2>
    <div id="chRev" class="chart"></div>
    <h2>歲出政事別（點選政事別往下查）</h2>
    <div id="chExp" class="chart"></div>
    <h2>經常門與資本門歲出</h2>
    <div id="chNat" class="chart small"></div>
    <p class="note">金額單位：元。可由上方「歲出」「歲入」逐層展開到明細，每一層都附預算書頁碼。</p>`;
  bindFind(year, data);
  if (!window.echarts) {
    $app.insertAdjacentHTML("beforeend", `<p class="warn">圖表函式庫載入失敗（需要網路連到 CDN），其他功能不受影響。</p>`);
    return;
  }
  const palette = ["#3b6fd4", "#2a9d8f", "#e9a23b", "#c8553d", "#7b5ea7", "#4f8a5b", "#a14a76", "#5d6d7e"];
  const mk = (id, nodes, section, level) => {
    const chart = echarts.init(document.getElementById(id));
    charts.push(chart);
    chart.setOption({
      color: palette,
      tooltip: { formatter: (p) => `${esc(p.name)}<br>${fmt(p.value)} 元` },
      series: [{
        type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, width: "100%", height: "100%",
        label: { show: true, formatter: (p) => `${p.name}\n${fmtBig(p.value)}`, overflow: "truncate" },
        itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 },
        data: nodes.filter((n) => n.amount_元 > 0).map((n) => ({ name: n.name, value: n.amount_元, key: nodeKey(n) })),
      }],
    });
    chart.on("click", (p) => { location.hash = href(year, section, { [level]: p.data.key }); });
  };
  mk("chRev", data.revenue.hierarchy, "歲入", "款");
  mk("chExp", data.expenditure.hierarchy, "歲出", "政事別");
  const nat = echarts.init(document.getElementById("chNat"));
  charts.push(nat);
  nat.setOption({
    color: palette,
    tooltip: { formatter: (p) => `${esc(p.name)}<br>${fmt(p.value)} 元（${p.percent}%）` },
    series: [{ type: "pie", radius: ["40%", "70%"], label: { formatter: "{b}\n{d}%" }, data: [{ name: "經常門歲出", value: cur.expenditure_元 }, { name: "資本門歲出", value: cap.expenditure_元 }] }],
  });
  window.onresize = () => charts.forEach((c) => c.resize());
}

// ---------- 逐層展開 ----------
function walkPath(nodes, levels, params) {
  const path = [];
  let list = nodes;
  for (const [lvl, param] of levels) {
    const v = params.get(param);
    if (v === null) break;
    const hit = list.find((n) => nodeKey(n) === v);
    if (!hit) return { path, missing: `${param}=${v}` };
    path.push({ node: hit, param, value: v });
    list = hit.children || [];
    if (hit.level === "細目" || hit.level === "用途別") break;
  }
  return { path };
}

function getDrillCompareTarget(view, node) {
  if (!node) return { kind: null, code: null };
  if (view === "歲入") return { kind: "revenue", code: node.code };
  if (view === "歲出") {
    if (node.level === "工作計畫") return { kind: "plan", code: node.code };
    if (node.level === "用途別") return { kind: "object", code: `${node.plan_code}|${node.code}` };
  }
  return { kind: null, code: null };
}

function renderDrill(year, view, data, params, compare) {
  const sec = SECTIONS[view];
  const root = data[sec.key];
  const { path, missing } = walkPath(root.hierarchy, sec.levels, params);
  const cur = path.length ? path[path.length - 1].node : null;
  const crumbs = [`<a href="${href(year, view, {})}">${esc(view)}</a>`];
  const acc = {};
  path.forEach((p, i) => {
    acc[p.param] = p.value;
    crumbs.push(i === path.length - 1 ? `<strong>${esc(p.node.name)}</strong>` : `<a href="${href(year, view, { ...acc })}">${esc(p.node.name)}</a>`);
  });
  const parentAmt = cur ? cur.amount_元 : root.total_元;
  let body;
  if (cur && (cur.level === "細目" || cur.level === "用途別")) body = detailTable(cur, view);
  else body = childTable(year, view, cur ? cur.children : root.hierarchy, acc, parentAmt);
  const note = cur && cur.unresolved
    ? `<div class="warn"><strong>未解決</strong>：${esc(cur.note || cur.unresolved_note || "此項資料待核對")}</div>`
    : "";
  const cmpTarget = getDrillCompareTarget(view, cur);
  const cmpBtn = compareBtn(year, compare, cmpTarget.kind, cmpTarget.code);
  const head = cur
    ? `<h1>${esc(cur.name)} <span class="muted">${esc(cur.level)}${cur.code ? " " + esc(cur.code) : ""}</span>${cmpBtn}</h1>
       <p>預算 <strong>${fmt(cur.amount_元)}</strong> 元　${esc(pageText(cur))}${cur.dept ? "　承辦：" + esc(cur.dept) : ""}</p>`
    : `<h1>${esc(year)} 年度${esc(view)}　<span class="muted">${fmt(root.total_元)} 元</span></h1>`;
  $app.innerHTML = `<div class="crumbs">${crumbs.join('<span class="sep">›</span>')}</div>${missing ? `<p class="warn">找不到：${esc(missing)}</p>` : ""}${head}${note}${body}`;
  $app.querySelectorAll("tr[data-to]").forEach((tr) => tr.addEventListener("click", () => { location.hash = tr.dataset.to; }));
}

function childTable(year, view, nodes, acc, parentAmt) {
  const sec = SECTIONS[view];
  const rows = nodes.map((n) => {
    const nextLevel = sec.levels.find(([lvl]) => lvl === n.level);
    const to = nextLevel ? href(year, view, { ...acc, [nextLevel[1]]: nodeKey(n) }) : "";
    const pct = parentAmt ? Math.max(0, Math.min(100, (n.amount_元 / parentAmt) * 100)) : 0;
    const flag = n.unresolved ? ' <span class="badge" title="明細加總與表頭不一致，待核對">⚠ 未解決</span>' : "";
    return `<tr class="click" data-to="${esc(to)}"><td><a href="${esc(to)}">${esc(n.name)}</a>${flag}<div class="note">${esc(n.level)}${n.code ? " " + esc(n.code) : ""}${n.dept ? "　" + esc(n.dept) : ""}</div></td>
      <td class="num">${fmt(n.amount_元)}<div class="bar"><i style="width:${pct.toFixed(1)}%"></i></div></td>
      <td class="num hide-sm">${pct.toFixed(1)}%</td><td class="num">${esc(pageText(n))}</td></tr>`;
  });
  return `<div class="tablewrap"><table><thead><tr><th>名稱</th><th class="num">預算（元）</th><th class="num hide-sm">占比</th><th class="num">頁碼</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

function detailTable(node, view) {
  const items = node.children || [];
  const isExp = view === "歲出";
  const rows = items.map((it) => `<tr><td>${esc(isExp ? it["說明"] : it.note || it.name)}${it.unresolved ? ' <span class="badge">⚠</span>' : ""}</td>
    <td class="hide-sm">${esc(it.unit)}</td><td class="num hide-sm">${esc(it.qty)}</td><td class="num hide-sm">${fmt(it.unit_price)}</td><td class="num">${fmt(it.amount_元)}</td>
    ${isExp ? `<td class="hide-sm">${esc(it["經費來源"])}</td>` : ""}<td class="num">p${esc(it.page)}</td></tr>`);
  return `<div class="tablewrap"><table><thead><tr><th>${isExp ? "說明" : "說明／依據"}</th><th class="hide-sm">單位</th><th class="num hide-sm">數量</th><th class="num hide-sm">單價</th><th class="num">預算（元）</th>${isExp ? '<th class="hide-sm">經費來源</th>' : ""}<th class="num">頁碼</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

// ---------- 搜尋 ----------
let searchIndex = null;
// 中文沒有空白分詞：CJK 以單字 + 相鄰雙字組索引，英數字照一般詞切。
function tokenize(text) {
  const out = [];
  for (const m of String(text).toLowerCase().matchAll(/[㐀-鿿]+|[a-z0-9]+/g)) {
    const w = m[0];
    if (/^[a-z0-9]+$/.test(w)) { out.push(w); continue; }
    for (let i = 0; i < w.length; i++) {
      out.push(w[i]);
      if (i + 1 < w.length) out.push(w.slice(i, i + 2));
    }
  }
  return out;
}

async function getSearch() {
  if (searchIndex) return searchIndex;
  const docs = await loadJson("data/search.json");
  const ms = new MiniSearch({
    fields: ["name", "text", "code", "dept"],
    storeFields: ["kind", "year", "code", "name", "text", "page", "page_start", "page_end", "amount_元", "dept", "unresolved", "用途別_code"],
    tokenize,
    searchOptions: { tokenize, combineWith: "AND", boost: { name: 2 } },
  });
  ms.addAll(docs);
  searchIndex = { ms, docs };
  return searchIndex;
}

function findPath(nodes, levels, targetCode, trail = {}) {
  for (const n of nodes) {
    const lv = levels.find(([l]) => l === n.level);
    if (!lv) continue;
    const here = { ...trail, [lv[1]]: nodeKey(n) };
    if (n.code === targetCode || (n.level === "工作計畫" && n.code === targetCode)) return here;
    if (n.children && n.level !== "細目" && n.level !== "用途別") {
      const r = findPath(n.children, levels, targetCode, here);
      if (r) return r;
    }
  }
  return null;
}

function getSearchCompareTarget(hit) {
  if (!hit) return { kind: null, code: null };
  if (hit.kind === "revenue") return { kind: "revenue", code: hit.code };
  if (hit.kind === "plan") return { kind: "plan", code: hit.code };
  if (hit.kind === "expenditure" && hit.code && hit["用途別_code"]) {
    return { kind: "object", code: `${hit.code}|${hit["用途別_code"]}` };
  }
  return { kind: null, code: null };
}

async function renderSearch(year, data, params, compare) {
  const q = (params.get("q") || "").trim();
  const kind = params.get("kind") || "";
  document.getElementById("q").value = q;
  $app.innerHTML = `<h1>搜尋${q ? "：" + esc(q) : ""}</h1><p class="muted">搜尋中…</p>`;
  if (!q) { $app.innerHTML = `<h1>搜尋</h1><p class="muted">請輸入關鍵字（名稱、說明或編號）。</p>`; return; }
  const { ms } = await getSearch();
  let hits = ms.search(q).filter((h) => String(h.year) === String(year));
  const kinds = { revenue: "歲入明細", expenditure: "歲出明細", plan: "工作計畫", summary: "總表" };
  const counts = {};
  hits.forEach((h) => { counts[h.kind] = (counts[h.kind] || 0) + 1; });
  const shown = kind ? hits.filter((h) => h.kind === kind) : hits;
  const chips = [`<a class="chip ${kind ? "" : "on"}" href="${href(year, "搜尋", { q })}">全部 ${hits.length}</a>`]
    .concat(Object.keys(kinds).filter((k) => counts[k]).map((k) => `<a class="chip ${kind === k ? "on" : ""}" href="${href(year, "搜尋", { q, kind: k })}">${kinds[k]} ${counts[k]}</a>`));
  const list = shown.slice(0, 100).map((h) => {
    let link = "";
    if (h.kind === "revenue") { const p = findPath(data.revenue.hierarchy, REV_LEVELS, h.code); if (p) link = href(year, "歲入", p); }
    else if (h.kind === "plan" || h.kind === "expenditure") {
      const p = findPath(data.expenditure.hierarchy, EXP_LEVELS, h.code);
      if (p) { if (h.kind === "expenditure" && h["用途別_code"]) p["用途別"] = h["用途別_code"]; link = href(year, "歲出", p); }
    }
    const cmpTarget = getSearchCompareTarget(h);
    const cmpBtn = compareBtn(year, compare, cmpTarget.kind, cmpTarget.code);
    const title = esc(h.name);
    return `<div class="hit"><div class="t">${link ? `<a href="${esc(link)}">${title}</a>` : title} <span class="muted">${esc(kinds[h.kind] || h.kind)} ${esc(h.code)}</span>${h.unresolved ? ' <span class="badge">⚠ 未解決</span>' : ""}${cmpBtn}</div>
      <div class="note">${esc((h.text || "").slice(0, 140))}</div><div>${fmt(h.amount_元)} 元　${esc(pageText(h))}${h.dept ? "　" + esc(h.dept) : ""}</div></div>`;
  });
  $app.innerHTML = `<h1>搜尋：${esc(q)}</h1><div class="filters">${chips.join("")}</div>${list.join("") || '<p class="muted">沒有符合的結果。</p>'}${shown.length > 100 ? `<p class="note">只顯示前 100 筆，共 ${shown.length} 筆，請加上更多關鍵字。</p>` : ""}`;
}

// ---------- 跨年度比較 ----------
function renderCompare(year, data, params, compare, pair, defPair) {
  // 只有指定了非預設比較對時才把 pair 帶進連結，預設情況網址維持原樣
  const cmpHref = (kind, code) => href(year, "比較", pair && pair !== defPair ? { kind, code, pair } : { kind, code });
  const kind = (params.get("kind") || "").trim();
  const code = (params.get("code") || "").trim();
  if (!compare || !compare.entries) {
    $app.innerHTML = `<p class="warn">比較功能不可用（找不到比較資料）。</p>`;
    return;
  }
  const key = `${kind}:${code}`;
  const entry = compare.entries[key];
  if (!entry) {
    $app.innerHTML = `<p class="warn">找不到比較項目：${esc(kind)} ${esc(code)}</p>`;
    return;
  }

  const y1 = String(compare.from_year ?? compare.years[0]);
  const y2 = String(compare.to_year ?? compare.years[1]);
  const section = entry.kind === "revenue" ? "歲入" : "歲出";

  // 麵包屑：回分類頁 + 父層比較鏈
  const chain = [];
  let cur = entry;
  while (cur) {
    chain.unshift(cur);
    cur = cur.parent_key ? compare.entries[cur.parent_key] : null;
  }
  const crumbs = [`<a href="${href(year, section, {})}">${esc(section)}</a>`];
  chain.forEach((item, idx) => {
    const label = `${item.display_name || item.code}`;
    if (idx === chain.length - 1) {
      crumbs.push(`<strong>${esc(label)}（比較）</strong>`);
    } else {
      crumbs.push(`<a href="${esc(cmpHref(item.kind, item.code))}">${esc(label)}</a>`);
    }
  });

  // 若目前導覽年度有此項目且在階層內，提供返回該年度下鑽頁的連結
  let drillLink = "";
  if (entry.in_hierarchy) {
    if (entry.kind === "revenue") {
      const p = findPath(data.revenue.hierarchy, REV_LEVELS, entry.code);
      if (p) drillLink = href(year, "歲入", p);
    } else if (entry.kind === "plan") {
      const p = findPath(data.expenditure.hierarchy, EXP_LEVELS, entry.code);
      if (p) drillLink = href(year, "歲出", p);
    } else if (entry.kind === "object") {
      const [pCode, uCode] = entry.code.split("|");
      const p = findPath(data.expenditure.hierarchy, EXP_LEVELS, pCode);
      if (p && uCode) {
        p["用途別"] = uCode;
        drillLink = href(year, "歲出", p);
      }
    }
  }

  const a1 = entry.amount_元?.[y1] ?? null;
  const a2 = entry.amount_元?.[y2] ?? null;
  const p1 = entry.page?.[y1] ?? null;
  const p2 = entry.page?.[y2] ?? null;
  const n1 = entry.name?.[y1] ?? null;
  const n2 = entry.name?.[y2] ?? null;

  const statusBadge =
    entry.status === `only_${y1}`
      ? ` <span class="badge">僅${esc(y1)}</span>`
      : entry.status === `only_${y2}`
        ? ` <span class="badge">僅${esc(y2)}</span>`
        : "";
  const unresolvedBadge = entry.unresolved ? ' <span class="badge">⚠ 未解決</span>' : "";
  const nameNote = entry.name_changed
    ? `<div class="note">${esc(y1)} 名稱：${esc(n1)} → ${esc(y2)} 名稱：${esc(n2)}</div>`
    : "";
  const hierarchyNote = !entry.in_hierarchy
    ? `<p class="note">此項目未掛入總表階層，僅見於明細表。</p>`
    : "";

  const selfRow = `<tr>
    <td><strong>${esc(entry.display_name)}</strong>${statusBadge}${unresolvedBadge}<div class="note">${esc(entry.level)} ${esc(entry.code)}${entry.dept ? "　" + esc(entry.dept) : ""}</div>${nameNote}</td>
    <td class="num">${a1 !== null ? fmt(a1) : `僅${esc(y2)}`}</td>
    <td class="num">${a2 !== null ? fmt(a2) : `僅${esc(y1)}`}</td>
    <td class="num">${esc(fmtDiff(entry.diff_元))}</td>
    <td class="num">${esc(fmtPct(entry, y1, y2))}</td>
    <td class="num">${p1 ? esc(pageText(p1)) : "—"}</td>
    <td class="num">${p2 ? esc(pageText(p2)) : "—"}</td>
  </tr>`;

  const childItems = (entry.children || []).map((ck) => compare.entries[ck]).filter(Boolean);
  let childrenSection = "";
  if (childItems.length > 0) {
    const childRows = childItems.map((ch) => {
      const ca1 = ch.amount_元?.[y1] ?? null;
      const ca2 = ch.amount_元?.[y2] ?? null;
      const cp1 = ch.page?.[y1] ?? null;
      const cp2 = ch.page?.[y2] ?? null;
      const cn1 = ch.name?.[y1] ?? null;
      const cn2 = ch.name?.[y2] ?? null;
      const chStatusBadge =
        ch.status === `only_${y1}`
          ? ` <span class="badge">僅${esc(y1)}</span>`
          : ch.status === `only_${y2}`
            ? ` <span class="badge">僅${esc(y2)}</span>`
            : "";
      const chUnresolved = ch.unresolved ? ' <span class="badge">⚠ 未解決</span>' : "";
      const chNameDiff = ch.name_changed
        ? `<div class="note">${esc(y1)}：${esc(cn1)} → ${esc(y2)}：${esc(cn2)}</div>`
        : "";
      const to = cmpHref(ch.kind, ch.code);
      return `<tr class="click" data-to="${esc(to)}">
        <td><a href="${esc(to)}">${esc(ch.display_name)}</a>${chStatusBadge}${chUnresolved}<div class="note">${esc(ch.level)} ${esc(ch.code)}</div>${chNameDiff}</td>
        <td class="num">${ca1 !== null ? fmt(ca1) : `僅${esc(y2)}`}</td>
        <td class="num">${ca2 !== null ? fmt(ca2) : `僅${esc(y1)}`}</td>
        <td class="num">${esc(fmtDiff(ch.diff_元))}</td>
        <td class="num">${esc(fmtPct(ch, y1, y2))}</td>
        <td class="num">${cp1 ? esc(pageText(cp1)) : "—"}</td>
        <td class="num">${cp2 ? esc(pageText(cp2)) : "—"}</td>
      </tr>`;
    });
    childrenSection = `
      <h2>下一層項目對照（依編號合併，共 ${childItems.length} 項）</h2>
      <div class="tablewrap">
        <table>
          <thead>
            <tr>
              <th>名稱 / 編號</th>
              <th class="num">${esc(y1)} 年度（元）</th>
              <th class="num">${esc(y2)} 年度（元）</th>
              <th class="num">差額（元）</th>
              <th class="num">增減 %</th>
              <th class="num">${esc(y1)} 頁碼</th>
              <th class="num">${esc(y2)} 頁碼</th>
            </tr>
          </thead>
          <tbody>${childRows.join("")}</tbody>
        </table>
      </div>`;
  } else {
    childrenSection = `<p class="note">此項目（${esc(entry.level)}）無下一層比較子項。</p>`;
  }

  $app.innerHTML = `
    <div class="crumbs">${crumbs.join('<span class="sep">›</span>')}</div>
    <h1>${esc(entry.display_name)} <span class="muted">${esc(entry.level)} ${esc(entry.code)}（${esc(y1)} vs ${esc(y2)} 比較）</span>${statusBadge}${unresolvedBadge}</h1>
    ${drillLink ? `<p><a class="btn btn-sm" href="${esc(drillLink)}">返回 ${esc(year)} 年度此項明細</a></p>` : ""}
    ${hierarchyNote}
    <div class="tablewrap">
      <table>
        <thead>
          <tr>
            <th>本項摘要</th>
            <th class="num">${esc(y1)} 年度（元）</th>
            <th class="num">${esc(y2)} 年度（元）</th>
            <th class="num">差額（元）</th>
            <th class="num">增減 %</th>
            <th class="num">${esc(y1)} 頁碼</th>
            <th class="num">${esc(y2)} 頁碼</th>
          </tr>
        </thead>
        <tbody>${selfRow}</tbody>
      </table>
    </div>
    ${childrenSection}`;
  $app.querySelectorAll("tr[data-to]").forEach((tr) => tr.addEventListener("click", () => { location.hash = tr.dataset.to; }));
}

function bindFind(year, data) {
  $app.querySelectorAll("a[data-find]").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const p = findPath(data.revenue.hierarchy, REV_LEVELS, a.dataset.find);
      if (p) location.hash = href(year, "歲入", p);
    })
  );
}

document.getElementById("searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (!$yearSel.value) return; // 年度資料尚未載入
  location.hash = href($yearSel.value, "搜尋", { q });
});
window.addEventListener("hashchange", render);
render();
