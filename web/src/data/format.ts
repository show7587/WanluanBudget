const nf = new Intl.NumberFormat("zh-Hant-TW");

/** 千分位整數 */
export const fmtInt = (n: number): string => nf.format(Math.round(n));

/** 金額（元）加千分位，例：312,678,000 元 */
export const fmtYuan = (n: number): string => `${fmtInt(n)} 元`;

/** 簡短金額：≥1 億用「億元」，≥1 萬用「萬元」，皆含千分位與最多 2 位小數 */
export function fmtCompact(n: number): string {
  const a = Math.abs(n);
  const fmt = (v: number, unit: string) =>
    `${new Intl.NumberFormat("zh-Hant-TW", { maximumFractionDigits: 2 }).format(v)} ${unit}`;
  if (a >= 1e8) return fmt(n / 1e8, "億元");
  if (a >= 1e4) return fmt(n / 1e4, "萬元");
  return fmt(n, "元");
}

/** 百分比固定 2 位小數；null → 「—」 */
export const fmtPct = (p: number | null | undefined): string =>
  p == null || Number.isNaN(p) ? "—" : `${p.toFixed(2)}%`;

/** 帶正負號的百分比，例：+9.27% / -3.10% */
export const fmtSignedPct = (p: number | null | undefined): string =>
  p == null || Number.isNaN(p) ? "—" : `${p > 0 ? "+" : ""}${p.toFixed(2)}%`;

/** 帶正負號的金額差 */
export const fmtSignedYuan = (n: number | null | undefined): string =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${fmtInt(n)} 元`;
