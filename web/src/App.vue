<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { dataSource } from "@/data/source";
import type { IndexData } from "@/data/types";

const DISCLAIMER = "以萬巒鄉公所公布之預算書為準，僅供快速比對與查閱，請勿引用於其他地方。本站資料可能有誤差。";

const route = useRoute();
const router = useRouter();
const index = ref<IndexData | null>(null);
const year = computed(() => Number(route.params.year) || index.value?.default_year || 0);

onMounted(async () => {
  try {
    index.value = await dataSource().index();
  } catch {
    /* 各頁自行顯示載入失敗 */
  }
});

const nav = computed(() => {
  const items = [
    { to: "總覽", label: "總覽" },
    { to: "歲出", label: "歲出" },
    { to: "歲入", label: "歲入" },
    { to: "比較", label: "比較" },
  ];
  // 趨勢頁在 series_years 至少 2 個年度時顯示
  if ((index.value?.series_years?.length ?? 0) >= 2) items.push({ to: "趨勢", label: "趨勢" });
  items.push({ to: "搜尋", label: "搜尋" });
  // 參考表只有部分年度有；備註只在 index.memo_years 含該年度時顯示
  if (index.value?.reference_years.includes(year.value)) items.push({ to: "參考表", label: "參考表" });
  if (index.value?.memo_years.includes(year.value)) items.push({ to: "備註", label: "資料備註" });
  return items;
});

function changeYear(e: Event): void {
  const y = (e.target as HTMLSelectElement).value;
  // 換年度時保留頁面，清掉 drill-down 路徑（節點 id 不一定跨年度存在）
  void router.push({ path: `/${y}/${String(route.path.split("/")[2] ?? "總覽")}`, query: { ...route.query, path: undefined, filter: undefined } });
}

</script>

<template>
  <a class="skip" href="#main">跳到主要內容</a>
  <div class="notice" role="note">{{ DISCLAIMER }}</div>
  <header class="top">
    <router-link class="brand" to="/">萬巒鄉預算查詢</router-link>
    <nav class="nav" aria-label="主要導覽">
      <router-link v-for="n in nav" :key="n.to" :to="{ path: `/${year}/${n.to}` }" class="nav-link" active-class="active">
        {{ n.label }}
      </router-link>
    </nav>
    <div class="tools">
      <label class="year">
        <span class="sr-only">年度</span>
        <select :value="year" @change="changeYear" aria-label="年度">
          <option v-for="y in index?.years ?? [year]" :key="y" :value="y">{{ y }} 年度</option>
        </select>
      </label>
    </div>
  </header>
  <main id="main" tabindex="-1">
    <router-view :key="`${$route.path}`" />
  </main>
  <footer class="foot muted">
    <p>資料來源：萬巒鄉預算書（OCR 轉檔後人工校正，每筆修正見 data/corrections.csv）。金額單位：元。</p>
    <p class="disclaimer">{{ DISCLAIMER }}</p>
  </footer>
</template>

<style scoped>
.skip { position: absolute; left: -999px; top: 0; background: var(--accent); color: var(--accent-contrast); padding: 8px 12px; z-index: 10; }
.skip:focus { left: 8px; top: 8px; }
.top {
  position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 20px;
  padding: 10px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
}
.brand { font-weight: 700; font-size: var(--fs-lg); color: var(--text); text-decoration: none; }
.nav { display: flex; gap: 4px; flex-wrap: wrap; }
.nav-link { padding: 6px 14px; border-radius: 999px; color: var(--text); text-decoration: none; min-height: 36px; display: inline-flex; align-items: center; }
.nav-link:hover { background: var(--surface-2); }
.nav-link.active { background: var(--accent); color: var(--accent-contrast); }
.tools { margin-left: auto; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
select { font: inherit; padding: 6px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface); color: var(--text); min-height: 36px; }
.notice { padding: 6px 16px; background: var(--surface-2); border-bottom: 1px solid var(--border); color: var(--text); font-size: var(--fs-sm); text-align: center; }
.foot { max-width: 1200px; margin: 0 auto; padding: 24px 16px; font-size: var(--fs-sm); }
.foot p { margin: 0 0 6px; }
.foot .disclaimer { font-weight: 700; }
@media (max-width: 640px) { .tools { margin-left: 0; width: 100%; } }
</style>
