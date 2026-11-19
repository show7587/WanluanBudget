<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import DrillExplorer from "@/components/DrillExplorer.vue";
import { useBudget } from "@/composables/useBudget";
import { useQueryPath, useQueryString } from "@/composables/useRouteState";
import { normalizeRevenue } from "@/data/normalize";
import type { TreeNode } from "@/data/types";

type ColorMode = "size" | "diff";

const route = useRoute();
const year = computed(() => Number(route.params.year) || 0);
const { loading, error, data, compare } = useBudget(year);

const path = useQueryPath();
const colorBy = useQueryString<ColorMode>("color", "size", ["size", "diff"]);

const roots = computed<TreeNode[]>(() => (data.value ? normalizeRevenue(data.value, compare.value) : []));

const compareNote = computed(() =>
  compare.value ? `較 ${compare.value.from_year} 年度` : "無跨年度比較資料，上年度數字取自預算書",
);

const compareDetail = computed(() =>
  compare.value
    ? `本頁增減係與 ${compare.value.from_year} 年度對照（預算書載有上年度數字者優先採用，其餘取自跨年度比較資料）。`
    : `${year.value} 年度無跨年度比較資料，上年度數字取自預算書（款、項層級有載列，未載列者標示為「無上年度可比資料」）。`,
);

const exportName = computed(() => `${year.value}-revenue`);
</script>

<template>
  <div class="page revenue-page">
    <header class="page-head">
      <div>
        <h1 class="page-title">{{ year }} 年度歲入</h1>
        <p class="muted desc">依來源別階層探索（款 → 項 → 子目 → 細目），點選色塊或表格項目可展開下一層。金額單位：元。</p>
      </div>
      <div class="controls" role="group" aria-label="圖表著色方式">
        <span class="controls-label muted">著色方式：</span>
        <button
          class="btn"
          type="button"
          :aria-pressed="colorBy === 'size'"
          @click="colorBy = 'size'"
        >
          依金額（類別色）
        </button>
        <button
          class="btn"
          type="button"
          :aria-pressed="colorBy === 'diff'"
          @click="colorBy = 'diff'"
        >
          依較上年度增減
        </button>
      </div>
    </header>

    <p v-if="loading" class="card muted" role="status" aria-live="polite">
      載入 {{ year }} 年度歲入資料中…
    </p>

    <div v-else-if="error" class="error-box" role="alert">
      <strong>無法載入 {{ year }} 年度歲入資料：</strong>{{ error }}
    </div>

    <template v-else-if="data">
      <aside class="notice" aria-label="比較資料說明">
        <strong>比較資料說明：</strong>{{ compareDetail }}
      </aside>

      <DrillExplorer
        v-model:path="path"
        :roots="roots"
        root-label="歲入"
        :title="`${year} 年度歲入`"
        :color-by="colorBy"
        :show-diff="true"
        :export-name="exportName"
        :compare-note="compareNote"
      />
    </template>
  </div>
</template>

<style scoped>
.revenue-page > * {
  min-width: 0;
}

.page-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px 16px;
}

.desc {
  margin: 4px 0 0;
  font-size: var(--fs-sm);
}

.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.controls-label {
  font-size: var(--fs-sm);
}

.notice {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  font-size: var(--fs-sm);
  color: var(--text);
}
</style>
