<script setup lang="ts">
import { ref } from "vue";
import type { FlatRow } from "@/data/normalize";
import { download, rowsToCsv, rowsToJson } from "@/utils/export";

/** 圖表容器：標題、圖／表切換（無障礙替代檢視）、匯出 CSV／JSON */
const props = defineProps<{
  title: string;
  subtitle?: string;
  /** 匯出用資料（目前檢視的節點）；沒有則不顯示匯出按鈕 */
  exportRows?: FlatRow[];
  exportName?: string;
}>();

const mode = ref<"chart" | "table">("chart");
const uid = `panel-${Math.random().toString(36).slice(2, 8)}`;

function exportAs(kind: "csv" | "json"): void {
  const rows = props.exportRows ?? [];
  const base = props.exportName ?? "budget";
  if (kind === "csv") download(`${base}.csv`, rowsToCsv(rows), "text/csv");
  else download(`${base}.json`, rowsToJson(rows), "application/json");
}
</script>

<template>
  <section class="card panel" :aria-labelledby="`${uid}-t`">
    <header class="head">
      <div>
        <h2 :id="`${uid}-t`" class="title">{{ title }}</h2>
        <p v-if="subtitle" class="muted sub">{{ subtitle }}</p>
      </div>
      <div class="actions" role="group" aria-label="檢視方式">
        <button class="btn" type="button" :aria-pressed="mode === 'chart'" @click="mode = 'chart'">圖表</button>
        <button class="btn" type="button" :aria-pressed="mode === 'table'" @click="mode = 'table'">資料表格</button>
      </div>
    </header>
    <slot name="toolbar" />
    <div v-show="mode === 'chart'"><slot name="chart" /></div>
    <div v-show="mode === 'table'"><slot name="table" /></div>
    <slot />
    <footer v-if="exportRows" class="foot">
      <span class="muted">匯出目前檢視：</span>
      <button class="btn" type="button" @click="exportAs('csv')">CSV</button>
      <button class="btn" type="button" @click="exportAs('json')">JSON</button>
    </footer>
  </section>
</template>

<style scoped>
.panel { display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.panel > * { min-width: 0; }
.head { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: flex-start; }
.title { font-size: var(--fs-lg); }
.sub { margin: 2px 0 0; font-size: var(--fs-sm); }
.actions { display: flex; gap: 8px; }
.foot { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
