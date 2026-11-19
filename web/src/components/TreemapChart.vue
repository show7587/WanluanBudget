<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import * as echarts from "echarts/core";
import { TreemapChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { TreeNode } from "@/data/types";
import { diffBand } from "@/data/diffScale";
import { fmtCompact, fmtPct, fmtSignedPct, fmtSignedYuan, fmtInt } from "@/data/format";

echarts.use([TreemapChart, TooltipComponent, CanvasRenderer]);

const props = withDefaults(
  defineProps<{
    /** 目前這一層要畫的節點（不含孫節點，drill-down 由父元件換資料） */
    nodes: TreeNode[];
    /** 上一層總額，用來算「占上層 %」；沒有時用 nodes 加總 */
    parentTotal?: number;
    /** size：以類別色區分；diff：以增減 % 發散色階上色 */
    colorBy?: "size" | "diff";
    chartLabel: string;
    height?: number;
  }>(),
  { colorBy: "size", height: 460 },
);

const emit = defineEmits<{ (e: "drill", node: TreeNode): void; (e: "up"): void }>();

const el = ref<HTMLDivElement | null>(null);
const chart = shallowRef<echarts.ECharts | null>(null);
let ro: ResizeObserver | null = null;
let mq: MediaQueryList | null = null;

const css = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

/** 依底色亮度挑黑／白字，確保標籤對比 */
function textOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return "#111";
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.4 ? "#111827" : "#ffffff";
}

const total = computed(() => props.parentTotal ?? props.nodes.reduce((s, n) => s + n.amount, 0));
const drawable = computed(() => props.nodes.filter((n) => n.amount > 0));

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function tooltipHtml(n: TreeNode): string {
  const share = total.value ? (n.amount / total.value) * 100 : 0;
  const band = diffBand(n.status, n.pct);
  const rows = [
    ["預算數", `${fmtInt(n.amount)} 元`],
    ["占本層", fmtPct(share)],
  ];
  if (n.status !== "unknown") {
    rows.push(["上年度", n.prev == null ? "—" : `${fmtInt(n.prev)} 元`]);
    rows.push(["增減", `${fmtSignedYuan(n.diff)}（${fmtSignedPct(n.pct)}）`]);
    rows.push(["狀態", `${band.symbol} ${band.label}`]);
  }
  if (n.children.length) rows.push(["操作", "點擊展開下一層"]);
  return (
    `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(n.name)}</div>` +
    rows.map(([k, v]) => `<div style="display:flex;justify-content:space-between;gap:16px"><span>${k}</span><b>${escapeHtml(v)}</b></div>`).join("")
  );
}

function buildOption(): echarts.EChartsCoreOption {
  const cats = Array.from({ length: 8 }, (_, i) => css(`--cat-${i + 1}`));
  const surface = css("--surface");
  const data = drawable.value.map((n, i) => {
    const fill =
      props.colorBy === "diff" ? css(diffBand(n.status, n.pct).cssVar) : cats[i % cats.length];
    const band = diffBand(n.status, n.pct);
    return {
      name: n.name,
      value: n.amount,
      node: n,
      itemStyle: { color: fill },
      label: {
        color: textOn(fill),
        formatter: () =>
          [n.name, fmtCompact(n.amount), props.colorBy === "diff" ? `${band.symbol} ${fmtSignedPct(n.pct)}` : ""]
            .filter(Boolean)
            .join("\n"),
      },
    };
  });
  return {
    animationDurationUpdate: 350,
    tooltip: {
      confine: true,
      backgroundColor: css("--surface"),
      borderColor: css("--border"),
      textStyle: { color: css("--text"), fontSize: 13 },
      formatter: (p: { data?: { node?: TreeNode } }) => (p.data?.node ? tooltipHtml(p.data.node) : ""),
    },
    series: [
      {
        type: "treemap",
        data,
        left: 0, right: 0, top: 0, bottom: 0,
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        squareRatio: 1,
        label: { show: true, position: "insideTopLeft", fontSize: 13, lineHeight: 18, overflow: "truncate", padding: 6 },
        itemStyle: { borderColor: surface, borderWidth: 2, gapWidth: 2, borderRadius: 4 },
        emphasis: { itemStyle: { borderColor: css("--focus"), borderWidth: 3 } },
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
    if (n && n.children.length) emit("drill", n);
  });
  // 點空白處回上一層
  chart.value.getZr().on("click", (e: { target?: unknown }) => {
    if (!e.target) emit("up");
  });
  render();
  ro = new ResizeObserver(() => chart.value?.resize());
  ro.observe(el.value);
  mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", render);
});

onBeforeUnmount(() => {
  ro?.disconnect();
  mq?.removeEventListener("change", render);
  chart.value?.dispose();
  chart.value = null;
});

watch(() => [props.nodes, props.colorBy, props.parentTotal], render);
</script>

<template>
  <div
    ref="el"
    class="treemap"
    role="img"
    :aria-label="chartLabel"
    :style="{ height: height + 'px' }"
  ></div>
</template>

<style scoped>
.treemap { width: 100%; min-height: 280px; }
</style>
