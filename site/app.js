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

// ---------- 資料備註 ----------
const MEMO_TYPES = {
  print_typo: "原書錯字",
  print_inconsistent: "原書前後不一致",
  print_layout: "原書版面",
  data_gap: "資料缺口",
};
const MEMO_STATUSES = {
  confirmed: "已對照原圖",
  pending_publisher: "待公所確認",
};
const hasMemos = (index, year) => Boolean(index && (index.memo_years || []).map(String).includes(String(year)));

// 備註資料由單一 data/memos.json 載入；失敗（404、網路、JSON 錯誤）快取為 null，不重複請求也不中斷頁面。
let memosPromise = null;
async function fetchMemosFile() {
  if (!memosPromise) {
    memosPromise = fetch("data/memos.json")
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return memosPromise;
}

async function getMemos(index, year) {
  if (year !== undefined && year !== null) {
    if (!hasMemos(index, year)) return null;
    const data = await fetchMemosFile();
    return data && data.years ? (data.years[String(year)] || []) : null;
  }
  if (!index || !(index.memo_years || []).length) return null;
  return fetchMemosFile();
}

/**
 * 純函式：將 print_typo 類備註的 suggested_text 併入對應搜尋文件的 alias 欄位。
 * @param {Array<Object>} docs - search.json 的文件陣列（不會被修改）
 * @param {Object|Array<Object>|null} memos - memos.json 物件（含 years 鍵）或已展平的備註陣列
 * @returns {Array<Object>} 新的文件陣列；無對應 print_typo 備註的文件保持原物件且不新增 alias 鍵
 */
function mergeMemoAliases(docs, memos) {
  if (!Array.isArray(docs)) return [];
  const list = Array.isArray(memos)
    ? memos
    : memos && memos.years
      ? Object.values(memos.years).flat()
      : [];
  const aliasById = new Map();
  for (const m of list) {
    if (!m || m.type !== "print_typo" || !m.suggested_text) continue;
    const sid = m.target && m.target.search_id;
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

// 各畫面掛載點的備註篩選函式
function memosForRevenueItem(memos, code, itemSeq) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "revenue" && m.target.code === code && Number(m.target.item_seq) === Number(itemSeq));
}
function memosForRevenueFine(memos, code) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "revenue" && m.target.code === code);
}
function memosForExpenditureItem(memos, planCode, useCode, itemSeq) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "expenditure" && m.target.plan_code === planCode && m.target["用途別_code"] === useCode && Number(m.target.item_seq) === Number(itemSeq));
}
function memosForExpenditureUse(memos, planCode, useCode) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "expenditure" && m.target.plan_code === planCode && m.target["用途別_code"] === useCode);
}
function memosForPlanOnly(memos, planCode) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "plan" && m.target.plan_code === planCode);
}
function memosForPlan(memos, planCode) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && (m.target.kind === "plan" || m.target.kind === "expenditure") && m.target.plan_code === planCode);
}
function memosForSearchDoc(memos, docId) {
  if (!memos || !memos.length || !docId) return [];
  return memos.filter((m) => m.target && m.target.search_id === docId);
}
function memosForRefCell(memos, page, r, c) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "reference" && Number(m.target.page) === Number(page) && Number(m.target.row) === Number(r) && Number(m.target.col) === Number(c));
}
function memosForRefPage(memos, page) {
  if (!memos || !memos.length) return [];
  return memos.filter((m) => m.target && m.target.kind === "page" && Number(m.target.page) === Number(page));
}

function memoBtn(memos) {
  if (!memos || !memos.length) return "";
  const ids = memos.map((m) => m.memo_id).join(",");
  const label = memos.length === 1 ? `備註 ${memos[0].memo_id}` : `備註 ${memos[0].memo_id} 等 ${memos.length} 筆`;
  return ` <button type="button" class="memo-btn" data-memo="${esc(ids)}" aria-label="${esc(label)}" title="${esc(label)}">ⓘ</button>`;
}

function renderMemoFields(m) {
  const ev = m.evidence && String(m.evidence).startsWith("docs/evidence/") ? String(m.evidence) : "";
  const evHtml = ev
    ? `<div class="memo-evidence"><img src="${esc(ev.slice("docs/".length))}" alt="證據截圖 ${esc(m.memo_id)}" loading="lazy"><div class="memo-evidence-path note">${esc(ev)}</div></div>`
    : "";
  return `
    <dl class="memo-dl">
      <dt>原書印刷</dt><dd><code class="memo-code">${m.printed_text ? esc(m.printed_text) : "—"}</code></dd>
      <dt>資料目前存的</dt><dd><code class="memo-code">${m.data_text ? esc(m.data_text) : "—"}</code></dd>
      ${m.suggested_text ? `<dt>建議寫法</dt><dd><code class="memo-code">${esc(m.suggested_text)}</code></dd>` : ""}
      <dt>說明</dt><dd>${esc(m.note)}</dd>
      <dt>來源 PDF</dt><dd>${esc(m.pdf_file)}（第 ${esc(m.pdf_page)} 頁）</dd>
      <dt>核對</dt><dd>${esc(m.verified_method)}（${esc(m.verified_on)}）</dd>
      <dt>狀態</dt><dd>${esc(MEMO_STATUSES[m.status] || m.status)}</dd>
    </dl>${evHtml}`;
}

let activeMemoKey = null;
let currentMemoMap = new Map();
let memoPanelBound = false;

function handleEvidenceImgError(e) {
  const t = e && e.target;
  if (t && t.tagName === "IMG" && t.parentElement && t.parentElement.classList && t.parentElement.classList.contains("memo-evidence")) {
    t.remove();
  }
}

function getMemoPanel() {
  let el = document.getElementById("memoPanel");
  if (!el && typeof document.createElement === "function" && document.body) {
    el = document.createElement("aside");
    el.id = "memoPanel";
    el.className = "memo-panel";
    el.hidden = true;
    el.setAttribute("aria-label", "資料備註詳情");
    document.body.appendChild(el);
  }
  if (el && !memoPanelBound && typeof el.addEventListener === "function") {
    memoPanelBound = true;
    el.addEventListener("click", (e) => {
      if (e && e.target && typeof e.target.closest === "function" && e.target.closest(".memo-close")) {
        closeMemoPanel();
      }
    });
    el.addEventListener("error", handleEvidenceImgError, true);
  }
  return el || null;
}

function closeMemoPanel() {
  const panel = getMemoPanel();
  if (panel) {
    panel.hidden = true;
    panel.innerHTML = "";
  }
  activeMemoKey = null;
}

function openMemoPanel(idsStr) {
  const panel = getMemoPanel();
  if (!panel) return;
  if (!panel.hidden && activeMemoKey === idsStr) {
    closeMemoPanel();
    return;
  }
  const ids = String(idsStr || "").split(",").filter(Boolean);
  const items = ids.map((id) => currentMemoMap.get(id)).filter(Boolean);
  if (!items.length) {
    closeMemoPanel();
    return;
  }
  activeMemoKey = idsStr;
  const title = items.length === 1 ? `資料備註：${esc(items[0].memo_id)}` : `資料備註（共 ${items.length} 筆）`;
  const body = items.map((m) => `
    <div class="memo-item">
      <div class="memo-meta">
        <strong>${esc(m.memo_id)}</strong>
        <span class="badge">${esc(MEMO_TYPES[m.type] || m.type)}</span>
        <span class="muted">p${esc(m.page)}</span>
      </div>
      ${renderMemoFields(m)}
    </div>`).join("");
  panel.innerHTML = `<div class="memo-panel-head"><h3>${title}</h3><button type="button" class="memo-close" aria-label="關閉">✕</button></div>${body}`;
  panel.hidden = false;
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
  closeMemoPanel();
  try {
    const index = await loadJson("data/index.json");
    const r = parseHash();
    const year = String(r.year && /^\d+$/.test(r.year) ? r.year : index.default_year);
    if (!index.years.map(String).includes(year)) {
      $app.innerHTML = `<p class="warn">找不到年度 ${esc(year)}。</p>`;
      return;
    }
    const pair = pickPair(index, year, r.view === "比較" ? r.params : null);
    const [data, compare, yearMemos] = await Promise.all([
      loadJson(`data/${year}.json`),
      getCompare(pair),
      getMemos(index, year),
    ]);
    currentMemoMap = new Map((yearMemos || []).map((m) => [m.memo_id, m]));
    setNav(r.view, year, index);
    if (r.view === "歲入" || r.view === "歲出") renderDrill(year, r.view, data, r.params, compare, yearMemos);
    else if (r.view === "搜尋") await renderSearch(year, data, r.params, compare, index, yearMemos);
    else if (r.view === "比較") renderCompare(year, data, r.params, compare, pair, defaultPair(index, year));
    else if (r.view === "參考表") {
      if (!hasReference(index, year)) { location.replace(href(year, "總覽")); return; } // 該年度沒有參考表：導向總覽
      await renderReference(year, r.params, yearMemos);
    }
    else if (r.view === "備註") {
      if (!hasMemos(index, year)) { location.replace(href(year, "總覽")); return; } // 該年度沒有備註：導向總覽
      renderMemosPage(year, data, r.params, yearMemos);
    }
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
  if (view === "參考表") {
    // 切到沒有參考表的年度時導向該年度總覽；有參考表的年度保留 p
    loadJson("data/index.json").then((index) => {
      if (!hasReference(index, $yearSel.value)) location.hash = href($yearSel.value, "總覽");
      else location.hash = href($yearSel.value, "參考表", r.params.get("p") ? { p: r.params.get("p") } : {});
    }).catch(() => { location.hash = href($yearSel.value, "總覽"); });
    return;
  }
  if (view === "備註") {
    // 切到沒有備註的年度時導向該年度總覽；有備註的年度保留在備註頁並清除篩選參數
    loadJson("data/index.json").then((index) => {
      if (!hasMemos(index, $yearSel.value)) location.hash = href($yearSel.value, "總覽");
      else location.hash = href($yearSel.value, "備註", {});
    }).catch(() => { location.hash = href($yearSel.value, "總覽"); });
    return;
  }
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
  // 「參考表」只有該年度有參考表資料時才顯示
  // 瀏覽器可能快取了舊版 index.html（沒有這個連結）卻載入新版 app.js，找不到時略過，不可丟錯
  const refA = document.querySelector('.nav a[data-nav="ref"]');
  if (refA) {
    refA.setAttribute("href", href(year, "參考表"));
    refA.hidden = !hasReference(index, year);
  }
  const memoA = document.querySelector('.nav a[data-nav="memo"]');
  if (memoA) {
    memoA.setAttribute("href", href(year, "備註"));
    memoA.hidden = !hasMemos(index, year);
  }
  document.querySelectorAll(".nav a").forEach((a) => {
    const on = (a.dataset.nav === "memo" && view === "備註") || (a.dataset.nav === "ref" && view === "參考表") || (a.dataset.nav === "exp" && view === "歲出") || (a.dataset.nav === "rev" && view === "歲入") || (a.dataset.nav === "overview" && view === "總覽");
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

function renderDrill(year, view, data, params, compare, yearMemos) {
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
  if (cur && (cur.level === "細目" || cur.level === "用途別")) body = detailTable(cur, view, yearMemos);
  else body = childTable(year, view, cur ? cur.children : root.hierarchy, acc, parentAmt, yearMemos);
  const note = cur && cur.unresolved
    ? `<div class="warn"><strong>未解決</strong>：${esc(cur.note || cur.unresolved_note || "此項資料待核對")}</div>`
    : "";
  const cmpTarget = getDrillCompareTarget(view, cur);
  const cmpBtn = compareBtn(year, compare, cmpTarget.kind, cmpTarget.code);
  const headMemoBtn = cur && cur.level === "工作計畫" ? memoBtn(memosForPlanOnly(yearMemos, cur.code)) : "";
  const head = cur
    ? `<h1>${esc(cur.name)} <span class="muted">${esc(cur.level)}${cur.code ? " " + esc(cur.code) : ""}</span>${cmpBtn}${headMemoBtn}</h1>
       <p>預算 <strong>${fmt(cur.amount_元)}</strong> 元　${esc(pageText(cur))}${cur.dept ? "　承辦：" + esc(cur.dept) : ""}</p>`
    : `<h1>${esc(year)} 年度${esc(view)}　<span class="muted">${fmt(root.total_元)} 元</span></h1>`;
  $app.innerHTML = `<div class="crumbs">${crumbs.join('<span class="sep">›</span>')}</div>${missing ? `<p class="warn">找不到：${esc(missing)}</p>` : ""}${head}${note}${body}`;
  $app.querySelectorAll("tr[data-to]").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e && e.target && typeof e.target.closest === "function" && e.target.closest(".memo-btn")) return;
    location.hash = tr.dataset.to;
  }));
}

function childTable(year, view, nodes, acc, parentAmt, yearMemos) {
  const sec = SECTIONS[view];
  const rows = nodes.map((n) => {
    const nextLevel = sec.levels.find(([lvl]) => lvl === n.level);
    const to = nextLevel ? href(year, view, { ...acc, [nextLevel[1]]: nodeKey(n) }) : "";
    const pct = parentAmt ? Math.max(0, Math.min(100, (n.amount_元 / parentAmt) * 100)) : 0;
    const flag = n.unresolved ? ' <span class="badge" title="明細加總與表頭不一致，待核對">⚠ 未解決</span>' : "";
    let rowMemos = [];
    if (n.level === "細目") rowMemos = memosForRevenueFine(yearMemos, n.code);
    else if (n.level === "用途別") rowMemos = memosForExpenditureUse(yearMemos, n.plan_code, n.code);
    else if (n.level === "工作計畫") rowMemos = memosForPlan(yearMemos, n.code);
    const mBtn = memoBtn(rowMemos);
    return `<tr class="click" data-to="${esc(to)}"><td><a href="${esc(to)}">${esc(n.name)}</a>${flag}${mBtn}<div class="note">${esc(n.level)}${n.code ? " " + esc(n.code) : ""}${n.dept ? "　" + esc(n.dept) : ""}</div></td>
      <td class="num">${fmt(n.amount_元)}<div class="bar"><i style="width:${pct.toFixed(1)}%"></i></div></td>
      <td class="num hide-sm">${pct.toFixed(1)}%</td><td class="num">${esc(pageText(n))}</td></tr>`;
  });
  return `<div class="tablewrap"><table><thead><tr><th>名稱</th><th class="num">預算（元）</th><th class="num hide-sm">占比</th><th class="num">頁碼</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

function detailTable(node, view, yearMemos) {
  const items = node.children || [];
  const isExp = view === "歲出";
  const rows = items.map((it) => {
    const itemMemos = isExp
      ? memosForExpenditureItem(yearMemos, it.plan_code, it["用途別_code"], it.item_seq)
      : memosForRevenueItem(yearMemos, it.code, it.item_seq);
    return `<tr><td>${esc(isExp ? it["說明"] : it.note || it.name)}${it.unresolved ? ' <span class="badge">⚠</span>' : ""}${memoBtn(itemMemos)}</td>
    <td class="hide-sm">${esc(it.unit)}</td><td class="num hide-sm">${esc(it.qty)}</td><td class="num hide-sm">${fmt(it.unit_price)}</td><td class="num">${fmt(it.amount_元)}</td>
    ${isExp ? `<td class="hide-sm">${esc(it["經費來源"])}</td>` : ""}<td class="num">p${esc(it.page)}</td></tr>`;
  });
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

async function getSearch(index) {
  if (searchIndex) return searchIndex;
  const [docs, allMemos] = await Promise.all([
    loadJson("data/search.json"),
    getMemos(index),
  ]);
  const indexedDocs = mergeMemoAliases(docs, allMemos);
  const ms = new MiniSearch({
    fields: ["name", "text", "code", "dept", "alias"],
    storeFields: ["kind", "year", "code", "name", "text", "page", "page_start", "page_end", "amount_元", "dept", "unresolved", "用途別_code"],
    tokenize,
    searchOptions: { tokenize, combineWith: "AND", boost: { name: 2 } },
  });
  ms.addAll(indexedDocs);
  searchIndex = { ms, docs: indexedDocs };
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

async function renderSearch(year, data, params, compare, index, yearMemos) {
  const q = (params.get("q") || "").trim();
  const kind = params.get("kind") || "";
  document.getElementById("q").value = q;
  $app.innerHTML = `<h1>搜尋${q ? "：" + esc(q) : ""}</h1><p class="muted">搜尋中…</p>`;
  if (!q) { $app.innerHTML = `<h1>搜尋</h1><p class="muted">請輸入關鍵字（名稱、說明或編號）。</p>`; return; }
  const { ms } = await getSearch(index);
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
    const mBtn = memoBtn(memosForSearchDoc(yearMemos, h.id));
    const title = esc(h.name);
    return `<div class="hit"><div class="t">${link ? `<a href="${esc(link)}">${title}</a>` : title} <span class="muted">${esc(kinds[h.kind] || h.kind)} ${esc(h.code)}</span>${h.unresolved ? ' <span class="badge">⚠ 未解決</span>' : ""}${cmpBtn}${mBtn}</div>
      <div class="note">${esc((h.text || "").slice(0, 140))}</div><div>${fmt(h.amount_元)} 元　${esc(pageText(h))}${h.dept ? "　" + esc(h.dept) : ""}</div></div>`;
  });
  $app.innerHTML = `<h1>搜尋：${esc(q)}</h1><div class="filters">${chips.join("")}</div>${list.join("") || '<p class="muted">沒有符合的結果。</p>'}${shown.length > 100 ? `<p class="note">只顯示前 100 筆，共 ${shown.length} 筆，請加上更多關鍵字。</p>` : ""}`;
}

// ---------- 參考表 ----------
const hasReference = (index, year) => (index.reference_years || []).map(String).includes(String(year));

function referenceNotFound(msg) {
  $app.innerHTML = `<p class="warn">找不到參考表：${esc(msg)}</p>`;
}

async function renderReference(year, params, yearMemos) {
  let ref;
  try {
    ref = await loadJson(`data/reference_${year}.json`);
  } catch (e) {
    referenceNotFound(`${year} 年度的參考表資料載入失敗。`);
    return;
  }
  const tables = (ref && ref.tables) || [];
  if (!tables.length) { referenceNotFound(`${year} 年度沒有參考表資料。`); return; }
  const want = params.get("p");
  const idx = want === null || want === "" ? 0 : tables.findIndex((t) => String(t.page) === want.trim());
  if (idx < 0) { referenceNotFound(`${year} 年度沒有第 ${want} 頁的參考表。`); return; }
  const t = tables[idx];

  // 目次：依 source_table 分組（相鄰頁同名併為一組），顯示頁碼範圍與各頁連結
  const groups = [];
  tables.forEach((tb) => {
    const last = groups[groups.length - 1];
    if (last && last.name === tb.source_table) last.pages.push(tb.page);
    else groups.push({ name: tb.source_table, pages: [tb.page] });
  });
  const toc = groups.map((g) => {
    const s = g.pages[0], e = g.pages[g.pages.length - 1];
    const range = s === e ? `p${s}` : `p${s}–${e}`;
    const links = g.pages.map((pg) => `<a class="chip ${pg === t.page ? "on" : ""}" href="${esc(href(year, "參考表", { p: pg }))}">p${esc(pg)}</a>`).join("");
    return `<li><span class="toc-name">${esc(g.name)}</span> <span class="muted">${esc(range)}</span> <span class="filters">${links}</span></li>`;
  }).join("");

  const prev = tables[idx - 1], next = tables[idx + 1];
  const pager = `<div class="pager">${prev ? `<a class="btn btn-sm" href="${esc(href(year, "參考表", { p: prev.page }))}">‹ 上一頁（p${esc(prev.page)}）</a>` : '<span class="muted">‹ 上一頁</span>'}
    ${next ? `<a class="btn btn-sm" href="${esc(href(year, "參考表", { p: next.page }))}">下一頁（p${esc(next.page)}） ›</a>` : '<span class="muted">下一頁 ›</span>'}</div>`;

  // 依 r、c、rs、cs 還原合併儲存格；顯示文字以 t 為準，不重新格式化
  const byRow = [];
  t.cells.forEach((c) => { (byRow[c.r] = byRow[c.r] || []).push(c); });
  const body = [];
  for (let r = 0; r < t.rows; r++) {
    const tds = (byRow[r] || []).sort((a, b) => a.c - b.c).map((c) => {
      const cellMemos = memosForRefCell(yearMemos, t.page, c.r, c.c);
      const cls = [];
      if (c.v !== null && c.v !== undefined) cls.push("num");
      if (cellMemos.length) cls.push("has-memo");
      return `<td${c.rs > 1 ? ` rowspan="${esc(c.rs)}"` : ""}${c.cs > 1 ? ` colspan="${esc(c.cs)}"` : ""}${cls.length ? ` class="${cls.join(" ")}"` : ""}>${esc(c.t)}${memoBtn(cellMemos)}</td>`;
    }).join("");
    body.push(`<tr>${tds}</tr>`);
  }
  const pageMemos = memosForRefPage(yearMemos, t.page);
  $app.innerHTML = `
    <h1>參考表</h1>
    <p class="note">這是預算書參考表的原樣呈現，儲存格內容依 OCR 轉檔，只套用 data/corrections.csv 登記過的修正；金額單位依各表標示。</p>
    <ul class="toc">${toc}</ul>
    <h2>${esc(t.source_table)}</h2>
    <p>預算書第 ${esc(t.page)} 頁　單位：${t.unit ? esc(t.unit) : "單位請見原書該頁"}${memoBtn(pageMemos)}</p>
    ${t.note ? `<p class="warn">${esc(t.note)}</p>` : ""}
    ${pager}
    <div class="tablewrap ref"><table class="reftable"><tbody>${body.join("")}</tbody></table></div>
    ${pager}`;
}

// ---------- 資料備註頁 ----------
function memoLocationText(m) {
  const t = m.target || {};
  if (m.scope === "revenue_item") return `歲入明細 ${t.code || m.locator}${t.item_seq ? ` 第 ${t.item_seq} 筆` : ""}${m.field ? `（${m.field}）` : ""}`;
  if (m.scope === "expenditure_item") return `歲出明細 ${t.plan_code || ""} / ${t["用途別_code"] || ""}${t.item_seq ? ` 第 ${t.item_seq} 筆` : ""}${m.field ? `（${m.field}）` : ""}`;
  if (m.scope === "plan") return `工作計畫 ${t.plan_code || m.locator}${m.field ? `（${m.field}）` : ""}`;
  if (m.scope === "summary") return `總表 ${t.source_table || ""} — ${t["科目名稱"] || ""}${m.field ? `（${m.field}）` : ""}`;
  if (m.scope === "reference_cell") return `參考表 p${t.page ?? m.page} 第 ${t.row} 列第 ${t.col} 欄`;
  if (m.scope === "page") return `整頁 p${t.page ?? m.page}`;
  return m.locator || "";
}

function memoTargetLink(year, data, m) {
  const t = m.target || {};
  if (t.kind === "revenue" && t.code) {
    const p = findPath(data.revenue.hierarchy, REV_LEVELS, t.code);
    if (p) return href(year, "歲入", p);
  } else if (t.kind === "expenditure" && t.plan_code) {
    const p = findPath(data.expenditure.hierarchy, EXP_LEVELS, t.plan_code);
    if (p) {
      if (t["用途別_code"]) p["用途別"] = t["用途別_code"];
      return href(year, "歲出", p);
    }
  } else if (t.kind === "plan" && t.plan_code) {
    const p = findPath(data.expenditure.hierarchy, EXP_LEVELS, t.plan_code);
    if (p) return href(year, "歲出", p);
  } else if (t.kind === "summary" && t["科目名稱"]) {
    return href(year, "搜尋", { q: t["科目名稱"], kind: "summary" });
  } else if (t.kind === "reference" || t.kind === "page") {
    return href(year, "參考表", { p: t.page ?? m.page });
  }
  return "";
}

function renderMemosPage(year, data, params, yearMemos) {
  const intro = `<p class="note">本頁記錄預算書原件的印刷錯字、前後不一致、版面限制與資料缺口；資料本身依原書保留，不改動原書數字或原文。</p>`;
  if (yearMemos === null) {
    $app.innerHTML = `<h1>${esc(year)} 年度資料備註</h1>${intro}<p class="muted">備註資料無法載入。</p>`;
    return;
  }
  const sorted = [...yearMemos].sort((a, b) => String(a.memo_id).localeCompare(String(b.memo_id)));
  const typeFilter = (params.get("type") || "").trim();
  const pageFilter = (params.get("p") || "").trim();

  const typeCounts = {};
  const pageCounts = {};
  sorted.forEach((m) => {
    typeCounts[m.type] = (typeCounts[m.type] || 0) + 1;
    const pk = String(m.page);
    pageCounts[pk] = (pageCounts[pk] || 0) + 1;
  });

  const mkFilterHref = (nextType, nextPage) => {
    const p = {};
    if (nextType) p.type = nextType;
    if (nextPage) p.p = nextPage;
    return href(year, "備註", p);
  };

  const typeChips = [`<a class="chip ${typeFilter ? "" : "on"}" href="${esc(mkFilterHref("", pageFilter))}">全部 ${sorted.length}</a>`]
    .concat(
      Object.keys(MEMO_TYPES)
        .filter((k) => typeCounts[k])
        .map((k) => `<a class="chip ${typeFilter === k ? "on" : ""}" href="${esc(mkFilterHref(k, pageFilter))}">${esc(MEMO_TYPES[k])} ${typeCounts[k]}</a>`)
    );

  const pages = Object.keys(pageCounts).sort((a, b) => Number(a) - Number(b));
  const pageChips = [`<a class="chip ${pageFilter ? "" : "on"}" href="${esc(mkFilterHref(typeFilter, ""))}">全部頁碼</a>`]
    .concat(
      pages.map((pg) => `<a class="chip ${pageFilter === pg ? "on" : ""}" href="${esc(mkFilterHref(typeFilter, pg))}">p${esc(pg)} ${pageCounts[pg]}</a>`)
    );

  const shown = sorted.filter((m) => {
    if (typeFilter && m.type !== typeFilter) return false;
    if (pageFilter && String(m.page) !== pageFilter) return false;
    return true;
  });

  const cards = shown.map((m) => {
    const locText = memoLocationText(m);
    const link = memoTargetLink(year, data, m);
    const locHtml = link
      ? `<a class="btn btn-sm" href="${esc(link)}">前往：${esc(locText)}</a>`
      : `<span class="muted">${esc(locText)}</span>`;
    return `<article class="memo-card" data-memo-id="${esc(m.memo_id)}">
      <div class="memo-card-head">
        <div class="memo-card-title">
          <strong>${esc(m.memo_id)}</strong>
          <span class="badge">${esc(MEMO_TYPES[m.type] || m.type)}</span>
          <span class="muted">p${esc(m.page)}</span>
        </div>
        <div>${locHtml}</div>
      </div>
      ${renderMemoFields(m)}
    </article>`;
  }).join("");

  $app.innerHTML = `
    <h1>${esc(year)} 年度資料備註</h1>
    ${intro}
    <div class="memo-filter-group"><div class="filters">${typeChips.join("")}</div></div>
    <div class="memo-filter-group"><div class="filters">${pageChips.join("")}</div></div>
    ${cards || '<p class="muted">沒有符合的備註。</p>'}`;
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
  $app.querySelectorAll("tr[data-to]").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e && e.target && typeof e.target.closest === "function" && e.target.closest(".memo-btn")) return;
    location.hash = tr.dataset.to;
  }));
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

$app.addEventListener("click", (e) => {
  const btn = e && e.target && typeof e.target.closest === "function" ? e.target.closest(".memo-btn") : null;
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  openMemoPanel(btn.dataset.memo);
});
$app.addEventListener("error", handleEvidenceImgError, true);
if (typeof document.addEventListener === "function") {
  document.addEventListener("keydown", (e) => {
    if (e && e.key === "Escape") closeMemoPanel();
  });
}

document.getElementById("searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (!$yearSel.value) return; // 年度資料尚未載入
  location.hash = href($yearSel.value, "搜尋", { q });
});
window.addEventListener("hashchange", render);
render();
