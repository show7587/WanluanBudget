<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { fmtCompact, fmtInt, fmtSignedPct, fmtSignedYuan } from "@/data/format";
import type { SeriesDerived, SeriesItem } from "@/data/types";
import type { TrendMode } from "./trendModel";

echarts.use([
  LineChart,
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export interface TrendChartEntry {
  key: string;
  label: string;
  item: SeriesItem;
  derived: SeriesDerived;
  isPrimary: boolean;
}

const props = withDefaults(
  defineProps<{
    years: number[];
    entries: TrendChartEntry[];
    mode: TrendMode;
    yoyMetric?: "pct" | "diff";
    currentYear: number;
    height?: number;
  }>(),
  { yoyMetric: "pct", height: 380 },
);

const el = ref<HTMLDivElement | null>(null);
const chart = shallowRef<echarts.ECharts | null>(null);
let ro: ResizeObserver | null = null;
let mq: MediaQueryList | null = null;
let mo: MutationObserver | null = null;

const PALETTE_VARS = [
  "--cat-1",
  "--cat-2",
  "--cat-3",
  "--cat-4",
  "--cat-5",
  "--cat-6",
  "--cat-7",
  "--cat-8",
] as const;

const SYMBOLS = ["circle", "rect", "triangle", "diamond", "roundRect", "pin", "arrow", "emptyCircle"] as const;

const css = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

const chartAriaLabel = computed(() => {
  if (!props.entries.length) return "跨年度趨勢折線圖（尚未選擇項目）";
  const modeLabel =
    props.mode === "amount"
      ? "各年金額"
      : props.mode === "yoy"
        ? props.yoyMetric === "diff"
          ? "逐年差額"
          : "逐年增減率"
        : "指數（基準年=100）";
  const names = props.entries.map((e) => (e.isPrimary ? `主項目 ${e.label}` : e.label)).join("、");
  return `${props.years.join("、")} 年度 ${modeLabel}折線圖，包含 ${props.entries.length} 個項目：${names}。完整數字請見下方資料表格。`;
});

function legendNameOf(entry: TrendChartEntry): string {
  const prefix = entry.isPrimary ? "★ " : "";
  if (props.mode === "index") {
    const base = entry.derived.index_base_year != null ? `基準 ${entry.derived.index_base_year} 年` : "無基準年";
    return `${prefix}${entry.label}（${base}）`;
  }
  return `${prefix}${entry.label}`;
}

function buildOption(): echarts.EChartsCoreOption {
  const text = css("--text");
  const muted = css("--text-muted");
  const border = css("--border");
  const surface = css("--surface");
  const accent = css("--accent");
  const colors = PALETTE_VARS.map((v) => css(v));

  const years = props.years;
  const xLabels = years.map((y) => (y === props.currentYear ? `${y} 年度（目前）` : `${y} 年度`));
  const curIdx = years.indexOf(props.currentYear);

  const series = props.entries.map((entry, idx) => {
    const color = colors[idx % colors.length];
    const data = years.map((y) => {
      const yk = String(y);
      if (props.mode === "amount") {
        const v = entry.item.amount_元[yk];
        return typeof v === "number" ? v : null;
      }
      if (props.mode === "yoy") {
        const v = props.yoyMetric === "diff" ? entry.derived.diff_元[yk] : entry.derived.pct[yk];
        return typeof v === "number" ? v : null;
      }
      const v = entry.derived.index[yk];
      return typeof v === "number" ? v : null;
    });

    const markLineData: Array<Record<string, unknown>> = [];
    if (idx === 0) {
      if (curIdx >= 0) {
        markLineData.push({
          xAxis: xLabels[curIdx],
          lineStyle: { color: accent, type: "dashed", width: 1.5, opacity: 0.55 },
          label: { show: false },
        });
      }
      if (props.mode === "index") {
        markLineData.push({
          yAxis: 100,
          lineStyle: { color: muted, type: "dotted", width: 1.5 },
          label: { show: true, position: "insideEndTop", formatter: "基準 100", color: muted, fontSize: 11 },
        });
      } else if (props.mode === "yoy") {
        markLineData.push({
          yAxis: 0,
          lineStyle: { color: muted, type: "dotted", width: 1.5 },
          label: { show: false },
        });
      }
    }

    return {
      name: legendNameOf(entry),
      type: "line",
      connectNulls: false,
      showAllSymbol: true,
      symbol: SYMBOLS[idx % SYMBOLS.length],
      symbolSize: entry.isPrimary ? 9 : 7,
      lineStyle: {
        width: entry.isPrimary ? 3 : 2,
        color,
      },
      itemStyle: { color },
      emphasis: { focus: "series" },
      data,
      ...(markLineData.length
        ? {
            markLine: {
              silent: true,
              symbol: ["none", "none"],
              data: markLineData,
            },
          }
        : {}),
    };
  });

  return {
    animationDuration: 300,
    color: colors,
    aria: { enabled: true },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: surface,
      borderColor: border,
      textStyle: { color: text, fontSize: 13 },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [];
        const dataIndex = (list[0] as { dataIndex?: number } | undefined)?.dataIndex;
        if (dataIndex == null || years[dataIndex] == null) return "";
        const y = years[dataIndex];
        const yk = String(y);
        const curTag = y === props.currentYear ? "（目前檢視）" : "";
        const header = `<div style="font-weight:600;margin-bottom:6px">${escapeHtml(`${y} 年度${curTag}`)}</div>`;

        const rows = props.entries
          .map((entry, idx) => {
            const color = colors[idx % colors.length];
            const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${color};margin-right:6px;flex-shrink:0"></span>`;
            const roleTag = entry.isPrimary ? "★ " : "";
            const amt = entry.item.amount_元[yk];
            const diff = entry.derived.diff_元[yk];
            const pct = entry.derived.pct[yk];
            const ix = entry.derived.index[yk];

            let valText = "無資料";
            if (props.mode === "amount") {
              valText = amt == null ? "無資料" : `${fmtInt(amt)} 元（${fmtCompact(amt)}）`;
            } else if (props.mode === "yoy") {
              valText =
                diff == null && pct == null
                  ? "—"
                  : `${fmtSignedYuan(diff)}（${fmtSignedPct(pct)}）`;
            } else {
              const baseNote =
                entry.derived.index_base_year != null ? `基準 ${entry.derived.index_base_year} 年` : "無基準年";
              valText = ix == null ? `—（${baseNote}）` : `${ix.toFixed(2)}（${baseNote}）`;
            }

            return (
              `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:14px;margin:2px 0">` +
              `<span style="display:inline-flex;align-items:center;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${dot}${escapeHtml(`${roleTag}${entry.label}`)}</span>` +
              `<b style="white-space:nowrap">${escapeHtml(valText)}</b>` +
              `</div>`
            );
          })
          .join("");

        return header + rows;
      },
    },
    legend: {
      type: "scroll",
      top: 0,
      left: 0,
      right: 0,
      textStyle: { color: text, fontSize: 12 },
      pageTextStyle: { color: muted },
      pageIconColor: accent,
      pageIconInactiveColor: border,
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
      boundaryGap: true,
      axisLine: { lineStyle: { color: border } },
      axisTick: { show: false },
      axisLabel: {
        color: (val: string) => (val.includes("目前") ? accent : text),
        fontWeight: (val: string) => (val.includes("目前") ? 700 : 400),
        fontSize: 12,
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
        formatter: (v: number) => {
          if (props.mode === "amount") return fmtCompact(v);
          if (props.mode === "yoy") return props.yoyMetric === "diff" ? fmtCompact(v) : `${v}%`;
          return String(v);
        },
      },
    },
    series,
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

watch(() => [props.years, props.entries, props.mode, props.yoyMetric, props.currentYear], render, { deep: true });
</script>

<template>
  <div
    ref="el"
    class="trend-chart"
    role="img"
    :aria-label="chartAriaLabel"
    :style="{ height: `${height}px` }"
  ></div>
</template>

<style scoped>
.trend-chart {
  width: 100%;
  min-height: 280px;
}
</style>
