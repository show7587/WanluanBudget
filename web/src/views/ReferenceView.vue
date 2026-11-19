<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { dataSource } from "@/data/source";
import type { IndexData } from "@/data/types";
import { firstQuery } from "@/utils/query";
import {
  buildTableGrid,
  buildTocGroups,
  collectNotes,
  collectReferencePages,
  fetchReferenceData,
  sortReferenceTables,
  tablesForPage,
  type ReferenceData,
  type ReferenceTable,
  type RenderedTableGrid,
} from "./reference/referenceModel";

const route = useRoute();
const router = useRouter();

const year = computed(() => Number(route.params.year) || 0);
const index = ref<IndexData | null>(null);
const refData = ref<ReferenceData | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const unsupportedYear = ref(false);

let loadSeq = 0;

async function loadYear(y: number): Promise<void> {
  const seq = ++loadSeq;
  loading.value = true;
  error.value = null;
  refData.value = null;
  unsupportedYear.value = false;

  if (!y) {
    loading.value = false;
    error.value = "無效的年度參數。";
    return;
  }

  let idx: IndexData | null = index.value;
  if (!idx) {
    try {
      idx = await dataSource().index();
      if (seq !== loadSeq) return;
      index.value = idx;
    } catch {
      // 索引檔載入失敗時仍嘗試直接讀取該年度參考表
      idx = null;
    }
  }

  if (idx && !idx.reference_years.includes(y)) {
    unsupportedYear.value = true;
    loading.value = false;
    return;
  }

  try {
    const data = await fetchReferenceData(y);
    if (seq !== loadSeq) return;
    refData.value = data;
  } catch (e) {
    if (seq !== loadSeq) return;
    error.value = e instanceof Error ? e.message : `${y} 年度的參考表資料載入失敗。`;
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

watch(year, (y) => void loadYear(y), { immediate: true });

const referenceYears = computed(() =>
  [...(index.value?.reference_years ?? [114])].sort((a, b) => b - a),
);

const sortedTables = computed(() =>
  refData.value ? sortReferenceTables(refData.value.tables) : [],
);

const pages = computed(() => collectReferencePages(sortedTables.value));

const tocGroups = computed(() => buildTocGroups(sortedTables.value));

const pageQuery = computed(() => (firstQuery(route.query.p) ?? "").trim());

const activePage = computed<number | null>(() => {
  if (!pages.value.length) return null;
  if (!pageQuery.value) return pages.value[0];
  return pages.value.find((pg) => String(pg) === pageQuery.value) ?? null;
});

const isInvalidPage = computed(
  () => pages.value.length > 0 && pageQuery.value !== "" && activePage.value === null,
);

const activePageIndex = computed(() =>
  activePage.value === null ? -1 : pages.value.indexOf(activePage.value),
);

const prevPage = computed<number | null>(() =>
  activePageIndex.value > 0 ? pages.value[activePageIndex.value - 1] : null,
);

const nextPage = computed<number | null>(() =>
  activePageIndex.value >= 0 && activePageIndex.value + 1 < pages.value.length
    ? pages.value[activePageIndex.value + 1]
    : null,
);

const globalNotes = computed(() =>
  refData.value ? collectNotes(refData.value.note, refData.value.notes) : [],
);

interface ActiveTableEntry {
  table: ReferenceTable;
  grid: RenderedTableGrid;
  notes: string[];
}

const activeTables = computed<ActiveTableEntry[]>(() => {
  if (activePage.value === null) return [];
  return tablesForPage(sortedTables.value, activePage.value).map((table) => ({
    table,
    grid: buildTableGrid(table),
    notes: collectNotes(table.note, table.notes),
  }));
});

const pageLabelByPage = computed(() => {
  const map = new Map<number, string>();
  for (const t of sortedTables.value) {
    if (!map.has(t.page)) {
      map.set(t.page, `p${t.page} — ${t.source_table}`);
    }
  }
  return map;
});

function pageLink(pg: number) {
  return { path: `/${year.value}/參考表`, query: { p: String(pg) } };
}

function onSelectPage(e: Event): void {
  const value = (e.target as HTMLSelectElement).value;
  if (!value) return;
  void router.push({ path: `/${year.value}/參考表`, query: { p: value } });
}

function tableHeading(tb: ReferenceTable, totalOnPage: number): string {
  return totalOnPage > 1 ? `${tb.source_table}（第 ${tb.table_seq} 表）` : tb.source_table;
}

function tableRegionLabel(tb: ReferenceTable, totalOnPage: number): string {
  const title = tableHeading(tb, totalOnPage);
  return `預算書第 ${tb.page} 頁：${title}（共 ${tb.rows} 列 ${tb.cols} 欄，可使用方向鍵捲動檢視）`;
}
</script>

<template>
  <div class="page ref-page">
    <header class="page-head">
      <h1 class="page-title">{{ year }} 年度參考表</h1>
      <p class="muted lead">
        預算書參考表原樣呈現，儲存格內容依 OCR 轉檔，只套用 data/corrections.csv 登記過的修正；金額單位依各表標示。
      </p>
    </header>

    <p v-if="loading" class="card muted" role="status" aria-live="polite">
      載入 {{ year }} 年度參考表資料中…
    </p>

    <section
      v-else-if="unsupportedYear"
      class="card empty-state"
      aria-labelledby="unsupported-ref-title"
    >
      <h2 id="unsupported-ref-title" class="section-title">{{ year }} 年度未收錄參考表</h2>
      <p class="muted">
        目前僅 {{ referenceYears.join("、") }} 年度提供預算書參考表原樣檢視。您可以切換至已收錄年度，或前往
        {{ year }} 年度的其他頁面。
      </p>
      <div class="nav-groups">
        <div class="link-group">
          <span class="group-label muted">切換至已收錄年度：</span>
          <div class="link-row">
            <router-link
              v-for="y in referenceYears"
              :key="y"
              class="btn primary"
              :to="{ path: `/${y}/參考表` }"
            >
              查看 {{ y }} 年度參考表
            </router-link>
          </div>
        </div>
        <div class="link-group">
          <span class="group-label muted">前往 {{ year }} 年度其他頁面：</span>
          <div class="link-row">
            <router-link class="btn" :to="{ path: `/${year}/總覽` }">總覽</router-link>
            <router-link class="btn" :to="{ path: `/${year}/歲出` }">歲出</router-link>
            <router-link class="btn" :to="{ path: `/${year}/歲入` }">歲入</router-link>
          </div>
        </div>
      </div>
    </section>

    <div v-else-if="error" class="error-box" role="alert">
      <strong>無法載入參考表資料：</strong>{{ error }}
      <div class="error-actions">
        <router-link class="btn" :to="{ path: `/${year}/總覽` }">返回 {{ year }} 年度總覽</router-link>
      </div>
    </div>

    <section v-else-if="!pages.length" class="card empty-state">
      <h2 class="section-title">{{ year }} 年度沒有參考表資料</h2>
      <p class="muted">目前資料檔中沒有任何可顯示的參考表。</p>
    </section>

    <template v-else>
      <aside v-if="globalNotes.length" class="note-box" aria-label="參考表整體說明">
        <p v-for="(n, i) in globalNotes" :key="i" class="note-line">
          <strong>註：</strong>{{ n }}
        </p>
      </aside>

      <section class="card toc-card" aria-labelledby="ref-toc-title">
        <div class="toc-head">
          <h2 id="ref-toc-title" class="section-title">
            目次（共 {{ tocGroups.length }} 類、{{ pages.length }} 頁）
          </h2>
          <label class="page-select">
            <span class="muted">快速跳頁：</span>
            <select
              :value="activePage !== null ? String(activePage) : ''"
              aria-label="選擇參考表頁碼"
              @change="onSelectPage"
            >
              <option v-if="activePage === null" value="" disabled>請選擇頁碼</option>
              <option v-for="pg in pages" :key="pg" :value="String(pg)">
                {{ pageLabelByPage.get(pg) ?? `p${pg}` }}
              </option>
            </select>
          </label>
        </div>

        <ul class="toc-list">
          <li v-for="group in tocGroups" :key="`${group.name}-${group.range}`" class="toc-item">
            <div class="toc-label">
              <span class="toc-name">{{ group.name }}</span>
              <span class="muted toc-range">{{ group.range }}</span>
            </div>
            <div class="chip-row" role="group" :aria-label="`${group.name} 頁碼`">
              <router-link
                v-for="pg in group.pages"
                :key="pg"
                class="btn chip"
                :class="{ primary: pg === activePage }"
                :aria-current="pg === activePage ? 'page' : undefined"
                :to="pageLink(pg)"
              >
                p{{ pg }}
              </router-link>
            </div>
          </li>
        </ul>
      </section>

      <div v-if="isInvalidPage" class="error-box" role="alert">
        <strong>找不到指定頁碼：</strong>{{ year }} 年度沒有第 {{ pageQuery }} 頁的參考表（收錄範圍：p{{ pages[0] }}–p{{ pages[pages.length - 1] }}）。
        <div class="error-actions">
          <router-link class="btn primary" :to="pageLink(pages[0])">
            前往第 {{ pages[0] }} 頁
          </router-link>
        </div>
      </div>

      <template v-else-if="activePage !== null">
        <nav class="pager" aria-label="參考表分頁導覽（上方）">
          <router-link v-if="prevPage !== null" class="btn" :to="pageLink(prevPage)">
            ‹ 上一頁（p{{ prevPage }}）
          </router-link>
          <button v-else type="button" class="btn" disabled>‹ 上一頁</button>

          <span class="pager-status muted">
            第 {{ activePage }} 頁（{{ activePageIndex + 1 }} / {{ pages.length }}）
          </span>

          <router-link v-if="nextPage !== null" class="btn" :to="pageLink(nextPage)">
            下一頁（p{{ nextPage }}） ›
          </router-link>
          <button v-else type="button" class="btn" disabled>下一頁 ›</button>
        </nav>

        <section
          v-for="entry in activeTables"
          :key="`${entry.table.page}-${entry.table.table_seq}`"
          class="card table-card"
          :aria-labelledby="`ref-table-title-${entry.table.page}-${entry.table.table_seq}`"
        >
          <header class="table-head">
            <h2
              :id="`ref-table-title-${entry.table.page}-${entry.table.table_seq}`"
              class="table-title"
            >
              {{ tableHeading(entry.table, activeTables.length) }}
            </h2>
            <p class="table-meta muted">
              <span>預算書第 {{ entry.table.page }} 頁</span>
              <span aria-hidden="true">・</span>
              <span>單位：{{ entry.table.unit || "單位請見原書該頁" }}</span>
              <span aria-hidden="true">・</span>
              <span>{{ entry.table.rows }} 列 × {{ entry.table.cols }} 欄</span>
            </p>
          </header>

          <aside
            v-if="entry.notes.length"
            class="note-box"
            :aria-label="`第 ${entry.table.page} 頁表格提示`"
          >
            <p v-for="(noteText, idx) in entry.notes" :key="idx" class="note-line">
              <strong>⚠ 頁面提示：</strong>{{ noteText }}
            </p>
          </aside>

          <p class="scroll-hint muted">
            表格較寬時可左右滑動，或聚焦表格區域後以方向鍵捲動。
          </p>

          <div
            class="ref-table-wrap"
            tabindex="0"
            role="region"
            :aria-label="tableRegionLabel(entry.table, activeTables.length)"
          >
            <table class="ref-table">
              <caption class="sr-only">
                {{ tableHeading(entry.table, activeTables.length) }}（預算書第
                {{ entry.table.page }} 頁，單位：{{ entry.table.unit || "請見原書該頁" }}）
              </caption>

              <thead v-if="entry.grid.headerRows.length">
                <tr v-for="(row, rIdx) in entry.grid.headerRows" :key="`h-${rIdx}`">
                  <th
                    v-for="cell in row"
                    :key="cell.key"
                    :rowspan="cell.rowspan"
                    :colspan="cell.colspan"
                    :scope="cell.scope"
                  >
                    {{ cell.text }}
                  </th>
                </tr>
              </thead>

              <tbody>
                <tr v-for="(row, rIdx) in entry.grid.bodyRows" :key="`b-${rIdx}`">
                  <td
                    v-for="cell in row"
                    :key="cell.key"
                    :rowspan="cell.rowspan"
                    :colspan="cell.colspan"
                    :class="{ num: cell.isNumeric }"
                  >
                    {{ cell.text }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <nav class="pager" aria-label="參考表分頁導覽（下方）">
          <router-link v-if="prevPage !== null" class="btn" :to="pageLink(prevPage)">
            ‹ 上一頁（p{{ prevPage }}）
          </router-link>
          <button v-else type="button" class="btn" disabled>‹ 上一頁</button>

          <span class="pager-status muted">
            第 {{ activePage }} 頁（{{ activePageIndex + 1 }} / {{ pages.length }}）
          </span>

          <router-link v-if="nextPage !== null" class="btn" :to="pageLink(nextPage)">
            下一頁（p{{ nextPage }}） ›
          </router-link>
          <button v-else type="button" class="btn" disabled>下一頁 ›</button>
        </nav>
      </template>
    </template>
  </div>
</template>

<style scoped>
.ref-page > * {
  min-width: 0;
}

.page-head {
  display: grid;
  gap: 4px;
}

.lead {
  margin: 0;
  font-size: var(--fs-sm);
}

.section-title {
  font-size: var(--fs-lg);
}

.empty-state {
  display: grid;
  gap: 12px;
}

.empty-state p {
  margin: 0;
}

.nav-groups {
  display: grid;
  gap: 12px;
}

.link-group {
  display: grid;
  gap: 8px;
}

.group-label {
  font-size: var(--fs-sm);
}

.link-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.link-row .btn,
.error-actions .btn,
.pager .btn,
.chip {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.error-actions {
  margin-top: 10px;
}

.note-box {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-left: 4px solid var(--cat-2);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  font-size: var(--fs-sm);
  display: grid;
  gap: 4px;
}

.note-line {
  margin: 0;
}

.toc-card {
  display: grid;
  gap: 12px;
}

.toc-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
}

.page-select {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
  max-width: 100%;
}

.page-select select {
  font: inherit;
  font-size: var(--fs-sm);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  min-height: 36px;
  max-width: 100%;
  min-width: 0;
}

.toc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}

.toc-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.toc-item:first-child {
  padding-top: 0;
  border-top: 0;
}

.toc-label {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 8px;
  min-width: 0;
}

.toc-name {
  font-weight: 600;
  font-size: var(--fs-sm);
  overflow-wrap: anywhere;
}

.toc-range {
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  padding: 4px 12px;
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
}

.pager-status {
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}

.table-card {
  display: grid;
  gap: 12px;
}

.table-head {
  display: grid;
  gap: 4px;
}

.table-title {
  font-size: var(--fs-lg);
  overflow-wrap: anywhere;
}

.table-meta {
  margin: 0;
  font-size: var(--fs-sm);
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
}

.scroll-hint {
  margin: 0;
  font-size: var(--fs-xs);
}

.ref-table thead th { position: sticky; top: 0; z-index: 1; background: var(--surface-2); }
.ref-table-wrap {
  overflow: auto;
  max-width: 100%;
  max-height: 70vh;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.ref-table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.ref-table th,
.ref-table td {
  padding: 6px 10px;
  border: 1px solid var(--border);
  vertical-align: middle;
  line-height: 1.45;
}

.ref-table thead th {
  background: var(--surface-2);
  font-weight: 600;
  text-align: center;
  white-space: nowrap;
}

.ref-table tbody td {
  text-align: left;
}

.ref-table tbody td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.ref-table tbody tr:hover td {
  background: var(--surface-2);
}

@media (max-width: 640px) {
  .page-select {
    width: 100%;
  }

  .page-select select {
    flex: 1;
  }

  .pager {
    justify-content: center;
  }

  .pager-status {
    width: 100%;
    text-align: center;
    order: -1;
  }
}
</style>
