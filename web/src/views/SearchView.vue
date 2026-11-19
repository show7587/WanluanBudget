<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { fmtInt, fmtYuan } from "@/data/format";
import { dataSource } from "@/data/source";
import type { IndexData } from "@/data/types";
import { firstQuery } from "@/utils/query";
import {
  buildPathLookup,
  buildSnippet,
  formatPage,
  highlightSegments,
  KIND_FILTERS,
  KIND_LABELS,
  loadSearchEngine,
  matchesKindFilter,
  normalizeKindFilter,
  resolveHitLink,
  type SearchEngine,
  type SearchHit,
  type SearchKindFilter,
  type YearPathLookup,
} from "./search/searchModel";

const PAGE_SIZE = 50;
const EXAMPLE_KEYWORDS = ["遺產稅", "道路", "垃圾", "人事", "獎助"];

const route = useRoute();
const router = useRouter();

const routeYear = computed(() => Number(route.params.year) || 0);

const engine = ref<SearchEngine | null>(null);
const indexData = ref<IndexData | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);

const inputRef = ref<HTMLInputElement | null>(null);
const queryInput = ref(firstQuery(route.query.q) ?? "");
const displayLimit = ref(PAGE_SIZE);

const pathLookups = reactive<Record<number, YearPathLookup>>({});
const loadingYears = new Set<number>();

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const availableYears = computed<number[]>(() => {
  const fromIndex = indexData.value?.years ?? [];
  const fromEngine = engine.value?.years ?? [];
  const merged = Array.from(new Set([...fromIndex, ...fromEngine, ...(routeYear.value ? [routeYear.value] : [])]));
  return merged.filter((y) => y > 0).sort((a, b) => b - a);
});

const activeQuery = computed(() => (firstQuery(route.query.q) ?? "").trim());

const activeKind = computed<SearchKindFilter>(() => normalizeKindFilter(firstQuery(route.query.kind)));

/** y=all 表示全部年度；未指定時預設為目前路由年度 */
const activeYear = computed<string>(() => {
  const raw = firstQuery(route.query.y)?.trim();
  if (raw === "all" || raw === "全部") return "all";
  if (raw && /^\d+$/.test(raw)) return raw;
  return routeYear.value ? String(routeYear.value) : "all";
});

function updateQueryParams(patch: { q?: string; kind?: SearchKindFilter; y?: string }): void {
  const nextQuery: Record<string, string> = {};
  for (const [k, v] of Object.entries(route.query)) {
    const val = firstQuery(v);
    if (val !== undefined) nextQuery[k] = val;
  }

  if ("q" in patch) {
    const trimmed = (patch.q ?? "").trim();
    if (trimmed) nextQuery.q = trimmed;
    else delete nextQuery.q;
  }
  if ("kind" in patch) {
    const k = patch.kind ?? "all";
    if (k !== "all") nextQuery.kind = k;
    else delete nextQuery.kind;
  }
  if ("y" in patch) {
    const y = patch.y ?? "all";
    if (y) nextQuery.y = y;
    else delete nextQuery.y;
  }

  void router.replace({ query: nextQuery });
}

watch(
  () => firstQuery(route.query.q) ?? "",
  (next) => {
    // 只在外部（上一頁、連結）改變 q 時才覆寫；輸入中的尾端空白不能被吃掉
    if (next !== queryInput.value.trim()) queryInput.value = next;
  },
);

watch([activeQuery, activeKind, activeYear], () => {
  displayLimit.value = PAGE_SIZE;
});

function onInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    if (queryInput.value.trim() !== activeQuery.value) {
      updateQueryParams({ q: queryInput.value });
    }
  }, 220);
}

function onSubmit(): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  updateQueryParams({ q: queryInput.value });
}

function clearQuery(): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  queryInput.value = "";
  updateQueryParams({ q: "" });
  inputRef.value?.focus();
}

function applyExample(keyword: string): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
  queryInput.value = keyword;
  updateQueryParams({ q: keyword });
}

function selectKind(kind: SearchKindFilter): void {
  updateQueryParams({ kind });
}

function selectYear(y: string): void {
  updateQueryParams({ y });
}

async function init(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const [eng, idx] = await Promise.all([
      loadSearchEngine(),
      dataSource()
        .index()
        .catch(() => null),
    ]);
    engine.value = eng;
    indexData.value = idx;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void init();
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
});

const rawHits = computed<SearchHit[]>(() => {
  if (!engine.value || !activeQuery.value) return [];
  return engine.value.search(activeQuery.value);
});

const yearFilteredHits = computed<SearchHit[]>(() => {
  if (activeYear.value === "all") return rawHits.value;
  return rawHits.value.filter((h) => String(h.year) === activeYear.value);
});

const filteredHits = computed<SearchHit[]>(() =>
  yearFilteredHits.value.filter((h) => matchesKindFilter(h.kind, activeKind.value)),
);

const visibleHits = computed<SearchHit[]>(() => filteredHits.value.slice(0, displayLimit.value));

const remainingCount = computed(() => Math.max(0, filteredHits.value.length - visibleHits.value.length));

const kindCounts = computed<Record<SearchKindFilter, number>>(() => {
  const counts: Record<SearchKindFilter, number> = { all: 0, 歲入: 0, 歲出: 0, 總表: 0 };
  for (const h of yearFilteredHits.value) {
    counts.all++;
    if (h.kind === "revenue") counts.歲入++;
    else if (h.kind === "expenditure" || h.kind === "plan") counts.歲出++;
    else if (h.kind === "summary") counts.總表++;
  }
  return counts;
});

const yearCounts = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = { all: 0 };
  for (const y of availableYears.value) counts[String(y)] = 0;
  for (const h of rawHits.value) {
    if (!matchesKindFilter(h.kind, activeKind.value)) continue;
    counts.all++;
    const key = String(h.year);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
});

async function ensureYearLookup(y: number): Promise<void> {
  if (!y || pathLookups[y] || loadingYears.has(y)) return;
  loadingYears.add(y);
  try {
    const yd = await dataSource().year(y);
    pathLookups[y] = buildPathLookup(yd);
  } catch {
    // 年度階層資料載入失敗時仍可退回基本路徑連結
  } finally {
    loadingYears.delete(y);
  }
}

// 點擊結果時才載入該年度的階層資料來算完整路徑（避免「全部年度」搜尋一次抓所有年度的 JSON）
async function onHitClick(e: MouseEvent, hit: SearchHit): Promise<void> {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  await ensureYearLookup(Number(hit.year));
  const link = getLink(hit);
  if (link) void router.push(link.to);
}

const statusSummary = computed(() => {
  if (!activeQuery.value) return "";
  const yearLabel = activeYear.value === "all" ? "全部年度" : `${activeYear.value} 年度`;
  const kindLabel = activeKind.value === "all" ? "全部分類" : activeKind.value;
  return `「${activeQuery.value}」在 ${yearLabel}／${kindLabel} 共找到 ${fmtInt(filteredHits.value.length)} 筆結果`;
});

function showMore(): void {
  displayLimit.value += PAGE_SIZE;
}

function getLink(hit: SearchHit) {
  return resolveHitLink(hit, pathLookups[hit.year]);
}

function getSnippetSegments(hit: SearchHit) {
  const snippet = buildSnippet(hit.text, activeQuery.value, 160);
  return highlightSegments(snippet, activeQuery.value);
}

function getTitleSegments(hit: SearchHit) {
  return highlightSegments(hit.name, activeQuery.value);
}
</script>

<template>
  <div class="page search-page">
    <header class="page-head">
      <h1 class="page-title">搜尋預算項目</h1>
      <p class="muted desc">
        可搜尋歲入、歲出工作計畫、用途別明細與總表的名稱、說明、科目編號或承辦機關。金額單位：元。
      </p>
    </header>

    <section class="card search-card" aria-label="搜尋條件">
      <form class="search-form" role="search" aria-label="搜尋預算資料" @submit.prevent="onSubmit">
        <label class="sr-only" for="budget-search-input">輸入搜尋關鍵字</label>
        <div class="input-row">
          <input
            id="budget-search-input"
            ref="inputRef"
            v-model="queryInput"
            class="search-input"
            type="search"
            inputmode="search"
            autocomplete="off"
            placeholder="輸入關鍵字（例如：遺產稅、道路、垃圾、33120010101）"
            @input="onInput"
          />
          <button class="btn primary" type="submit">搜尋</button>
          <button v-if="queryInput" class="btn" type="button" @click="clearQuery">清除</button>
        </div>
      </form>

      <div class="filter-rows">
        <div class="filter-group" role="group" aria-label="依年度篩選">
          <span class="filter-label muted">年度：</span>
          <button
            class="btn"
            type="button"
            :aria-pressed="activeYear === 'all'"
            @click="selectYear('all')"
          >
            全部年度<template v-if="activeQuery">（{{ fmtInt(yearCounts.all ?? 0) }}）</template>
          </button>
          <button
            v-for="y in availableYears"
            :key="y"
            class="btn"
            type="button"
            :aria-pressed="activeYear === String(y)"
            @click="selectYear(String(y))"
          >
            {{ y }} 年度<template v-if="activeQuery">（{{ fmtInt(yearCounts[String(y)] ?? 0) }}）</template>
          </button>
        </div>

        <div class="filter-group" role="group" aria-label="依預算種類篩選">
          <span class="filter-label muted">種類：</span>
          <button
            v-for="f in KIND_FILTERS"
            :key="f.key"
            class="btn"
            type="button"
            :aria-pressed="activeKind === f.key"
            @click="selectKind(f.key)"
          >
            {{ f.label }}<template v-if="activeQuery">（{{ fmtInt(kindCounts[f.key] ?? 0) }}）</template>
          </button>
        </div>
      </div>
    </section>

    <div v-if="loading" class="card muted" role="status" aria-live="polite">
      載入搜尋索引中…
    </div>

    <div v-else-if="error" class="error-box" role="alert">
      <strong>無法載入搜尋索引</strong>
      <p class="muted err-msg">{{ error }}</p>
      <button class="btn retry-btn" type="button" @click="init">重新載入</button>
    </div>

    <section v-else-if="!activeQuery" class="card empty-state" aria-label="搜尋提示">
      <p class="empty-title">請輸入關鍵字開始搜尋</p>
      <p class="muted empty-desc">
        支援中文詞彙、科目編號與承辦機關；多個關鍵字以空白分隔（須同時符合）。
      </p>
      <div class="examples" role="group" aria-label="常用關鍵字範例">
        <span class="filter-label muted">試試看：</span>
        <button
          v-for="kw in EXAMPLE_KEYWORDS"
          :key="kw"
          class="btn"
          type="button"
          @click="applyExample(kw)"
        >
          {{ kw }}
        </button>
      </div>
    </section>

    <template v-else>
      <p class="status-line muted" role="status" aria-live="polite">
        {{ statusSummary }}
        <template v-if="filteredHits.length > visibleHits.length">
          （目前顯示前 {{ fmtInt(visibleHits.length) }} 筆）
        </template>
      </p>

      <div v-if="!filteredHits.length" class="card empty-state" role="status">
        <p class="empty-title">找不到符合「{{ activeQuery }}」的結果</p>
        <p class="muted empty-desc">
          請嘗試縮短關鍵字、改用同義詞，或放寬年度與種類篩選條件。
        </p>
        <div v-if="rawHits.length > 0" class="recovery-actions">
          <button
            v-if="activeYear !== 'all' && (yearCounts.all ?? 0) > 0"
            class="btn primary"
            type="button"
            @click="selectYear('all')"
          >
            改搜全部年度（{{ fmtInt(yearCounts.all ?? 0) }} 筆）
          </button>
          <button
            v-if="activeKind !== 'all' && kindCounts.all > 0"
            class="btn"
            type="button"
            @click="selectKind('all')"
          >
            改搜全部分類（{{ fmtInt(kindCounts.all) }} 筆）
          </button>
        </div>
      </div>

      <ol v-else class="hit-list" aria-label="搜尋結果列表">
        <li v-for="hit in visibleHits" :key="hit.id" class="card hit-card">
          <article class="hit-article">
            <div class="hit-head">
              <h2 class="hit-title">
                <a v-if="getLink(hit)" :href="router.resolve(getLink(hit)!.to).href" class="hit-title-link" @click="onHitClick($event, hit)">
                  <template v-for="(seg, idx) in getTitleSegments(hit)" :key="idx">
                    <mark v-if="seg.hit" class="hl">{{ seg.text }}</mark>
                    <template v-else>{{ seg.text }}</template>
                  </template>
                </a>
                <template v-else>
                  <template v-for="(seg, idx) in getTitleSegments(hit)" :key="idx">
                    <mark v-if="seg.hit" class="hl">{{ seg.text }}</mark>
                    <template v-else>{{ seg.text }}</template>
                  </template>
                </template>
              </h2>

              <p class="hit-amount num">
                {{ typeof hit.amount_元 === "number" ? fmtYuan(hit.amount_元) : "—" }}
              </p>
            </div>

            <ul class="hit-meta" aria-label="項目資訊">
              <li>
                <span class="tag kind-tag" :data-kind="hit.kind">{{ KIND_LABELS[hit.kind] ?? hit.kind }}</span>
              </li>
              <li>
                <span class="tag">{{ hit.year }} 年度</span>
              </li>
              <li v-if="formatPage(hit)" class="muted">預算書 {{ formatPage(hit) }}</li>
              <li v-if="hit.dept" class="muted">機關：{{ hit.dept }}</li>
              <li v-if="hit.code" class="muted code-meta">編號：{{ hit.code }}</li>
              <li v-if="hit.unresolved">
                <span class="tag warn-tag">⚠ 待核對</span>
              </li>
            </ul>

            <p v-if="hit.text" class="hit-snippet">
              <template v-for="(seg, idx) in getSnippetSegments(hit)" :key="idx">
                <mark v-if="seg.hit" class="hl">{{ seg.text }}</mark>
                <template v-else>{{ seg.text }}</template>
              </template>
            </p>

          </article>
        </li>
      </ol>

      <div v-if="remainingCount > 0" class="more-wrap">
        <button class="btn" type="button" @click="showMore">
          顯示更多結果（尚有 {{ fmtInt(remainingCount) }} 筆）
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.search-page > * {
  min-width: 0;
}

.page-head {
  display: grid;
  gap: 6px;
}

.desc {
  margin: 0;
  font-size: var(--fs-sm);
}

.search-card {
  display: grid;
  gap: 14px;
}

.search-form {
  min-width: 0;
}

.input-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: stretch;
}

.search-input {
  flex: 1 1 220px;
  min-width: 0;
  min-height: 40px;
  padding: 8px 12px;
  font: inherit;
  color: var(--text);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

.search-input::placeholder {
  color: var(--text-muted);
}

.filter-rows {
  display: grid;
  gap: 10px;
}

.filter-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.filter-label {
  font-size: var(--fs-sm);
}

.err-msg {
  margin: 6px 0 12px;
  font-size: var(--fs-sm);
}

.retry-btn {
  margin-top: 4px;
}

.empty-state {
  display: grid;
  gap: 10px;
}

.empty-title {
  margin: 0;
  font-weight: 600;
}

.empty-desc {
  margin: 0;
  font-size: var(--fs-sm);
}

.examples,
.recovery-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.status-line {
  margin: 0;
  font-size: var(--fs-sm);
}

.hit-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 12px;
}

.hit-card {
  min-width: 0;
}

.hit-article {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.hit-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px 16px;
}

.hit-title {
  font-size: var(--fs-md);
  font-weight: 700;
  overflow-wrap: anywhere;
  min-width: 0;
  flex: 1 1 200px;
}

.hit-title-link {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.hit-title-link:hover {
  text-decoration-thickness: 2px;
}

.hit-amount {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text);
}

.hit-meta {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  font-size: var(--fs-xs);
}

.code-meta {
  overflow-wrap: anywhere;
}

.tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text);
  font-size: var(--fs-xs);
  font-weight: 600;
  white-space: nowrap;
}

.kind-tag[data-kind="revenue"] {
  border-left: 6px solid var(--cat-3);
}

.kind-tag[data-kind="expenditure"],
.kind-tag[data-kind="plan"] {
  border-left: 6px solid var(--cat-1);
}

.kind-tag[data-kind="summary"] {
  border-left: 6px solid var(--cat-8);
}

.warn-tag {
  border-color: var(--diff-down-4);
  border-left-width: 6px;
}

.hit-snippet {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text);
  overflow-wrap: anywhere;
}

.hl {
  background: color-mix(in srgb, var(--accent) 22%, transparent);
  color: var(--text);
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 2px;
  padding: 0 2px;
  border-radius: 3px;
}

.more-wrap {
  display: flex;
  justify-content: center;
  padding-top: 4px;
}
</style>
