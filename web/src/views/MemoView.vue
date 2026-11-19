<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter, type RouteLocationRaw } from "vue-router";
import { dataSource } from "@/data/source";
import type { YearData } from "@/data/types";
import { firstQuery } from "@/utils/query";
import {
  MEMO_TYPE_ORDER,
  fetchMemosFile,
  memoLocationText,
  memoScopeLabel,
  memoStatusLabel,
  memoTargetRoute,
  memoTypeLabel,
  resolveEvidenceSrc,
  sortMemos,
  type MemoItem,
} from "./memo/memoModel";

const route = useRoute();
const router = useRouter();

const year = computed(() => Number(route.params.year) || 0);
const loading = ref(true);
const error = ref<string | null>(null);
const yearMemos = ref<MemoItem[]>([]);
const yearData = ref<YearData | null>(null);
const hasReference = ref(false);
const failedImages = ref<Record<string, boolean>>({});

let loadSeq = 0;

async function loadData(y: number): Promise<void> {
  const mine = ++loadSeq;
  loading.value = true;
  error.value = null;
  failedImages.value = {};

  try {
    const file = await fetchMemosFile();
    if (mine !== loadSeq) return;
    const list = file.years?.[String(y)];
    yearMemos.value = Array.isArray(list) ? sortMemos(list) : [];
  } catch (e) {
    if (mine !== loadSeq) return;
    error.value = e instanceof Error ? e.message : String(e);
    yearMemos.value = [];
  } finally {
    if (mine === loadSeq) loading.value = false;
  }

  // 輔助載入年度預算與 index，用於產生「前往對應頁面」連結；失敗不影響備註瀏覽
  yearData.value = null;
  hasReference.value = false;
  if (!y) return;
  try {
    const src = dataSource();
    const [idx, yd] = await Promise.all([
      src.index().catch(() => null),
      src.year(y).catch(() => null),
    ]);
    if (mine !== loadSeq) return;
    hasReference.value = Boolean(idx?.reference_years?.includes(y));
    yearData.value = yd;
  } catch {
    if (mine !== loadSeq) return;
    hasReference.value = false;
    yearData.value = null;
  }
}

watch(year, (y) => void loadData(y), { immediate: true });

const typeFilter = computed(() => (firstQuery(route.query.type) ?? "").trim());
const pageFilter = computed(() => (firstQuery(route.query.p) ?? "").trim());

function setFilters(nextType: string, nextPage: string): void {
  const query = { ...route.query };
  if (nextType) query.type = nextType;
  else delete query.type;
  if (nextPage) query.p = nextPage;
  else delete query.p;
  void router.replace({ query });
}

function clearFilters(): void {
  setFilters("", "");
}

const typeCounts = computed(() => {
  const counts: Record<string, number> = {};
  for (const m of yearMemos.value) {
    counts[m.type] = (counts[m.type] ?? 0) + 1;
  }
  return counts;
});

const typeOptions = computed(() => {
  const seen = new Set<string>();
  const out: Array<{ key: string; label: string; count: number }> = [];
  for (const k of MEMO_TYPE_ORDER) {
    const count = typeCounts.value[k] ?? 0;
    if (count > 0 || typeFilter.value === k) {
      seen.add(k);
      out.push({ key: k, label: memoTypeLabel(k), count });
    }
  }
  for (const [k, count] of Object.entries(typeCounts.value)) {
    if (!seen.has(k)) {
      seen.add(k);
      out.push({ key: k, label: memoTypeLabel(k), count });
    }
  }
  if (typeFilter.value && !seen.has(typeFilter.value)) {
    out.push({ key: typeFilter.value, label: memoTypeLabel(typeFilter.value), count: 0 });
  }
  return out;
});

const pageCounts = computed(() => {
  const counts: Record<string, number> = {};
  for (const m of yearMemos.value) {
    const key = String(m.page);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
});

const pageOptions = computed(() => {
  const keys = Object.keys(pageCounts.value).sort((a, b) => Number(a) - Number(b));
  const out = keys.map((pg) => ({ page: pg, count: pageCounts.value[pg] }));
  if (pageFilter.value && !pageCounts.value[pageFilter.value]) {
    out.push({ page: pageFilter.value, count: 0 });
  }
  return out;
});

const filteredMemos = computed(() =>
  yearMemos.value.filter((m) => {
    if (typeFilter.value && m.type !== typeFilter.value) return false;
    if (pageFilter.value && String(m.page) !== pageFilter.value) return false;
    return true;
  }),
);

const hasActiveFilter = computed(() => Boolean(typeFilter.value || pageFilter.value));

interface MemoViewRow {
  memo: MemoItem;
  typeLabel: string;
  statusLabel: string;
  statusSymbol: string;
  scopeLabel: string;
  locationText: string;
  targetRoute: RouteLocationRaw | null;
  evidenceSrc: string | null;
}

const displayRows = computed<MemoViewRow[]>(() =>
  filteredMemos.value.map((memo) => ({
    memo,
    typeLabel: memoTypeLabel(memo.type),
    statusLabel: memoStatusLabel(memo.status),
    statusSymbol: memo.status === "confirmed" ? "✓" : memo.status === "pending_publisher" ? "⧗" : "•",
    scopeLabel: memoScopeLabel(memo.scope),
    locationText: memoLocationText(memo),
    targetRoute: memoTargetRoute(year.value, memo, yearData.value, hasReference.value),
    evidenceSrc: resolveEvidenceSrc(memo.evidence),
  })),
);

function onEvidenceError(memoId: string): void {
  failedImages.value = { ...failedImages.value, [memoId]: true };
}

function pdfText(m: MemoItem): string {
  if (!m.pdf_file && (m.pdf_page === undefined || m.pdf_page === "")) return "—";
  if (m.pdf_file && m.pdf_page !== undefined && m.pdf_page !== "") {
    return `${m.pdf_file}（第 ${m.pdf_page} 頁）`;
  }
  return m.pdf_file || `第 ${m.pdf_page} 頁`;
}

function verifiedText(m: MemoItem): string {
  if (!m.verified_method && !m.verified_on) return "—";
  if (m.verified_method && m.verified_on) return `${m.verified_method}（${m.verified_on}）`;
  return m.verified_method || m.verified_on;
}
</script>

<template>
  <div class="page memo-page">
    <header class="page-head">
      <h1 class="page-title">{{ year }} 年度資料備註</h1>
      <p class="muted desc">
        本頁記錄預算書原件的印刷錯字、前後不一致、版面限制與資料缺口；資料本身依原書保留，不改動原書數字或原文。
      </p>
    </header>

    <p v-if="loading" class="card muted" role="status" aria-live="polite">
      載入 {{ year }} 年度資料備註中…
    </p>

    <div v-else-if="error" class="error-box" role="alert">
      <strong>無法載入資料備註：</strong>{{ error }}
      <p class="muted error-hint">請確認 <code>data/memos.json</code> 是否存在，或稍後重新整理頁面。</p>
    </div>

    <div v-else-if="!yearMemos.length" class="card muted" role="status">
      {{ year }} 年度目前沒有資料備註。
    </div>

    <template v-else>
      <section class="card filter-panel" aria-label="備註篩選條件">
        <div class="filter-row">
          <span class="filter-label" id="memo-type-label">類型</span>
          <div class="filter-chips" role="group" aria-labelledby="memo-type-label">
            <button
              type="button"
              class="btn"
              :aria-pressed="!typeFilter"
              @click="setFilters('', pageFilter)"
            >
              全部（{{ yearMemos.length }}）
            </button>
            <button
              v-for="opt in typeOptions"
              :key="opt.key"
              type="button"
              class="btn"
              :aria-pressed="typeFilter === opt.key"
              @click="setFilters(opt.key, pageFilter)"
            >
              {{ opt.label }}（{{ opt.count }}）
            </button>
          </div>
        </div>

        <div class="filter-row">
          <span class="filter-label" id="memo-page-label">頁碼</span>
          <div class="filter-chips" role="group" aria-labelledby="memo-page-label">
            <button
              type="button"
              class="btn"
              :aria-pressed="!pageFilter"
              @click="setFilters(typeFilter, '')"
            >
              全部頁碼
            </button>
            <button
              v-for="opt in pageOptions"
              :key="opt.page"
              type="button"
              class="btn"
              :aria-pressed="pageFilter === opt.page"
              @click="setFilters(typeFilter, opt.page)"
            >
              p{{ opt.page }}（{{ opt.count }}）
            </button>
          </div>
        </div>

        <div class="filter-summary" role="status" aria-live="polite">
          <span class="muted">
            顯示 <strong>{{ filteredMemos.length }}</strong> / 共 {{ yearMemos.length }} 筆備註
          </span>
          <button
            v-if="hasActiveFilter"
            type="button"
            class="btn btn-clear"
            @click="clearFilters"
          >
            清除篩選
          </button>
        </div>
      </section>

      <div v-if="!displayRows.length" class="card empty-filtered" role="status">
        <p class="muted">目前篩選條件沒有符合的備註。</p>
        <button type="button" class="btn" @click="clearFilters">顯示全部備註</button>
      </div>

      <section v-else class="memo-list" aria-label="備註列表">
        <article
          v-for="row in displayRows"
          :key="row.memo.memo_id"
          class="card memo-card"
          :data-memo-id="row.memo.memo_id"
        >
          <header class="memo-card-head">
            <div class="memo-card-meta">
              <h2 class="memo-id">{{ row.memo.memo_id }}</h2>
              <span class="badge" :class="`badge-type-${row.memo.type}`">
                {{ row.typeLabel }}
              </span>
              <span class="badge badge-status" :class="`badge-status-${row.memo.status}`">
                <span aria-hidden="true">{{ row.statusSymbol }}</span>
                {{ row.statusLabel }}
              </span>
              <span class="page-tag muted">第 {{ row.memo.page }} 頁（p{{ row.memo.page }}）</span>
            </div>

            <router-link
              v-if="row.targetRoute"
              :to="row.targetRoute"
              class="btn target-link"
            >
              前往對應頁面
            </router-link>
          </header>

          <dl class="memo-dl">
            <dt>位置</dt>
            <dd>
              <div class="loc-primary">{{ row.locationText }}</div>
              <div class="loc-detail muted">
                <span>範圍（scope）：<code>{{ row.scopeLabel }}</code>（<code>{{ row.memo.scope || "—" }}</code>）</span>
                <span>頁碼（page）：<code>p{{ row.memo.page }}</code></span>
                <span>定位（locator）：<code>{{ row.memo.locator || "—" }}</code></span>
                <span v-if="row.memo.field">欄位：<code>{{ row.memo.field }}</code></span>
              </div>
            </dd>

            <dt>印刷原文</dt>
            <dd>
              <code class="memo-code">{{ row.memo.printed_text || "—" }}</code>
            </dd>

            <dt>資料中文字</dt>
            <dd>
              <code class="memo-code">{{ row.memo.data_text || "—" }}</code>
            </dd>

            <dt>建議文字</dt>
            <dd>
              <code class="memo-code">{{ row.memo.suggested_text || "—" }}</code>
            </dd>

            <dt>說明</dt>
            <dd class="memo-note">{{ row.memo.note || "—" }}</dd>

            <dt>PDF 頁序</dt>
            <dd>{{ pdfText(row.memo) }}</dd>

            <dt>核對方式與日期</dt>
            <dd>{{ verifiedText(row.memo) }}</dd>

            <dt>狀態</dt>
            <dd>
              <span aria-hidden="true">{{ row.statusSymbol }}</span>
              {{ row.statusLabel }}
            </dd>

            <template v-if="row.memo.evidence">
              <dt>證據圖</dt>
              <dd class="memo-evidence">
                <img
                  v-if="row.evidenceSrc && !failedImages[row.memo.memo_id]"
                  :src="row.evidenceSrc"
                  :alt="`證據截圖 ${row.memo.memo_id}`"
                  loading="lazy"
                  class="memo-evidence-img"
                  @error="onEvidenceError(row.memo.memo_id)"
                />
                <div class="memo-evidence-path muted">
                  <code>{{ row.memo.evidence }}</code>
                </div>
              </dd>
            </template>
          </dl>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.memo-page > * {
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

.error-hint {
  margin: 6px 0 0;
  font-size: var(--fs-sm);
}

.filter-panel {
  display: grid;
  gap: 12px;
}

.filter-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 8px 12px;
  align-items: start;
}

.filter-label {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-muted);
  padding-top: 7px;
}

.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.filter-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.btn-clear {
  padding: 4px 12px;
}

.empty-filtered {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.empty-filtered p {
  margin: 0;
}

.memo-list {
  display: grid;
  gap: var(--gap);
}

.memo-card {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.memo-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.memo-card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.memo-id {
  font-size: var(--fs-lg);
  font-variant-numeric: tabular-nums;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--fs-xs);
  font-weight: 600;
  line-height: 1.5;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
}

.badge-type-print_typo {
  border-left: 4px solid var(--cat-2);
}

.badge-type-print_inconsistent {
  border-left: 4px solid var(--cat-5);
}

.badge-type-print_layout {
  border-left: 4px solid var(--cat-1);
}

.badge-type-data_gap {
  border-left: 4px solid var(--cat-4);
}

.badge-status-confirmed {
  border-left: 4px solid var(--cat-3);
}

.badge-status-pending_publisher {
  border-left: 4px solid var(--cat-7);
}

.page-tag {
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}

.target-link {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
}

.memo-dl {
  margin: 0;
  display: grid;
  grid-template-columns: minmax(112px, 136px) minmax(0, 1fr);
  gap: 8px 16px;
  font-size: var(--fs-sm);
}

.memo-dl dt {
  color: var(--text-muted);
  font-weight: 600;
  padding-top: 2px;
}

.memo-dl dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.loc-primary {
  font-weight: 500;
}

.loc-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 4px;
  font-size: var(--fs-xs);
}

.memo-code {
  display: inline-block;
  max-width: 100%;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: var(--fs-xs);
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.memo-note {
  line-height: 1.65;
}

.memo-evidence {
  display: grid;
  gap: 6px;
}

.memo-evidence-img {
  display: block;
  max-width: 100%;
  max-height: 360px;
  width: auto;
  height: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.memo-evidence-path {
  font-size: var(--fs-xs);
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .filter-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }

  .filter-label {
    padding-top: 0;
  }

  .memo-dl {
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
  }

  .memo-dl dt {
    margin-top: 8px;
  }

  .memo-dl dt:first-child {
    margin-top: 0;
  }
}
</style>
