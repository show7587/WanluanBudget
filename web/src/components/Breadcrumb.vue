<script setup lang="ts">
export interface Crumb {
  label: string;
  /** 最後一個（目前位置）不給 */
  onSelect?: () => void;
}
defineProps<{ items: Crumb[]; label?: string }>();
</script>

<template>
  <nav :aria-label="label ?? '目前位置'" class="crumbs">
    <ol>
      <li v-for="(c, i) in items" :key="i">
        <button v-if="c.onSelect && i < items.length - 1" type="button" class="crumb" @click="c.onSelect">{{ c.label }}</button>
        <span v-else class="here" aria-current="page">{{ c.label }}</span>
        <span v-if="i < items.length - 1" class="sep" aria-hidden="true">›</span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
ol { list-style: none; display: flex; flex-wrap: wrap; gap: 6px; padding: 0; margin: 0; align-items: center; }
.crumb {
  appearance: none; border: 0; background: none; padding: 2px 4px; font: inherit;
  color: var(--accent); cursor: pointer; text-decoration: underline;
}
.here { font-weight: 600; }
.sep { color: var(--text-muted); margin-left: 6px; }
</style>
