<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { fmtInt, fmtSignedPct, fmtSignedYuan } from "@/data/format";
import { dataSource } from "@/data/source";
import type { IndexData, SeriesData } from "@/data/types";
import { download } from "@/utils/export";
import { firstQuery } from "@/utils/query";
import { useQueryString } from "@/composables/useRouteState";
import ItemPicker from "./trend/ItemPicker.vue";
import TrendChart, { type TrendChartEntry } from "./trend/TrendChart.vue";
import {
  activeYearsOf,
  computeSeriesDerived,
  encodeTrendItemsParam,
  formatSeriesItemLabel,
  historicalNamesOf,
  MAX_TREND_ITEMS,
  parseTrendItemsParam,
  toTrendExportRows,
  TREND_MODE_KEYS,
  TREND_MODES,
  trendRowsToCsv,
  trendRowsToJson,
  type TrendMode,
} from "./trend/trendModel";

const route = useRoute();
const router = useRouter();
const year = computed(() => Number(route.params.year) || 0);

const loading = ref(true);
const seriesData = ref<SeriesData | null>(null);
const indexData = ref<IndexData | null>(null);

const mode = useQueryString<TrendMode>("mode", "amount", TREND_MODE_KEYS);
const yoyMetric = ref<"pct" | "diff">("pct");

onMounted(async () => {
  loading.value = true;
  try {
    const src = dataSource();
    const [s, idx] = await Promise.all([src.series(), src.index().catch(() => null)]);
    seriesData.value = s;
    indexData.value = idx;
  } finally {
    loading.value = false;
  }
});

const hasEnoughYears = computed(() => (seriesData.value?.years.length ?? 0) >= 2);

const parsedItems = computed(() => {
  if (!seriesData.value) {
    return { keys: [] as string[], notices: [] as string[], droppedUnknown: [], droppedDuplicate: [], droppedOverflow: [] };
  }
  return parseTrendItemsParam(seriesData.value, firstQuery(route.query.items));
});

const selectedKeys = computed(() => parsedItems.value.keys);
const paramNotices = computed(() => parsedItems.value.notices);

function updateItems(nextKeys: string[]): void {
  const query: Record<string, unknown> = { ...route.query };
  const enc = encodeTrendItemsParam(nextKeys.slice(0, MAX_TREND_ITEMS));
  if (enc) query.items = enc;
  else delete query.items;
  void router.replace({ query: query as Record<string, string> });
}

function addItem(key: string): void {
  if (selectedKeys.value.includes(key) || selectedKeys.value.length >= MAX_TREND_ITEMS) return;
  updateItems([...selectedKeys.value, key]);
}

function removeItem(key: string): void {
  updateItems(selectedKeys.value.filter((k) => k !== key));
}

function setPrimary(key: string): void {
  const rest = selectedKeys.value.filter((k) => k !== key);
  updateItems([key, ...rest]);
}

function clearItems(): void {
  updateItems([]);
}

const entries = computed<Array<TrendChartEntry & { activeYears: number[]; oldNames: string[] }>>(() => {
  const data = seriesData.value;
  if (!data) return [];
  return selectedKeys.value
    .map((key, idx) => {
      const item = data.items[key];
      if (!item) return null;
      return {
        key,
        label: formatSeriesItemLabel(key, item, data.items),
        item,
        derived: computeSeriesDerived(item, data.years),
        isPrimary: idx === 0,
        activeYears: activeYearsOf(item, data.years),
        oldNames: historicalNamesOf(item),
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);
});

const exportRows = computed(() =>
  seriesData.value ? toTrendExportRows(seriesData.value, selectedKeys.value) : [],
);

function exportAs(kind: "csv" | "json"): void {
  if (!seriesData.value || !exportRows.value.length) return;
  const years = seriesData.value.years;
  const base = `wanluan-trend-${years[0]}-${years[years.length - 1]}`;
  if (kind === "csv") {
    download(`${base}.csv`, trendRowsToCsv(exportRows.value, years), "text/csv");
  } else {
    download(`${base}.json`, trendRowsToJson(exportRows.value), "application/json");
  }
}

const singleYearEntries = computed(() => entries.value.filter((e) => e.activeYears.length === 1));
const fallbackYear = computed(() => year.value || indexData.value?.default_year || 116);
</script>

<template>
  <div class="page trend-page">
    <header class="page-head">
      <h1 class="page-title">跨年度趨勢與自選比較</h1>
      <p class="muted lead">
        檢視單一預算項目的逐年增減，或自選最多 {{ MAX_TREND_ITEMS }} 個項目（可跨歲入、歲出與不同層級）獨立比較。
      </p>
      <aside class="budget-note" aria-label="資料範圍說明">
        <strong>資料範圍說明：</strong>各年皆為原編預算，不含追加（減）預算與決算。金額單位：元；缺值年度以「—」表示，折線於缺值處斷開、不補 0。
      </aside>
    </header>

    <p v-if="loading" class="card muted" role="status" aria-live="polite">載入跨年度趨勢資料中…</p>

    <section v-else-if="!seriesData" class="card degrade-box" aria-labelledby="no-series-title">
      <h2 id="no-series-title" class="section-title">目前尚無跨年度趨勢資料</h2>
      <p class="muted">
        跨年度趨勢資料檔（<code>series.json</code>）尚未產生或暫時無法載入。您可以先瀏覽單一年度的總覽、歲出、歲入或比較頁。
      </p>
      <div class="link-row">
        <router-link class="btn primary" :to="{ path: `/${fallbackYear}/總覽` }">前往總覽</router-link>
        <router-link class="btn" :to="{ path: `/${fallbackYear}/歲出` }">歲出</router-link>
        <router-link class="btn" :to="{ path: `/${fallbackYear}/歲入` }">歲入</router-link>
        <router-link class="btn" :to="{ path: `/${fallbackYear}/比較` }">比較</router-link>
      </div>
    </section>

    <section v-else-if="!hasEnoughYears" class="card degrade-box" aria-labelledby="few-years-title">
      <h2 id="few-years-title" class="section-title">年度資料不足，無法顯示跨年度趨勢</h2>
      <p class="muted">
        目前僅有 {{ seriesData.years.join("、") || "0" }} 年度資料，至少需 2 個年度才可比較趨勢變化。
      </p>
    </section>

    <template v-else>
      <div v-if="paramNotices.length" class="notice-box" role="status" aria-live="polite">
        <strong>網址參數已自動調整：</strong>
        <ul class="notice-list">
          <li v-for="(msg, i) in paramNotices" :key="i">{{ msg }}</li>
        </ul>
      </div>

      <ItemPicker
        :data="seriesData"
        :selected-keys="selectedKeys"
        @add="addItem"
        @remove="removeItem"
        @set-primary="setPrimary"
        @clear="clearItems"
      />

      <section v-if="entries.length" class="card chart-section" aria-label="趨勢圖表與數值明細">
        <div class="mode-bar">
          <div class="btn-group" role="group" aria-label="檢視模式">
            <button
              v-for="m in TREND_MODES"
              :key="m.key"
              type="button"
              class="btn"
              :aria-pressed="mode === m.key"
              @click="mode = m.key"
            >
              {{ m.label }}
            </button>
          </div>

          <div v-if="mode === 'yoy'" class="btn-group" role="group" aria-label="逐年增減圖表指標">
            <button
              type="button"
              class="btn sub-btn"
              :aria-pressed="yoyMetric === 'pct'"
              @click="yoyMetric = 'pct'"
            >
              折線顯示增減率 (%)
            </button>
            <button
              type="button"
              class="btn sub-btn"
              :aria-pressed="yoyMetric === 'diff'"
              @click="yoyMetric = 'diff'"
            >
              折線顯示差額 (元)
            </button>
          </div>
        </div>

        <p v-if="mode === 'yoy'" class="mode-note">
          <strong>計算規則：</strong>逐年差額與增減率僅在<strong>相鄰兩年都有值時才計算</strong>（缺值年不跳年比較、也不補 0），<strong>和比較頁的差額不同</strong>（比較頁將缺值視為 0）。
        </p>
        <p v-else-if="mode === 'index'" class="mode-note">
          <strong>指數說明：</strong>各項目各自以「第一個非 null 且非 0 的年度」為基準年（基準年 ＝ 100）；若無非零年度則整條指數為「—」。各項目基準年列於圖例與下方表格。
        </p>

        <p v-if="singleYearEntries.length" class="single-year-note" role="note">
          提示：
          <template v-for="(e, i) in singleYearEntries" :key="e.key">
            <template v-if="i > 0">、</template>
            「{{ e.label }}」僅 {{ e.activeYears[0] }} 年度有資料
          </template>
          ，折線圖將顯示單點、逐年差額為「—」。
        </p>

        <TrendChart
          :years="seriesData.years"
          :entries="entries"
          :mode="mode"
          :yoy-metric="yoyMetric"
          :current-year="year"
        />

        <div class="table-section">
          <div class="table-head">
            <h2 class="section-title">數值對照表</h2>
            <div class="export-actions">
              <span class="muted export-label">匯出：</span>
              <button type="button" class="btn" @click="exportAs('csv')">CSV</button>
              <button type="button" class="btn" @click="exportAs('json')">JSON</button>
            </div>
          </div>

          <div class="table-wrap" tabindex="0" role="region" aria-label="跨年度趨勢數值對照表（可捲動）">
            <table class="data">
              <caption>
                {{ seriesData.years.join("–") }} 年度自選項目數值對照（各年皆為原編預算，金額單位：元；兩年都有值才計算差額與增減率）
              </caption>
              <thead>
                <tr>
                  <th scope="col">項目</th>
                  <th scope="col">層級</th>
                  <th v-if="mode === 'index'" scope="col" class="num">基準年</th>
                  <template v-for="y in seriesData.years" :key="y">
                    <th v-if="mode === 'amount'" scope="col" class="num">{{ y }} 年金額</th>
                    <template v-else-if="mode === 'yoy'">
                      <th scope="col" class="num">{{ y }} 年差額</th>
                      <th scope="col" class="num">{{ y }} 年增減 %</th>
                    </template>
                    <th v-else scope="col" class="num">{{ y }} 年指數</th>
                  </template>
                </tr>
              </thead>
              <tbody>
                <tr v-for="e in entries" :key="e.key">
                  <th scope="row" class="item-cell">
                    <div class="item-name-line">
                      <span v-if="e.isPrimary" class="role-badge">★ 主項目</span>
                      <span>{{ e.label }}</span>
                    </div>
                    <div v-if="e.oldNames.length" class="muted item-sub">
                      曾用名：{{ e.oldNames.join("、") }}
                    </div>
                  </th>
                  <td>{{ e.item.level }}</td>
                  <td v-if="mode === 'index'" class="num">
                    {{ e.derived.index_base_year != null ? `${e.derived.index_base_year} 年` : "無" }}
                  </td>
                  <template v-for="y in seriesData.years" :key="y">
                    <td v-if="mode === 'amount'" class="num">
                      {{ e.item.amount_元[String(y)] == null ? "—" : fmtInt(e.item.amount_元[String(y)]!) }}
                    </td>
                    <template v-else-if="mode === 'yoy'">
                      <td class="num">{{ fmtSignedYuan(e.derived.diff_元[String(y)]) }}</td>
                      <td class="num">{{ fmtSignedPct(e.derived.pct[String(y)]) }}</td>
                    </template>
                    <td v-else class="num">
                      {{ e.derived.index[String(y)] == null ? "—" : e.derived.index[String(y)]!.toFixed(2) }}
                    </td>
                  </template>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.trend-page > * {
  min-width: 0;
}
.page-head {
  display: grid;
  gap: 8px;
}
.lead {
  margin: 0;
  font-size: var(--fs-sm);
}
.budget-note {
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  background: var(--surface);
  font-size: var(--fs-sm);
}

.degrade-box {
  display: grid;
  gap: 12px;
}
.degrade-box p {
  margin: 0;
}
.section-title {
  font-size: var(--fs-lg);
}
.link-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.link-row .btn {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.notice-box {
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  border-left: 4px solid var(--cat-2);
  background: var(--surface);
  font-size: var(--fs-sm);
}
.notice-list {
  margin: 6px 0 0;
  padding-left: 20px;
}

.chart-section {
  display: grid;
  gap: 14px;
  min-width: 0;
}
.mode-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px 12px;
}
.btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.sub-btn {
  font-size: var(--fs-xs);
  padding: 4px 10px;
  min-height: 32px;
}
.mode-note,
.single-year-note {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--border);
  font-size: var(--fs-sm);
}

.table-section {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.table-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px 12px;
}
.export-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.export-label {
  font-size: var(--fs-sm);
}

.item-cell {
  min-width: 140px;
}
.item-name-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.role-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-contrast);
  font-size: var(--fs-xs);
  white-space: nowrap;
}
.item-sub {
  font-size: var(--fs-xs);
  font-weight: 400;
  margin-top: 2px;
}
</style>
