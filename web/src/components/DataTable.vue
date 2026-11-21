<script setup lang="ts">
import { computed } from "vue";
import type { RouteLocationRaw } from "vue-router";
import type { TreeNode } from "@/data/types";
import { diffBand } from "@/data/diffScale";
import { fmtInt, fmtPct, fmtSignedPct, fmtSignedYuan } from "@/data/format";

const props = defineProps<{
  nodes: TreeNode[];
  caption: string;
  /** 上一層總額；缺省用 nodes 加總 */
  parentTotal?: number;
  showDiff?: boolean;
  /** 若提供且節點有對應趨勢頁連結，於表格顯示「看趨勢」入口 */
  trendLinkFor?: (node: TreeNode) => RouteLocationRaw | null;
}>();
const emit = defineEmits<{ (e: "drill", node: TreeNode): void }>();

const total = computed(() => props.parentTotal ?? props.nodes.reduce((s, n) => s + n.amount, 0));
const share = (n: TreeNode): string => fmtPct(total.value ? (n.amount / total.value) * 100 : 0);
const hasTrendCol = computed(() => Boolean(props.trendLinkFor && props.nodes.some((n) => props.trendLinkFor!(n) != null)));
</script>

<template>
  <div class="table-wrap" tabindex="0" role="region" :aria-label="`${caption}（可捲動資料表）`">
    <table class="data">
      <caption>{{ caption }}（金額單位：元）</caption>
      <thead>
        <tr>
          <th scope="col">項目</th>
          <th scope="col" class="num">本年度</th>
          <th scope="col" class="num">占本層</th>
          <template v-if="showDiff">
            <th scope="col" class="num">上年度</th>
            <th scope="col" class="num">增減</th>
            <th scope="col" class="num">增減 %</th>
            <th scope="col">狀態</th>
          </template>
          <th v-if="hasTrendCol" scope="col">趨勢</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="n in nodes" :key="n.id">
          <th scope="row">
            <button v-if="n.children.length" class="link" type="button" @click="emit('drill', n)">
              {{ n.name }}<span class="sr-only">，展開下一層</span><span aria-hidden="true"> ›</span>
            </button>
            <template v-else>{{ n.name }}</template>
          </th>
          <td class="num">{{ fmtInt(n.amount) }}</td>
          <td class="num">{{ share(n) }}</td>
          <template v-if="showDiff">
            <td class="num">{{ n.prev == null ? "—" : fmtInt(n.prev) }}</td>
            <td class="num">{{ fmtSignedYuan(n.diff) }}</td>
            <td class="num">{{ fmtSignedPct(n.pct) }}</td>
            <td>
              <span class="badge" :style="{ '--c': `var(${diffBand(n.status, n.pct).cssVar})` }">
                <span aria-hidden="true">{{ diffBand(n.status, n.pct).symbol }}</span>
                {{ diffBand(n.status, n.pct).label }}
              </span>
            </td>
          </template>
          <td v-if="hasTrendCol">
            <router-link v-if="trendLinkFor && trendLinkFor(n)" class="trend-link" :to="trendLinkFor(n)!">
              看趨勢
            </router-link>
            <span v-else class="muted">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.link {
  appearance: none; background: none; border: 0; padding: 0; font: inherit;
  color: var(--accent); cursor: pointer; text-align: left; text-decoration: underline;
}
.badge {
  display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px;
  border-radius: 999px; border: 1px solid var(--border); font-size: var(--fs-xs);
  border-left: 10px solid var(--c); white-space: nowrap;
}
.trend-link {
  white-space: nowrap; font-size: var(--fs-xs); text-decoration: underline;
}
</style>
