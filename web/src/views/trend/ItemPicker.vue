<script setup lang="ts">
import { computed, ref } from "vue";
import type { SeriesData } from "@/data/types";
import {
  buildPickerTree,
  formatSeriesItemLabel,
  MAX_TREND_ITEMS,
  PICKER_FILTERS,
  searchSeriesItems,
  type PickerFilterKey,
  type PickerTreeNode,
} from "./trendModel";

const props = defineProps<{
  data: SeriesData;
  selectedKeys: string[];
}>();

const emit = defineEmits<{
  (e: "add", key: string): void;
  (e: "remove", key: string): void;
  (e: "set-primary", key: string): void;
  (e: "clear"): void;
}>();

type PickerTab = "search" | "tree";
const tab = ref<PickerTab>("search");
const query = ref("");
const filter = ref<PickerFilterKey>("all");
const treeSection = ref<"revenue" | "expenditure">("revenue");
const showLimit = ref(40);

const selectedSet = computed(() => new Set(props.selectedKeys));
const isFull = computed(() => props.selectedKeys.length >= MAX_TREND_ITEMS);

const selectedEntries = computed(() =>
  props.selectedKeys
    .map((key, idx) => {
      const item = props.data.items[key];
      if (!item) return null;
      return {
        key,
        isPrimary: idx === 0,
        label: formatSeriesItemLabel(key, item, props.data.items),
        level: item.level,
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null),
);

const searchResults = computed(() => searchSeriesItems(props.data, query.value, filter.value));
const visibleResults = computed(() => searchResults.value.slice(0, showLimit.value));
const hasMore = computed(() => searchResults.value.length > visibleResults.value.length);

const treeData = computed(() => buildPickerTree(props.data));
const activeTree = computed<PickerTreeNode[]>(() =>
  treeSection.value === "revenue" ? treeData.value.revenue : treeData.value.expenditure,
);

function toggleKey(key: string): void {
  if (selectedSet.value.has(key)) {
    emit("remove", key);
  } else if (!isFull.value) {
    emit("add", key);
  }
}

function formatYearsBadge(years?: number[]): string {
  if (!years || !years.length) return "";
  if (years.length === 1) return `${years[0]} 年`;
  return years.join("、") + " 年";
}
</script>

<template>
  <section class="card picker" aria-label="挑選比較項目">
    <div class="picker-head">
      <div>
        <h2 class="picker-title">已選項目（{{ selectedKeys.length }} / {{ MAX_TREND_ITEMS }}）</h2>
        <p class="muted picker-sub">
          第一個為「主項目」，可任意跨歲入、歲出與不同層級加入最多 {{ MAX_TREND_ITEMS }} 個項目獨立比較。
        </p>
      </div>
      <button v-if="selectedKeys.length" class="btn" type="button" @click="emit('clear')">
        清空已選
      </button>
    </div>

    <div v-if="selectedEntries.length" class="chip-list" role="list" aria-label="已選項目清單">
      <div
        v-for="s in selectedEntries"
        :key="s.key"
        class="chip"
        :class="{ primary: s.isPrimary }"
        role="listitem"
      >
        <span class="chip-role">{{ s.isPrimary ? "★ 主項目" : s.level }}</span>
        <span class="chip-name">{{ s.label }}</span>
        <div class="chip-actions">
          <button
            v-if="!s.isPrimary"
            class="chip-btn"
            type="button"
            :title="`將「${s.label}」設為主項目`"
            @click="emit('set-primary', s.key)"
          >
            設為主項
          </button>
          <button
            class="chip-btn remove"
            type="button"
            :aria-label="`移除 ${s.label}`"
            @click="emit('remove', s.key)"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
    <p v-else class="muted empty-selected">
      尚未選擇項目，請從下方搜尋或依階層挑選至少 1 個預算項目。
    </p>

    <p v-if="isFull" class="limit-note" role="status">
      已達上限 {{ MAX_TREND_ITEMS }} 項，請先移除既有項目再新增。
    </p>

    <div class="picker-tabs" role="tablist" aria-label="挑選方式">
      <button
        type="button"
        role="tab"
        class="btn"
        :aria-selected="tab === 'search'"
        :aria-pressed="tab === 'search'"
        @click="tab = 'search'"
      >
        搜尋／篩選項目
      </button>
      <button
        type="button"
        role="tab"
        class="btn"
        :aria-selected="tab === 'tree'"
        :aria-pressed="tab === 'tree'"
        @click="tab = 'tree'"
      >
        依階層挑選
      </button>
    </div>

    <div v-if="tab === 'search'" class="search-panel">
      <div class="search-row">
        <label class="sr-only" for="trend-picker-search">搜尋預算項目</label>
        <input
          id="trend-picker-search"
          v-model="query"
          class="search-input"
          type="search"
          autocomplete="off"
          placeholder="輸入名稱、代碼、機關或政事別（空白分隔多詞）"
          @input="showLimit = 40"
        />
        <button v-if="query" class="btn" type="button" @click="query = ''">清除</button>
      </div>

      <div class="filter-bar" role="group" aria-label="依層級篩選">
        <button
          v-for="f in PICKER_FILTERS"
          :key="f.key"
          type="button"
          class="btn filter-btn"
          :aria-pressed="filter === f.key"
          @click="filter = f.key; showLimit = 40"
        >
          {{ f.label }}
        </button>
      </div>

      <p class="muted result-count">共 {{ searchResults.length }} 個可選項目</p>

      <ul v-if="visibleResults.length" class="option-list" aria-label="搜尋結果清單">
        <li v-for="opt in visibleResults" :key="opt.key" class="option-row">
          <div class="option-info">
            <div class="option-title">
              <span class="level-tag">{{ opt.item.level }}</span>
              <span class="option-name">{{ opt.label }}</span>
              <span v-if="opt.item.name_changed" class="meta-tag warn">曾改名</span>
            </div>
            <div class="option-meta muted">
              <span>代碼 {{ opt.item.code }}</span>
              <span v-if="opt.category">{{ opt.category }}</span>
              <span v-if="opt.dept">{{ opt.dept }}</span>
              <span>有資料：{{ formatYearsBadge(opt.activeYears) }}</span>
            </div>
          </div>
          <button
            type="button"
            class="btn pick-btn"
            :class="{ primary: selectedSet.has(opt.key) }"
            :disabled="!selectedSet.has(opt.key) && isFull"
            @click="toggleKey(opt.key)"
          >
            {{ selectedSet.has(opt.key) ? "已選 ✓" : "+ 加入" }}
          </button>
        </li>
      </ul>
      <p v-else class="muted empty-selected">找不到符合條件的項目，請放寬關鍵字或層級篩選。</p>

      <div v-if="hasMore" class="more-row">
        <button type="button" class="btn" @click="showLimit += 60">
          顯示更多（尚有 {{ searchResults.length - visibleResults.length }} 項）
        </button>
      </div>
    </div>

    <div v-else class="tree-panel">
      <div class="filter-bar" role="group" aria-label="選擇歲入或歲出階層">
        <button
          type="button"
          class="btn"
          :aria-pressed="treeSection === 'revenue'"
          @click="treeSection = 'revenue'"
        >
          歲入階層（款 → 項 → 子目 → 細目）
        </button>
        <button
          type="button"
          class="btn"
          :aria-pressed="treeSection === 'expenditure'"
          @click="treeSection = 'expenditure'"
        >
          歲出階層（政事別 → 工作計畫 → 用途別）
        </button>
      </div>

      <div class="tree-list">
        <details v-for="(n1, i1) in activeTree" :key="n1.key ?? `g1-${i1}`" class="tree-node level-1">
          <summary class="tree-summary">
            <span class="tree-label">
              <span class="level-tag">{{ n1.level }}</span>
              <span>{{ n1.label }}</span>
              <span v-if="n1.activeYears" class="muted tree-years">（{{ formatYearsBadge(n1.activeYears) }}）</span>
            </span>
            <button
              v-if="n1.key"
              type="button"
              class="btn pick-btn"
              :class="{ primary: selectedSet.has(n1.key) }"
              :disabled="!selectedSet.has(n1.key) && isFull"
              @click.prevent.stop="toggleKey(n1.key)"
            >
              {{ selectedSet.has(n1.key) ? "已選 ✓" : "+ 加入" }}
            </button>
          </summary>

          <div v-if="n1.children.length" class="tree-children">
            <template v-for="(n2, i2) in n1.children" :key="n2.key ?? `g2-${i2}`">
              <details v-if="n2.children.length" class="tree-node level-2">
                <summary class="tree-summary">
                  <span class="tree-label">
                    <span class="level-tag">{{ n2.level }}</span>
                    <span>{{ n2.label }}</span>
                    <span v-if="n2.activeYears" class="muted tree-years">（{{ formatYearsBadge(n2.activeYears) }}）</span>
                  </span>
                  <button
                    v-if="n2.key"
                    type="button"
                    class="btn pick-btn"
                    :class="{ primary: selectedSet.has(n2.key) }"
                    :disabled="!selectedSet.has(n2.key) && isFull"
                    @click.prevent.stop="toggleKey(n2.key)"
                  >
                    {{ selectedSet.has(n2.key) ? "已選 ✓" : "+ 加入" }}
                  </button>
                </summary>

                <div class="tree-children">
                  <template v-for="(n3, i3) in n2.children" :key="n3.key ?? `g3-${i3}`">
                    <details v-if="n3.children.length" class="tree-node level-3">
                      <summary class="tree-summary">
                        <span class="tree-label">
                          <span class="level-tag">{{ n3.level }}</span>
                          <span>{{ n3.label }}</span>
                          <span v-if="n3.activeYears" class="muted tree-years">（{{ formatYearsBadge(n3.activeYears) }}）</span>
                        </span>
                        <button
                          v-if="n3.key"
                          type="button"
                          class="btn pick-btn"
                          :class="{ primary: selectedSet.has(n3.key) }"
                          :disabled="!selectedSet.has(n3.key) && isFull"
                          @click.prevent.stop="toggleKey(n3.key)"
                        >
                          {{ selectedSet.has(n3.key) ? "已選 ✓" : "+ 加入" }}
                        </button>
                      </summary>

                      <div class="tree-children">
                        <div v-for="n4 in n3.children" :key="n4.key ?? n4.label" class="tree-leaf">
                          <span class="tree-label">
                            <span class="level-tag">{{ n4.level }}</span>
                            <span>{{ n4.label }}</span>
                            <span v-if="n4.activeYears" class="muted tree-years">（{{ formatYearsBadge(n4.activeYears) }}）</span>
                          </span>
                          <button
                            v-if="n4.key"
                            type="button"
                            class="btn pick-btn"
                            :class="{ primary: selectedSet.has(n4.key) }"
                            :disabled="!selectedSet.has(n4.key) && isFull"
                            @click="toggleKey(n4.key)"
                          >
                            {{ selectedSet.has(n4.key) ? "已選 ✓" : "+ 加入" }}
                          </button>
                        </div>
                      </div>
                    </details>

                    <div v-else class="tree-leaf">
                      <span class="tree-label">
                        <span class="level-tag">{{ n3.level }}</span>
                        <span>{{ n3.label }}</span>
                        <span v-if="n3.activeYears" class="muted tree-years">（{{ formatYearsBadge(n3.activeYears) }}）</span>
                      </span>
                      <button
                        v-if="n3.key"
                        type="button"
                        class="btn pick-btn"
                        :class="{ primary: selectedSet.has(n3.key) }"
                        :disabled="!selectedSet.has(n3.key) && isFull"
                        @click="toggleKey(n3.key)"
                      >
                        {{ selectedSet.has(n3.key) ? "已選 ✓" : "+ 加入" }}
                      </button>
                    </div>
                  </template>
                </div>
              </details>

              <div v-else class="tree-leaf">
                <span class="tree-label">
                  <span class="level-tag">{{ n2.level }}</span>
                  <span>{{ n2.label }}</span>
                  <span v-if="n2.activeYears" class="muted tree-years">（{{ formatYearsBadge(n2.activeYears) }}）</span>
                </span>
                <button
                  v-if="n2.key"
                  type="button"
                  class="btn pick-btn"
                  :class="{ primary: selectedSet.has(n2.key) }"
                  :disabled="!selectedSet.has(n2.key) && isFull"
                  @click="toggleKey(n2.key)"
                >
                  {{ selectedSet.has(n2.key) ? "已選 ✓" : "+ 加入" }}
                </button>
              </div>
            </template>
          </div>
        </details>
      </div>
    </div>
  </section>
</template>

<style scoped>
.picker {
  display: grid;
  gap: 12px;
  min-width: 0;
}
.picker-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px 12px;
}
.picker-title {
  font-size: var(--fs-lg);
}
.picker-sub {
  margin: 2px 0 0;
  font-size: var(--fs-sm);
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-2);
  font-size: var(--fs-sm);
  max-width: 100%;
}
.chip.primary {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface));
}
.chip-role {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--accent);
  white-space: nowrap;
}
.chip-name {
  overflow-wrap: anywhere;
  font-weight: 600;
}
.chip-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.chip-btn {
  appearance: none;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  border-radius: 999px;
  padding: 2px 8px;
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}
.chip-btn:hover {
  background: var(--surface-2);
}
.chip-btn.remove {
  padding: 2px 6px;
}

.empty-selected {
  margin: 0;
  font-size: var(--fs-sm);
}
.limit-note {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  border-left: 4px solid var(--cat-2);
  background: var(--surface-2);
  font-size: var(--fs-sm);
}

.picker-tabs,
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.filter-btn {
  font-size: var(--fs-xs);
  padding: 4px 10px;
  min-height: 32px;
}

.search-panel,
.tree-panel {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.search-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.search-input {
  flex: 1 1 200px;
  min-width: 0;
  min-height: 38px;
  padding: 6px 12px;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.result-count {
  margin: 0;
  font-size: var(--fs-xs);
}

.option-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px;
}
.option-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid var(--border);
}
.option-row:last-child {
  border-bottom: 0;
}
.option-info {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}
.option-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
}
.option-name {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.option-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: var(--fs-xs);
  overflow-wrap: anywhere;
}

.level-tag,
.meta-tag {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  font-size: var(--fs-xs);
  white-space: nowrap;
}
.meta-tag.warn {
  border-color: var(--cat-2);
}

.pick-btn {
  flex-shrink: 0;
  padding: 4px 10px;
  min-height: 32px;
  font-size: var(--fs-xs);
}
.more-row {
  display: flex;
  justify-content: center;
}

.tree-list {
  display: grid;
  gap: 6px;
  max-height: 380px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px;
}
.tree-node {
  border-left: 2px solid var(--border);
  padding-left: 8px;
}
.tree-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  cursor: pointer;
  list-style: none;
}
.tree-summary::-webkit-details-marker {
  display: none;
}
.tree-summary::before {
  content: "▸";
  font-size: var(--fs-xs);
  color: var(--text-muted);
  margin-right: 4px;
  flex-shrink: 0;
}
details[open] > .tree-summary::before {
  content: "▾";
}
.tree-label {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}
.tree-years {
  font-size: var(--fs-xs);
}
.tree-children {
  display: grid;
  gap: 4px;
  padding-left: 10px;
  margin-top: 4px;
}
.tree-leaf {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 5px 4px;
  border-bottom: 1px dashed var(--border);
}
.tree-leaf:last-child {
  border-bottom: 0;
}
</style>
