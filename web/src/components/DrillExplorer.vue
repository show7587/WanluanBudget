<script setup lang="ts">
import { computed } from "vue";
import type { RouteLocationRaw } from "vue-router";
import type { TreeNode } from "@/data/types";
import { findByPath, flatten } from "@/data/normalize";
import { fmtCompact, fmtInt } from "@/data/format";
import ChartPanel from "./ChartPanel.vue";
import TreemapChart from "./TreemapChart.vue";
import DataTable from "./DataTable.vue";
import Breadcrumb, { type Crumb } from "./Breadcrumb.vue";
import DiffLegend from "./DiffLegend.vue";

/** 共用的 drill-down 探索器：麵包屑 + treemap + 資料表格 + 匯出。路徑由父層以 v-model:path 持有（同步到 URL）。 */
const props = withDefaults(
  defineProps<{
    roots: TreeNode[];
    path: string[];
    rootLabel: string;
    title: string;
    colorBy?: "size" | "diff";
    showDiff?: boolean;
    exportName?: string;
    /** 比較年度說明，例如「較 115 年度」 */
    compareNote?: string;
    /** 若提供，於支援趨勢的節點顯示「看趨勢」入口 */
    trendLinkFor?: (node: TreeNode) => RouteLocationRaw | null;
  }>(),
  { colorBy: "size", showDiff: true },
);
const emit = defineEmits<{ (e: "update:path", ids: string[]): void }>();

const resolved = computed(() => {
  const { node, trail } = findByPath(props.roots, props.path);
  // 路徑失效（資料換年度後找不到）→ 退回根層
  return props.path.length && !node ? { node: null, trail: [] as TreeNode[] } : { node, trail };
});
const current = computed<TreeNode | null>(() => resolved.value.node);
const currentTrendLink = computed(() =>
  current.value && props.trendLinkFor ? props.trendLinkFor(current.value) : null,
);
const level = computed<TreeNode[]>(() => (current.value ? current.value.children : props.roots));
const levelTotal = computed(() => level.value.reduce((s, n) => s + n.amount, 0));
const parentTotal = computed(() => (current.value ? current.value.amount : levelTotal.value));

const crumbs = computed<Crumb[]>(() => {
  const items: Crumb[] = [{ label: props.rootLabel, onSelect: () => emit("update:path", []) }];
  resolved.value.trail.forEach((n, i) =>
    items.push({ label: n.name, onSelect: () => emit("update:path", resolved.value.trail.slice(0, i + 1).map((t) => t.id)) }),
  );
  return items;
});

const heading = computed(() =>
  current.value ? `${current.value.name}：${fmtInt(current.value.amount)} 元` : `${props.rootLabel}：${fmtInt(levelTotal.value)} 元`,
);
const ariaLabel = computed(
  () =>
    `${props.title}矩形樹狀圖，目前位於「${crumbs.value.at(-1)?.label}」，共 ${level.value.length} 項，合計 ${fmtCompact(levelTotal.value)}。完整數字請切換到資料表格。`,
);
const rows = computed(() => flatten(level.value));

function drill(n: TreeNode): void {
  emit("update:path", [...resolved.value.trail.map((t) => t.id), n.id]);
}
function up(): void {
  if (resolved.value.trail.length) emit("update:path", resolved.value.trail.slice(0, -1).map((t) => t.id));
}
</script>

<template>
  <ChartPanel :title="heading" :subtitle="compareNote" :export-rows="rows" :export-name="exportName">
    <template #toolbar>
      <div class="toolbar-row">
        <Breadcrumb :items="crumbs" />
        <router-link v-if="current && currentTrendLink" class="btn trend-btn" :to="currentTrendLink">
          看「{{ current.name }}」趨勢
        </router-link>
      </div>
      <p v-if="resolved.trail.length" class="hint muted">提示：點圖表空白處或麵包屑可回上一層。</p>
    </template>
    <template #chart>
      <TreemapChart
        :nodes="level"
        :parent-total="parentTotal"
        :color-by="colorBy"
        :chart-label="ariaLabel"
        @drill="drill"
        @up="up"
      />
      <DiffLegend v-if="colorBy === 'diff'" class="legend" />
    </template>
    <template #table>
      <DataTable
        :nodes="level"
        :caption="heading"
        :parent-total="parentTotal"
        :show-diff="showDiff"
        :trend-link-for="trendLinkFor"
        @drill="drill"
      />
    </template>
  </ChartPanel>
</template>

<style scoped>
.toolbar-row { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px 12px; }
.trend-btn { text-decoration: none; display: inline-flex; align-items: center; font-size: var(--fs-xs); padding: 4px 12px; min-height: 32px; }
.hint { margin: 0; font-size: var(--fs-sm); }
.legend { margin-top: 12px; }
</style>
