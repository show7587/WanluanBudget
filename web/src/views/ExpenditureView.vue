<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, type RouteLocationRaw } from "vue-router";
import type { ExpenditureView, TreeNode } from "@/data/types";
import { normalizeExpenditure } from "@/data/normalize";
import { fmtCompact, fmtYuan } from "@/data/format";
import { useBudget } from "@/composables/useBudget";
import { useQueryPath, useQueryString } from "@/composables/useRouteState";
import DrillExplorer from "@/components/DrillExplorer.vue";
import { buildTrendRoute } from "./trend/trendModel";

const VIEWS: readonly ExpenditureView[] = ["政事別", "機關別", "用途別"];

const VIEW_META: Record<ExpenditureView, { hierarchy: string; slug: string }> = {
  政事別: { hierarchy: "政事別 → 機關 → 工作計畫 → 用途別", slug: "function" },
  機關別: { hierarchy: "機關 → 工作計畫 → 用途別", slug: "agency" },
  用途別: { hierarchy: "用途別大類 → 用途別 → 工作計畫", slug: "object" },
};

const route = useRoute();
const year = computed(() => Number(route.params.year) || 0);
const { loading, error, index, data, compare } = useBudget(year);

const view = useQueryString<ExpenditureView>("view", "政事別", VIEWS, ["path"]);
const path = useQueryPath();
const colorBy = ref<"size" | "diff">("size");
const tabRefs = ref<(HTMLButtonElement | null)[]>([]);

const roots = computed(() =>
  data.value ? normalizeExpenditure(data.value, compare.value, view.value) : [],
);
const hasSeries = computed(() => (index.value?.series_years?.length ?? 0) >= 2);

/**
 * 歲出 drill：只限政事別／機關別視角下的工作計畫（plan:）與計畫下用途別（object:）；
 * 政事別、機關與用途別視角的跨計畫彙總節點一律不顯示入口。
 */
function trendLinkFor(node: TreeNode): RouteLocationRaw | null {
  if (!hasSeries.value || !year.value) return null;
  if (view.value !== "政事別" && view.value !== "機關別") return null;
  if (node.id.startsWith("plan:") || node.id.startsWith("object:")) {
    return buildTrendRoute(year.value, `${year.value}:${node.id}`);
  }
  return null;
}

const totalAmount = computed(() => data.value?.overview.expenditure_total_元 ?? 0);

const hasDiff = computed(() => Boolean(compare.value) || view.value === "政事別");
const effectiveColorBy = computed<"size" | "diff">(() => (hasDiff.value ? colorBy.value : "size"));

const rootLabel = computed(() => `歲出（${view.value}）`);
const panelTitle = computed(() => `${year.value} 年度歲出（${view.value}）`);
const exportName = computed(() => `wanluan-${year.value}-expenditure-${VIEW_META[view.value].slug}`);

const compareNote = computed(() => {
  const hierarchy = `階層：${VIEW_META[view.value].hierarchy}`;
  if (compare.value) {
    return `${hierarchy}｜較 ${compare.value.from_year} 年度預算比較`;
  }
  if (view.value === "政事別") {
    return `${hierarchy}｜無跨年度比較檔，政事別款層級上年度數字取自預算書`;
  }
  return `${hierarchy}｜本年度無跨年度比較資料`;
});

function selectView(next: ExpenditureView): void {
  if (view.value !== next) {
    view.value = next;
  }
}

function onTabKeydown(e: KeyboardEvent, idx: number): void {
  let nextIdx = idx;
  if (e.key === "ArrowRight") nextIdx = (idx + 1) % VIEWS.length;
  else if (e.key === "ArrowLeft") nextIdx = (idx - 1 + VIEWS.length) % VIEWS.length;
  else if (e.key === "Home") nextIdx = 0;
  else if (e.key === "End") nextIdx = VIEWS.length - 1;
  else return;

  e.preventDefault();
  selectView(VIEWS[nextIdx]);
  tabRefs.value[nextIdx]?.focus();
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="title-block">
        <h1 class="page-title">{{ year }} 年度歲出</h1>
        <p v-if="data" class="summary muted">
          歲出總額：<strong class="num">{{ fmtYuan(totalAmount) }}</strong>（{{ fmtCompact(totalAmount) }}）
        </p>
      </div>

      <div class="controls">
        <div class="tabs" role="tablist" aria-label="歲出分類視角">
          <button
            v-for="(v, idx) in VIEWS"
            :key="v"
            :id="`tab-exp-${VIEW_META[v].slug}`"
            :ref="(el) => { tabRefs[idx] = el as HTMLButtonElement | null; }"
            class="btn tab"
            type="button"
            role="tab"
            :aria-selected="view === v"
            aria-controls="panel-expenditure"
            :tabindex="view === v ? 0 : -1"
            @click="selectView(v)"
            @keydown="onTabKeydown($event, idx)"
          >
            {{ v }}
          </button>
        </div>

        <div class="color-switch" role="group" aria-label="圖表著色方式">
          <button
            class="btn"
            type="button"
            :aria-pressed="effectiveColorBy === 'size'"
            @click="colorBy = 'size'"
          >
            依金額（類別色）
          </button>
          <button
            class="btn"
            type="button"
            :aria-pressed="effectiveColorBy === 'diff'"
            :disabled="!hasDiff"
            :title="hasDiff ? '依較上年度增減百分比著色' : '本年度此視角無上年度比較資料'"
            @click="colorBy = 'diff'"
          >
            依較上年度增減
          </button>
        </div>
      </div>
    </header>

    <div
      id="panel-expenditure"
      class="panel-wrap"
      role="tabpanel"
      :aria-labelledby="`tab-exp-${VIEW_META[view].slug}`"
    >
      <p v-if="view === '用途別'" class="notice" role="note">
        <strong>分類說明：</strong>大類為依用途別代碼第 1 碼的名稱分類，不是經常／資本拆分。
      </p>

      <div v-if="loading && !data" class="card muted" role="status" aria-live="polite">
        載入 {{ year }} 年度歲出資料中…
      </div>

      <div v-else-if="error" class="error-box" role="alert">
        <strong>無法載入 {{ year }} 年度歲出資料</strong>
        <p class="muted err-msg">{{ error }}</p>
      </div>

      <DrillExplorer
        v-else-if="data && roots.length"
        v-model:path="path"
        :roots="roots"
        :root-label="rootLabel"
        :title="panelTitle"
        :color-by="effectiveColorBy"
        :show-diff="hasDiff"
        :export-name="exportName"
        :compare-note="compareNote"
        :trend-link-for="trendLinkFor"
      />

      <div v-else class="card muted" role="status">
        查無 {{ year }} 年度歲出資料。
      </div>
    </div>
  </div>
</template>

<style scoped>
.page > * {
  min-width: 0;
}

.page-head {
  display: grid;
  gap: 12px;
}

.title-block {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 16px;
}

.summary {
  margin: 0;
  font-size: var(--fs-sm);
}

.summary strong {
  color: var(--text);
}

.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 16px;
}

.tabs,
.color-switch {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tab[aria-selected="true"] {
  background: var(--accent);
  color: var(--accent-contrast);
  border-color: var(--accent);
}

.panel-wrap {
  display: grid;
  gap: var(--gap);
  min-width: 0;
}

.panel-wrap > * {
  min-width: 0;
}

.notice {
  margin: 0;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 4px solid var(--accent);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--text);
}

.err-msg {
  margin: 6px 0 0;
  font-size: var(--fs-sm);
}
</style>
