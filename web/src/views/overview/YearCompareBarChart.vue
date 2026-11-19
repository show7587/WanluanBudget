<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { fmtCompact, fmtInt, fmtSignedYuan, fmtYuan } from "@/data/format";

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export interface YearSummaryItem {
  year: number;
  revenue_total_元: number;
  expenditure_total_元: number;
}

const props = withDefaults(
  defineProps<{
    summaries: YearSummaryItem[];
    currentYear: number;
    height?: number;
  }>(),
  { height: 340 },
);

const el = ref<HTMLDivElement | null>(null);
const chart = shallowRef<echarts.ECharts | null>(null);
let ro: ResizeObserver | null = null;
let mq: MediaQueryList | null = null;
let mo: MutationObserver | null = null;

const css = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";

const sorted = computed(() => [...props.summaries].sort((a, b) => a.year - b.year));

const chartLabel = computed(() => {
  if (!sorted.value.length) return "歷年歲入與歲出對照長條圖（無資料）";
  const parts = sorted.value.map((s) => {
    const bal = s.revenue_total_元 - s.expenditure_total_元;
    const status = bal > 0 ? "賸餘" : bal < 0 ? "短絀" : "收支平衡";
    return `${s.year}年度歲入${fmtYuan(s.revenue_total_元)}、歲出${fmtYuan(s.expenditure_total_元)}（${status}${fmtYuan(Math.abs(bal))}）`;
  });
  return `歷年歲入與歲出對照長條圖：${parts.join("；")}`;
});

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function buildOption(): echarts.EChartsCoreOption {
  const text = css("--text");
  const muted = css("--text-muted");
  const border = css("--border");
  const surface = css("--surface");
  const catRev = css("--cat-1");
  const catExp = css("--cat-2");
  const accent = css("--accent");

  const items = sorted.value;
  const xLabels = items.map((s) => (s.year === props.currentYear ? `${s.year} 年度（目前）` : `${s.year} 年度`));

  return {
    animationDuration: 350,
    color: [catRev, catExp],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      confine: true,
      backgroundColor: surface,
      borderColor: border,
      textStyle: { color: text, fontSize: 13 },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [];
        const idx = (list[0] as { dataIndex?: number } | undefined)?.dataIndex;
        if (idx == null || !items[idx]) return "";
        const item = items[idx];
        const bal = item.revenue_total_元 - item.expenditure_total_元;
        const balTag = bal > 0 ? "▲ 賸餘" : bal < 0 ? "▼ 短絀" : "＝ 收支平衡";
        const curTag = item.year === props.currentYear ? "（目前檢視）" : "";
        const rows = [
          ["歲入總額", `${fmtInt(item.revenue_total_元)} 元（${fmtCompact(item.revenue_total_元)}）`],
          ["歲出總額", `${fmtInt(item.expenditure_total_元)} 元（${fmtCompact(item.expenditure_total_元)}）`],
          ["歲入歲出餘絀", `${fmtSignedYuan(bal)}（${balTag}）`],
        ];
        return (
          `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(`${item.year} 年度${curTag}`)}</div>` +
          rows
            .map(
              ([k, v]) =>
                `<div style="display:flex;justify-content:space-between;gap:16px"><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`,
            )
            .join("")
        );
      },
    },
    legend: {
      top: 0,
      left: 0,
      textStyle: { color: text, fontSize: 13 },
      data: ["歲入", "歲出"],
    },
    grid: {
      top: 44,
      right: 16,
      bottom: 32,
      left: 16,
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: xLabels,
      axisLine: { lineStyle: { color: border } },
      axisTick: { show: false },
      axisLabel: {
        color: (val: string) => (val.includes("目前") ? accent : text),
        fontWeight: (val: string) => (val.includes("目前") ? 700 : 400),
        fontSize: 13,
      },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: border, type: "dashed" } },
      axisLabel: {
        color: muted,
        fontSize: 12,
        formatter: (v: number) => fmtCompact(v),
      },
    },
    series: [
      {
        name: "歲入",
        type: "bar",
        barMaxWidth: 44,
        barGap: "18%",
        data: items.map((s) => ({
          value: s.revenue_total_元,
          itemStyle: {
            color: catRev,
            borderRadius: [6, 6, 0, 0],
            borderColor: s.year === props.currentYear ? accent : "transparent",
            borderWidth: s.year === props.currentYear ? 2 : 0,
          },
        })),
        label: {
          show: true,
          position: "top",
          color: text,
          fontSize: 11,
          formatter: (p: { value?: unknown }) => (typeof p.value === "number" ? fmtCompact(p.value) : ""),
        },
      },
      {
        name: "歲出",
        type: "bar",
        barMaxWidth: 44,
        data: items.map((s) => ({
          value: s.expenditure_total_元,
          itemStyle: {
            color: catExp,
            borderRadius: [6, 6, 0, 0],
            borderColor: s.year === props.currentYear ? accent : "transparent",
            borderWidth: s.year === props.currentYear ? 2 : 0,
          },
        })),
        label: {
          show: true,
          position: "top",
          color: text,
          fontSize: 11,
          formatter: (p: { value?: unknown }) => (typeof p.value === "number" ? fmtCompact(p.value) : ""),
        },
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

watch(() => [props.summaries, props.currentYear], render, { deep: true });
</script>

<template>
  <div
    ref="el"
    class="bar-chart"
    role="img"
    :aria-label="chartLabel"
    :style="{ height: height + 'px' }"
  ></div>
</template>

<style scoped>
.bar-chart { width: 100%; min-height: 260px; }
</style>
