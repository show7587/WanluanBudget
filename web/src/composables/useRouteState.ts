import { computed, type WritableComputedRef } from "vue";
import { useRoute, useRouter } from "vue-router";
import { decodePath, encodePath, firstQuery } from "@/utils/query";

/** 把某個 query 參數當成 drill-down 路徑（id 陣列）讀寫；寫入用 push，讓瀏覽器上一頁可回上一層 */
export function useQueryPath(key = "path"): WritableComputedRef<string[]> {
  const route = useRoute();
  const router = useRouter();
  return computed({
    get: () => decodePath(route.query[key]),
    set: (ids) => {
      const query = { ...route.query };
      const enc = encodePath(ids);
      if (enc) query[key] = enc;
      else delete query[key];
      void router.push({ query });
    },
  });
}

/** 讀寫字串型 query 參數（例如 view）；切換時以 replace 取代，並清掉 path */
export function useQueryString<T extends string>(
  key: string,
  fallback: T,
  allowed: readonly T[],
  resetKeys: string[] = [],
): WritableComputedRef<T> {
  const route = useRoute();
  const router = useRouter();
  return computed({
    get: () => {
      const v = firstQuery(route.query[key]) as T | undefined;
      return v && allowed.includes(v) ? v : fallback;
    },
    set: (v) => {
      const query = { ...route.query, [key]: v };
      resetKeys.forEach((k) => delete query[k]);
      void router.replace({ query });
    },
  });
}
