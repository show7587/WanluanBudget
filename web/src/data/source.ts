import type { CompareData, IndexData, SeriesData, YearData } from "./types";

/** 資料來源介面：圖表與頁面只依賴它，可換成 mock 或其他後端。 */
export interface DataSource {
  index(): Promise<IndexData>;
  year(year: number): Promise<YearData>;
  /** 回傳「本年度為 toYear」的比較資料；沒有則 null（例如最早年度） */
  compareTo(toYear: number): Promise<CompareData | null>;
  /** 回傳跨年度時間序列資料；載入失敗快取 null、優雅降級 */
  series(): Promise<SeriesData | null>;
}

/** 預設：讀取 repo 內由 scripts/build.py 產生的靜態 JSON（base 預設 `data/`，可用 VITE_DATA_BASE 覆寫） */
export function createHttpSource(base = import.meta.env?.VITE_DATA_BASE ?? "data/"): DataSource {
  const cache = new Map<string, Promise<unknown>>();
  const get = <T>(path: string, optional = false): Promise<T | null> => {
    if (!cache.has(path)) {
      cache.set(
        path,
        fetch(`${base}${path}`).then(async (r) => {
          if (!r.ok) {
            if (optional && r.status === 404) return null;
            throw new Error(`載入 ${path} 失敗（HTTP ${r.status}）`);
          }
          try {
            return await r.json();
          } catch {
            // 某些伺服器（含 vite dev）對不存在的檔案回傳 index.html（HTTP 200）；選用資料視為不存在
            if (optional) return null;
            throw new Error(`載入 ${path} 失敗（內容不是 JSON）`);
          }
        }),
      );
    }
    return cache.get(path) as Promise<T | null>;
  };
  return {
    index: () => get<IndexData>("index.json") as Promise<IndexData>,
    year: (y) => get<YearData>(`${y}.json`) as Promise<YearData>,
    async compareTo(toYear) {
      // 先看 index：沒有上一年度就不必請求比較檔
      const idx = (await get<IndexData>("index.json")) as IndexData;
      if (!idx.years.includes(toYear - 1)) return null;
      const c = await get<CompareData>(`compare_${toYear - 1}_${toYear}.json`, true);
      return c && c.to_year === toYear ? c : null;
    },
    series() {
      const path = "series.json";
      if (!cache.has(path)) {
        cache.set(
          path,
          fetch(`${base}${path}`)
            .then(async (r) => {
              if (!r.ok) return null;
              const d = (await r.json()) as unknown;
              if (
                !d ||
                typeof d !== "object" ||
                !Array.isArray((d as SeriesData).years) ||
                !(d as SeriesData).items ||
                typeof (d as SeriesData).items !== "object"
              ) {
                return null;
              }
              return d as SeriesData;
            })
            .catch(() => null),
        );
      }
      return cache.get(path) as Promise<SeriesData | null>;
    },
  };
}

let current: DataSource | null = null;
export const dataSource = (): DataSource => (current ??= createHttpSource());
export const setDataSource = (s: DataSource): void => {
  current = s;
};
