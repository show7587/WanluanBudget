import type { CompareData, IndexData, YearData } from "./types";

/** 資料來源介面：圖表與頁面只依賴它，可換成 mock 或其他後端。 */
export interface DataSource {
  index(): Promise<IndexData>;
  year(year: number): Promise<YearData>;
  /** 回傳「本年度為 toYear」的比較資料；沒有則 null（例如最早年度） */
  compareTo(toYear: number): Promise<CompareData | null>;
}

/** 預設：讀取 repo 內由 scripts/build.py 產生的靜態 JSON（base 預設 `data/`，可用 VITE_DATA_BASE 覆寫） */
export function createHttpSource(base = import.meta.env?.VITE_DATA_BASE ?? "data/"): DataSource {
  const cache = new Map<string, Promise<unknown>>();
  const get = <T>(path: string, optional = false): Promise<T | null> => {
    if (!cache.has(path)) {
      cache.set(
        path,
        fetch(`${base}${path}`).then((r) => {
          if (!r.ok) {
            if (optional && r.status === 404) return null;
            throw new Error(`載入 ${path} 失敗（HTTP ${r.status}）`);
          }
          return r.json();
        }),
      );
    }
    return cache.get(path) as Promise<T | null>;
  };
  return {
    index: () => get<IndexData>("index.json") as Promise<IndexData>,
    year: (y) => get<YearData>(`${y}.json`) as Promise<YearData>,
    async compareTo(toYear) {
      const c = await get<CompareData>(`compare_${toYear - 1}_${toYear}.json`, true);
      return c && c.to_year === toYear ? c : null;
    },
  };
}

let current: DataSource | null = null;
export const dataSource = (): DataSource => (current ??= createHttpSource());
export const setDataSource = (s: DataSource): void => {
  current = s;
};
