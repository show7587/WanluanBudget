<script setup lang="ts">
import { DIFF_BANDS } from "@/data/diffScale";
withDefaults(defineProps<{ keys?: string[] }>(), { keys: () => [] });
</script>

<template>
  <ul class="legend" aria-label="色階說明">
    <li v-for="b in DIFF_BANDS.filter((x) => !keys.length || keys.includes(x.key))" :key="b.key">
      <span class="chip" :style="{ background: `var(${b.cssVar})` }" aria-hidden="true"></span>
      <span class="sym" aria-hidden="true">{{ b.symbol }}</span>
      {{ b.label }}
    </li>
  </ul>
</template>

<style scoped>
.legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: var(--fs-xs); }
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.chip { width: 16px; height: 16px; border-radius: 4px; border: 1px solid var(--border); }
.sym { color: var(--text-muted); }
</style>
