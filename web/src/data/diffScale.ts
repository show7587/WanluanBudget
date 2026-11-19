import type { DiffStatus } from "./types";

export interface DiffBand {
  key: string;
  label: string;
  /** 顏色以外的資訊載體：符號 */
  symbol: string;
  /** CSS 變數名（定義於 tokens.css） */
  cssVar: string;
}

/** 增減 % 發散色階：新增＝藍；增加＝綠（5 級）；0＝中性；減少＝紅（5 級，對稱） */
export const DIFF_BANDS: DiffBand[] = [
  { key: "new", label: "新增項目", symbol: "★", cssVar: "--diff-new" },
  { key: "up5", label: "增加 25% 以上", symbol: "▲▲▲", cssVar: "--diff-up-5" },
  { key: "up4", label: "增加 20–25%", symbol: "▲▲", cssVar: "--diff-up-4" },
  { key: "up3", label: "增加 15–20%", symbol: "▲▲", cssVar: "--diff-up-3" },
  { key: "up2", label: "增加 10–15%", symbol: "▲", cssVar: "--diff-up-2" },
  { key: "up1", label: "增加 5–10%", symbol: "▲", cssVar: "--diff-up-1" },
  { key: "up0", label: "增加 0–5%", symbol: "▲", cssVar: "--diff-up-0" },
  { key: "flat", label: "持平（0%）", symbol: "＝", cssVar: "--diff-flat" },
  { key: "down0", label: "減少 0–5%", symbol: "▼", cssVar: "--diff-down-0" },
  { key: "down1", label: "減少 5–10%", symbol: "▼", cssVar: "--diff-down-1" },
  { key: "down2", label: "減少 10–15%", symbol: "▼", cssVar: "--diff-down-2" },
  { key: "down3", label: "減少 15–20%", symbol: "▼▼", cssVar: "--diff-down-3" },
  { key: "down4", label: "減少 20–25%", symbol: "▼▼", cssVar: "--diff-down-4" },
  { key: "down5", label: "減少 25% 以上", symbol: "▼▼▼", cssVar: "--diff-down-5" },
  { key: "unknown", label: "無上年度可比資料", symbol: "？", cssVar: "--diff-unknown" },
  { key: "removed", label: "本年度無預算", symbol: "✕", cssVar: "--diff-removed" },
];

const byKey = new Map(DIFF_BANDS.map((b) => [b.key, b]));
export const bandByKey = (key: string): DiffBand => byKey.get(key) ?? byKey.get("unknown")!;

/** 依狀態與百分比挑色階（邊界歸入較大級距：5 → up1） */
export function diffBandKey(status: DiffStatus, pct: number | null): string {
  if (status === "new") return "new";
  if (status === "removed") return "removed";
  if (status === "unknown" || pct == null) return "unknown";
  if (pct === 0 || status === "flat") return "flat";
  const a = Math.abs(pct);
  const lvl = a >= 25 ? 5 : a >= 20 ? 4 : a >= 15 ? 3 : a >= 10 ? 2 : a >= 5 ? 1 : 0;
  return `${pct > 0 ? "up" : "down"}${lvl}`;
}

export const diffBand = (status: DiffStatus, pct: number | null): DiffBand =>
  bandByKey(diffBandKey(status, pct));
