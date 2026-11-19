import { ref, watch, type Ref } from "vue";
import { dataSource } from "@/data/source";
import type { CompareData, IndexData, YearData } from "@/data/types";

export interface BudgetState {
  loading: Ref<boolean>;
  error: Ref<string | null>;
  index: Ref<IndexData | null>;
  data: Ref<YearData | null>;
  /** 「本年度＝所選年度」的比較資料；最早年度為 null */
  compare: Ref<CompareData | null>;
}

/** 依年度載入 index／年度資料／比較資料；年度改變時重新載入，並忽略過時的回應 */
export function useBudget(year: Ref<number>): BudgetState {
  const loading = ref(true);
  const error = ref<string | null>(null);
  const index = ref<IndexData | null>(null);
  const data = ref<YearData | null>(null);
  const compare = ref<CompareData | null>(null);
  let seq = 0;

  watch(
    year,
    async (y) => {
      const mine = ++seq;
      loading.value = true;
      error.value = null;
      try {
        const src = dataSource();
        const [idx, d, c] = await Promise.all([src.index(), src.year(y), src.compareTo(y)]);
        if (mine !== seq) return;
        index.value = idx;
        data.value = d;
        compare.value = c;
      } catch (e) {
        if (mine !== seq) return;
        error.value = e instanceof Error ? e.message : String(e);
        data.value = null;
        compare.value = null;
      } finally {
        if (mine === seq) loading.value = false;
      }
    },
    { immediate: true },
  );

  return { loading, error, index, data, compare };
}
