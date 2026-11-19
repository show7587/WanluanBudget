<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import ChartPanel from "@/components/ChartPanel.vue";
import DataTable from "@/components/DataTable.vue";
import DiffLegend from "@/components/DiffLegend.vue";
import KpiCard from "@/components/KpiCard.vue";
import { useBudget } from "@/composables/useBudget";
import { useQueryString } from "@/composables/useRouteState";
import { DIFF_BANDS } from "@/data/diffScale";
import { fmtCompact, fmtSignedPct, fmtSignedYuan } from "@/data/format";
import DivergingBarChart from "./compare/DivergingBarChart.vue";
import {
  buildCompareNodes,
  COMPARE_FILTER_KEYS,
  COMPARE_FILTERS,
  COMPARE_SCOPE_KEYS,
  COMPARE_SCOPES,
  COMPARE_SORT_KEYS,
  COMPARE_SORTS,
  filterCompareNodes,
  sortCompareNodes,
  summarizeCompareNodes,
  toCompareExportRows,
  type CompareFilter,
  type CompareScope,
  type CompareSort,
} from "./compare/compareModel";

const route = useRoute();
const year = computed(() => Number(route.params.year) || 0);
const { loading, error, index, compare } = useBudget(year);

const scope = useQueryString<CompareScope>("scope", "plan", COMPARE_SCOPE_KEYS);
const filter = useQueryString<CompareFilter>("filter", "all", COMPARE_FILTER_KEYS);
const sort = useQueryString<CompareSort>("sort", "abs_diff", COMPARE_SORT_KEYS);

type LimitOption = 15 | 30 | 0;
const limit = ref<LimitOption>(15);

const activeScopeMeta = computed(() => COMPARE_SCOPES.find((s) => s.key === scope.value) ?? COMPARE_SCOPES[0]);

const expSummary = computed(() =>
  compare.value ? summarizeCompareNodes(buildCompareNodes(compare.value, "plan")) : null,
);
const revSummary = computed(() =>
  compare.value ? summarizeCompareNodes(buildCompareNodes(compare.value, "revenue_kuan")) : null,
);

const allScopeNodes = computed(() => (compare.value ? buildCompareNodes(compare.value, scope.value) : []));
const scopeSummary = computed(() => summarizeCompareNodes(allScopeNodes.value));

const filteredNodes = computed(() => filterCompareNodes(allScopeNodes.value, filter.value));
const sortedNodes = computed(() => sortCompareNodes(filteredNodes.value, sort.value));

const chartNodes = computed(() =>
  limit.value > 0 && sortedNodes.value.length > limit.value
    ? sortedNodes.value.slice(0, limit.value)
    : sortedNodes.value,
);

const exportRows = computed(() => toCompareExportRows(sortedNodes.value, activeScopeMeta.value.label));
const exportName = computed(() =>
  compare.value
    ? `wanluan-${compare.value.from_year}-${compare.value.to_year}-${scope.value}-${filter.value}`
    : `wanluan-compare`,
);

const legendKeys = DIFF_BANDS.filter((b) => b.key !== "unknown").map((b) => b.key);

const filterCount = (key: CompareFilter): number => {
  const s = scopeSummary.value;
  if (key === "all") return s.total;
  if (key === "new") return s.newCount;
  if (key === "up") return s.upCount;
  return s.downCount;
};

const comparableYears = computed(() => {
  const years = index.value?.years ?? [];
  if (years.length <= 1) return [];
  const minYear = Math.min(...years);
  return years.filter((y) => y > minYear).sort((a, b) => b - a);
});

const panelTitle = computed(() => {
  const label = activeScopeMeta.value.label;
  const f = COMPARE_FILTERS.find((x) => x.key === filter.value)?.label ?? "全部";
  return `${label}增減排行（${f}，共 ${sortedNodes.value.length} 項）`;
});

const panelSubtitle = computed(() => {
  if (!compare.value) return "";
  const base = `${compare.value.to_year} 年度對照 ${compare.value.from_year} 年度；金額單位：元`;
  const clipped =
    limit.value > 0 && sortedNodes.value.length > limit.value
      ? `（圖表顯示前 ${limit.value} 項，資料表格與匯出含全部 ${sortedNodes.value.length} 項）`
      : "";
  return `${base}${clipped}`;
});

const chartAriaLabel = computed(() => {
  if (!compare.value) return "";
  return `${compare.value.to_year} 年度對照 ${compare.value.from_year} 年度${activeScopeMeta.value.label}增減發散長條圖，目前顯示 ${chartNodes.value.length} 項（篩選後共 ${sortedNodes.value.length} 項）。完整數字請切換到資料表格。`;
});

const tableCaption = computed(() =>
  compare.value
    ? `${compare.value.to_year} 年度 vs ${compare.value.from_year} 年度 ${activeScopeMeta.value.label}增減明細`
    : "跨年度比較明細",
);

function diffSymbol(diff: number): string {
  if (diff > 0) return "▲";
  if (diff < 0) return "▼";
  return "＝";
}

function diffTone(diff: number): "good" | "bad" | "neutral" {
  if (diff > 0) return "good";
  if (diff < 0) return "bad";
  return "neutral";
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <h1 class="page-title">
        <template v-if="compare">{{ compare.to_year }} 年度 vs {{ compare.from_year }} 年度比較</template>
        <template v-else>{{ year }} 年度比較</template>
      </h1>
      <p v-if="compare" class="muted lead">
        比較 {{ compare.to_year }} 年度與 {{ compare.from_year }} 年度預算增減情形（金額單位：元；正值為增加 ▲、負值為減少 ▼、★ 為新增項目）。
      </p>
    </header>

    <p v-if="loading" class="muted" role="status" aria-live="polite">載入比較資料中…</p>

    <div v-else-if="error" class="error-box" role="alert">
      <strong>無法載入資料：</strong>{{ error }}
    </div>

    <section v-else-if="!compare" class="card empty-year" aria-labelledby="no-compare-title">
      <h2 id="no-compare-title" class="section-title">{{ year }} 年度尚無跨年度比較資料</h2>
      <p class="muted">
        {{ year }} 年度為本站目前收錄的最早年度，沒有前一年度的對應資料可供跨年度比較。
        您可以改看其他年度的比較結果，或直接瀏覽 {{ year }} 年度的總覽、歲出與歲入資料。
      </p>
      <div class="nav-groups">
        <div v-if="comparableYears.length" class="link-group">
          <span class="group-label muted">切換至可比較年度：</span>
          <div class="link-row">
            <router-link
              v-for="y in comparableYears"
              :key="y"
              class="btn primary"
              :to="{ path: `/${y}/比較` }"
            >
              查看 {{ y }} 年度比較
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

    <template v-else>
      <section v-if="expSummary && revSummary" class="grid kpi" aria-label="年度總額增減摘要">
        <KpiCard
          label="歲出總額增減"
          :value="`${diffSymbol(expSummary.netDiff)} ${fmtSignedYuan(expSummary.netDiff)}`"
          :sub="`${fmtSignedPct(expSummary.netPct)}（${compare.to_year} 年 ${fmtCompact(expSummary.curTotal)} vs ${compare.from_year} 年 ${fmtCompact(expSummary.prevTotal)}）`"
          :tone="diffTone(expSummary.netDiff)"
        />
        <KpiCard
          label="歲入總額增減"
          :value="`${diffSymbol(revSummary.netDiff)} ${fmtSignedYuan(revSummary.netDiff)}`"
          :sub="`${fmtSignedPct(revSummary.netPct)}（${compare.to_year} 年 ${fmtCompact(revSummary.curTotal)} vs ${compare.from_year} 年 ${fmtCompact(revSummary.prevTotal)}）`"
          :tone="diffTone(revSummary.netDiff)"
        />
        <KpiCard
          :label="`${activeScopeMeta.label}項目統計`"
          :value="`共 ${scopeSummary.total} 項`"
          :sub="`★ 新增 ${scopeSummary.newCount}・▲ 增加 ${scopeSummary.upCount}・▼ 減少 ${scopeSummary.downCount}・＝ 持平 ${scopeSummary.flatCount}`"
        />
      </section>

      <nav class="scope-bar" aria-label="比較項目分類">
        <div class="btn-group" role="group" aria-label="選擇歲出或歲入比較層級">
          <button
            v-for="s in COMPARE_SCOPES"
            :key="s.key"
            type="button"
            class="btn"
            :aria-pressed="scope === s.key"
            @click="scope = s.key"
          >
            {{ s.label }}
          </button>
        </div>
        <p v-if="scope === 'object'" class="muted scope-note">
          註：用途別已跨工作計畫依用途別代碼彙總，共 {{ scopeSummary.total }} 項。
        </p>
      </nav>

      <ChartPanel
        :title="panelTitle"
        :subtitle="panelSubtitle"
        :export-rows="exportRows"
        :export-name="exportName"
      >
        <template #toolbar>
          <div class="controls">
            <div class="btn-group" role="group" aria-label="依增減狀態篩選">
              <button
                v-for="f in COMPARE_FILTERS"
                :key="f.key"
                type="button"
                class="btn"
                :aria-pressed="filter === f.key"
                @click="filter = f.key"
              >
                <span v-if="f.symbol" aria-hidden="true">{{ f.symbol }} </span>{{ f.label }}
                <span class="count">({{ filterCount(f.key) }})</span>
              </button>
            </div>

            <div class="select-group">
              <label class="ctrl-label">
                <span class="muted">排序</span>
                <select v-model="sort" aria-label="排序方式">
                  <option v-for="s in COMPARE_SORTS" :key="s.key" :value="s.key">{{ s.label }}</option>
                </select>
              </label>

              <label v-if="sortedNodes.length > 15" class="ctrl-label">
                <span class="muted">圖表筆數</span>
                <select v-model.number="limit" aria-label="圖表顯示筆數">
                  <option :value="15">前 15 項</option>
                  <option :value="30">前 30 項</option>
                  <option :value="0">全部（{{ sortedNodes.length }} 項）</option>
                </select>
              </label>
            </div>
          </div>
        </template>

        <template #chart>
          <DivergingBarChart
            :nodes="chartNodes"
            :from-year="compare.from_year"
            :to-year="compare.to_year"
            :chart-label="chartAriaLabel"
          />
          <DiffLegend :keys="legendKeys" class="legend" />
        </template>

        <template #table>
          <DataTable
            :nodes="sortedNodes"
            :caption="tableCaption"
            :parent-total="scopeSummary.curTotal"
            show-diff
          />
        </template>
      </ChartPanel>
    </template>
  </div>
</template>

<style scoped>
.page > * { min-width: 0; }
.page-head { display: grid; gap: 4px; }
.lead { margin: 0; font-size: var(--fs-sm); }
.section-title { font-size: var(--fs-lg); margin-bottom: 8px; }

.empty-year { display: grid; gap: 12px; }
.empty-year p { margin: 0; }
.nav-groups { display: grid; gap: 12px; }
.link-group { display: grid; gap: 8px; }
.group-label { font-size: var(--fs-sm); }
.link-row { display: flex; flex-wrap: wrap; gap: 8px; }
.link-row .btn { text-decoration: none; display: inline-flex; align-items: center; }

.scope-bar { display: grid; gap: 6px; }
.scope-note { margin: 0; font-size: var(--fs-xs); }

.controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 10px 14px;
}
.btn-group { display: flex; flex-wrap: wrap; gap: 8px; }
.count { font-size: var(--fs-xs); opacity: 0.85; }

.select-group { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.ctrl-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
}
.ctrl-label select {
  font: inherit;
  font-size: var(--fs-sm);
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  min-height: 36px;
  max-width: 100%;
}

.legend { margin-top: 12px; }

@media (max-width: 640px) {
  .select-group { width: 100%; }
  .ctrl-label { flex: 1 1 100%; justify-content: space-between; }
  .ctrl-label select { flex: 1; min-width: 0; }
}
</style>
