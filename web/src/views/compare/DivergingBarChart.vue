<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { TreeNode } from "@/data/types";
import { diffBand } from "@/data/diffScale";
import { fmtCompact, fmtInt, fmtSignedPct, fmtSignedYuan } from "@/data/format";

echarts.use([BarChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

const props = defineProps<{
  nodes: TreeNode[];
  fromYear: number;
  toYear: number;
  chartLabel: string;
}>();

const el = ref<HTMLDivElement | null>(null);
const chart = shallowRef<echarts.ECharts | null>(null);
const width = ref(720);
let ro: ResizeObserver | null = null;
let mq: MediaQueryList | null = null;
let themeObserver: MutationObserver | null = null;

const chartHeight = computed(() => Math.max(240, props.nodes.length * 36 + 56));
const isNarrow = computed(() => width.value < 560);

const css = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function fmtSignedCompact(n: number): string {
  if (n > 0) return `+${fmtCompact(n)}`;
  return fmtCompact(n);
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function barLabel(n: TreeNode, narrow: boolean): string {
  const diff = n.diff ?? 0;
  const band = diffBand(n.status, n.pct);
  const compact = fmtSignedCompact(diff);
  if (narrow) return `${band.symbol} ${compact}`;
  const suffix =
    n.status === "new"
      ? "新增"
      : n.status === "removed"
        ? "本年度無預算"
        : fmtSignedPct(n.pct);
  return `${band.symbol} ${compact}（${suffix}）`;
}

function tooltipHtml(n: TreeNode): string {
  const band = diffBand(n.status, n.pct);
  const rows: Array<[string, string]> = [
    [`${props.toYear} 年度`, `${fmtInt(n.amount)} 元`],
    [`${props.fromYear} 年度`, n.prev == null ? "—" : `${fmtInt(n.prev)} 元`],
    ["增減金額", fmtSignedYuan(n.diff)],
    ["增減 %", n.status === "new" ? "新增項目" : fmtSignedPct(n.pct)],
    ["狀態", `${band.symbol} ${band.label}`],
  ];
  return (
    `<div style="font-weight:600;margin-bottom:4px;max-width:280px;white-space:normal">${escapeHtml(n.name)}</div>` +
    rows
      .map(
        ([k, v]) =>
          `<div style="display:flex;justify-content:space-between;gap:16px"><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`,
      )
      .join("")
  );
}

function buildOption(): echarts.EChartsCoreOption {
  const narrow = isNarrow.value;
  const textColor = css("--text");
  const mutedColor = css("--text-muted");
  const borderColor = css("--border");
  const surfaceColor = css("--surface");

  const diffs = props.nodes.map((n) => n.diff ?? 0);
  const maxPos = Math.max(0, ...diffs);
  const maxNeg = Math.max(0, ...diffs.map((d) => -d));
  const span = Math.max(maxPos, maxNeg);
  const padRatio = narrow ? 1.0 : 0.42;

  // 負值標籤放在零線右側，所以右側至少要留 padRatio 的空間給它們
  const axisMin = span === 0 ? -1 : maxNeg > 0 ? -Math.ceil(maxNeg * 1.05) : 0;
  const axisMax = span === 0 ? 1 : Math.ceil(Math.max(maxPos, span * 0.5) * (1 + padRatio));

  const categories = props.nodes.map((n) => n.name);
  const data = props.nodes.map((n) => {
    const val = n.diff ?? 0;
    const band = diffBand(n.status, n.pct);
    const fill = css(band.cssVar);
    return {
      value: val,
      node: n,
      itemStyle: {
        color: fill,
        borderColor: css("--text-muted"),
        borderWidth: 1,
        borderRadius: val >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
      },
      label: {
        show: true,
        // 負值長條的標籤也放在零線右側（該列右側是空的），避免蓋到左邊的類別軸文字
        position: "right",
        distance: 6,
        color: textColor,
        fontSize: narrow ? 11 : 12,
        formatter: () => barLabel(n, narrow),
      },
    };
  });

  return {
    animationDuration: 300,
    animationDurationUpdate: 300,
    grid: {
      top: 12,
      bottom: 32,
      left: narrow ? 8 : 12,
      right: narrow ? 12 : 18,
      containLabel: true,
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      confine: true,
      backgroundColor: surfaceColor,
      borderColor,
      textStyle: { color: textColor, fontSize: 13 },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params];
        const first = list[0] as { data?: { node?: TreeNode } } | undefined;
        return first?.data?.node ? tooltipHtml(first.data.node) : "";
      },
    },
    xAxis: {
      type: "value",
      min: axisMin,
      max: axisMax,
      splitNumber: narrow ? 3 : 5,
      axisLabel: {
        color: mutedColor,
        fontSize: narrow ? 11 : 12,
        formatter: (v: number) => (v === 0 ? "0" : fmtCompact(v)),
      },
      splitLine: {
        lineStyle: { color: borderColor, type: "dashed" },
      },
      axisLine: { show: false },
    },
    yAxis: {
      type: "category",
      inverse: true,
      data: categories,
      axisTick: { show: false },
      axisLine: {
        show: false,
        onZero: false,
      },
      axisLabel: {
        color: textColor,
        fontSize: narrow ? 11 : 12,
        formatter: (v: string) => truncate(v, narrow ? 9 : 16),
      },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 22,
        data,
        markLine: {
          silent: true,
          symbol: "none",
          animation: false,
          lineStyle: { color: mutedColor, type: "solid", width: 1.5 },
          label: { show: false },
          data: [{ xAxis: 0 }],
        },
      },
    ],
  };
}

function render(): void {
  if (!chart.value || !props.nodes.length) return;
  chart.value.setOption(buildOption(), true);
}

async function initOrUpdate(): Promise<void> {
  await nextTick();
  if (!props.nodes.length) {
    chart.value?.dispose();
    chart.value = null;
    return;
  }
  if (!el.value) return;
  if (!chart.value) {
    chart.value = echarts.init(el.value, undefined, { renderer: "canvas" });
  }
  width.value = el.value.clientWidth || 720;
  render();
  chart.value.resize();
}

onMounted(() => {
  void initOrUpdate();
  ro = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect.width;
    if (w && Math.abs(w - width.value) > 4) {
      width.value = w;
      render();
    }
    chart.value?.resize();
  });
  if (el.value) ro.observe(el.value);
  mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", render);
  themeObserver = new MutationObserver(render);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
});

onBeforeUnmount(() => {
  ro?.disconnect();
  mq?.removeEventListener("change", render);
  themeObserver?.disconnect();
  chart.value?.dispose();
  chart.value = null;
});

watch(
  () => [props.nodes, props.fromYear, props.toYear],
  () => {
    void initOrUpdate().then(() => {
      if (el.value && ro) {
        ro.disconnect();
        ro.observe(el.value);
      }
    });
  },
);
</script>

<template>
  <div v-if="nodes.length" class="bar-wrap">
    <div
      ref="el"
      class="bar-chart"
      role="img"
      :aria-label="chartLabel"
      :style="{ height: `${chartHeight}px` }"
    ></div>
  </div>
  <p v-else class="empty muted" role="status">目前篩選條件下沒有符合的項目。</p>
</template>

<style scoped>
.bar-wrap { width: 100%; overflow: hidden; }
.bar-chart { width: 100%; min-height: 240px; }
.empty { margin: 16px 0; text-align: center; }
</style>
