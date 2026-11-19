<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import * as echarts from "echarts/core";
import { PieChart } from "echarts/charts";
import { TitleComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { TreeNode } from "@/data/types";
import { diffBand } from "@/data/diffScale";
import { fmtCompact, fmtInt, fmtPct, fmtSignedPct, fmtSignedYuan } from "@/data/format";

echarts.use([PieChart, TitleComponent, TooltipComponent, CanvasRenderer]);

const props = withDefaults(
  defineProps<{
    nodes: TreeNode[];
    total: number;
    centerTitle: string;
    chartTitle: string;
    height?: number;
  }>(),
  { height: 280 },
);

const emit = defineEmits<{ (e: "select", node: TreeNode): void }>();

const el = ref<HTMLDivElement | null>(null);
const chart = shallowRef<echarts.ECharts | null>(null);
let ro: ResizeObserver | null = null;
let mq: MediaQueryList | null = null;
let mo: MutationObserver | null = null;

const css = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";

const sorted = computed(() => [...props.nodes].sort((a, b) => b.amount - a.amount));

const shareOf = (amount: number): number => (props.total > 0 ? (amount / props.total) * 100 : 0);

const chartLabel = computed(() => {
  if (!sorted.value.length) return `${props.chartTitle}（無資料）`;
  const top = sorted.value
    .slice(0, 5)
    .map((n) => `${n.name} ${fmtCompact(n.amount)}（${fmtPct(shareOf(n.amount))}）`)
    .join("、");
  return `${props.chartTitle}，總額 ${fmtCompact(props.total)}，主要項目：${top}`;
});

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function tooltipHtml(n: TreeNode): string {
  const share = shareOf(n.amount);
  const band = diffBand(n.status, n.pct);
  const rows = [
    ["預算數", `${fmtInt(n.amount)} 元`],
    ["占總額", fmtPct(share)],
  ];
  if (n.status !== "unknown") {
    rows.push(["上年度", n.prev == null ? "—" : `${fmtInt(n.prev)} 元`]);
    rows.push(["增減", `${fmtSignedYuan(n.diff)}（${fmtSignedPct(n.pct)}）`]);
    rows.push(["狀態", `${band.symbol} ${band.label}`]);
  }
  if (n.children.length) rows.push(["操作", "點擊前往細項查詢"]);
  return (
    `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(n.name)}</div>` +
    rows
      .map(
        ([k, v]) =>
          `<div style="display:flex;justify-content:space-between;gap:16px"><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`,
      )
      .join("")
  );
}

function buildOption(): echarts.EChartsCoreOption {
  const cats = Array.from({ length: 8 }, (_, i) => css(`--cat-${i + 1}`));
  const surface = css("--surface");
  const border = css("--border");
  const text = css("--text");
  const muted = css("--text-muted");

  const data = sorted.value
    .filter((n) => n.amount > 0)
    .map((n, i) => ({
      name: n.name,
      value: n.amount,
      node: n,
      itemStyle: { color: cats[i % cats.length] },
    }));

  return {
    animationDuration: 350,
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: surface,
      borderColor: border,
      textStyle: { color: text, fontSize: 13 },
      formatter: (p: { data?: { node?: TreeNode } }) => (p.data?.node ? tooltipHtml(p.data.node) : ""),
    },
    title: {
      text: props.centerTitle,
      subtext: fmtCompact(props.total),
      left: "center",
      top: "center",
      itemGap: 4,
      textStyle: { color: muted, fontSize: 12, fontWeight: 500 },
      subtextStyle: { color: text, fontSize: 17, fontWeight: 700 },
    },
    series: [
      {
        type: "pie",
        radius: ["54%", "84%"],
        center: ["50%", "50%"],
        minAngle: 3,
        avoidLabelOverlap: true,
        itemStyle: {
          borderColor: surface,
          borderWidth: 2,
          borderRadius: 4,
        },
        label: { show: false },
        labelLine: { show: false },
        emphasis: {
          scale: true,
          scaleSize: 5,
        },
        data,
      },
    ],
  };
}

function render(): void {
  if (!chart.value) return;
  chart.value.setOption(buildOption(), true);
}

onMounted(() => {
  if (!el.value) return;
  chart.value = echarts.init(el.value, undefined, { renderer: "canvas" });
  chart.value.on("click", (p: { data?: unknown }) => {
    const n = (p.data as { node?: TreeNode } | undefined)?.node;
    if (n) emit("select", n);
  });
  render();
  ro = new ResizeObserver(() => chart.value?.resize());
  ro.observe(el.value);
  mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", render);
  mo = new MutationObserver(render);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
});

onBeforeUnmount(() => {
  ro?.disconnect();
  mq?.removeEventListener("change", render);
  mo?.disconnect();
  chart.value?.dispose();
  chart.value = null;
});

watch(() => [props.nodes, props.total, props.centerTitle], render, { deep: true });
</script>

<template>
  <div class="structure">
    <div
      ref="el"
      class="donut"
      role="img"
      :aria-label="chartLabel"
      :style="{ height: height + 'px' }"
    ></div>
    <ul class="legend" :aria-label="`${chartTitle}項目列表`">
      <li v-for="(n, i) in sorted" :key="n.id" class="legend-item">
        <button
          type="button"
          class="legend-btn"
          @click="emit('select', n)"
        >
          <span class="swatch" :style="{ background: `var(--cat-${(i % 8) + 1})` }" aria-hidden="true"></span>
          <span class="name">{{ n.name }}</span>
          <span class="meta num">
            <span class="pct">{{ fmtPct(shareOf(n.amount)) }}</span>
            <span class="amt muted">{{ fmtCompact(n.amount) }}</span>
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.structure {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.donut {
  width: 100%;
  min-height: 240px;
}
.legend {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.legend-item {
  min-width: 0;
}
.legend-btn {
  width: 100%;
  appearance: none;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  padding: 6px 8px;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  cursor: pointer;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  text-align: left;
}
.legend-btn:hover {
  background: var(--surface-2);
  border-color: var(--border);
}
.swatch {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}
.pct {
  font-weight: 600;
}
.amt {
  font-size: var(--fs-xs);
}
</style>
