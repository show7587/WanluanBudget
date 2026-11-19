<script setup lang="ts">
defineProps<{ label: string; value: string; sub?: string; tone?: "neutral" | "good" | "bad" }>();
</script>

<template>
  <div class="card kpi" :data-tone="tone ?? 'neutral'">
    <div class="label muted">{{ label }}</div>
    <div class="value num">{{ value }}</div>
    <div v-if="sub" class="sub muted">{{ sub }}</div>
  </div>
</template>

<style scoped>
.kpi { display: grid; gap: 4px; border-top: 4px solid var(--border); }
.kpi[data-tone="good"] { border-top-color: var(--diff-up-4); }
.kpi[data-tone="bad"] { border-top-color: var(--diff-down-4); }
.label { font-size: var(--fs-sm); }
.value { font-size: var(--fs-xl); font-weight: 700; text-align: left; }
.sub { font-size: var(--fs-sm); }
</style>
