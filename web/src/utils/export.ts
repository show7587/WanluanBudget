import type { FlatRow } from "@/data/normalize";

const csvCell = (v: unknown): string => {
  const s = v == null ? "" : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export function rowsToCsv(rows: FlatRow[]): string {
  const head = ["層級", "路徑", "名稱", "本年度(元)", "上年度(元)", "增減(元)", "增減%"];
  const lines = rows.map((r) =>
    [r.level, r.path.join(" > "), r.name, r.amount, r.prev ?? "", r.diff ?? "", r.pct ?? ""].map(csvCell).join(","),
  );
  // BOM 讓 Excel 以 UTF-8 開啟
  return "﻿" + [head.map(csvCell).join(","), ...lines].join("\r\n");
}

export function rowsToJson(rows: FlatRow[]): string {
  return JSON.stringify(
    rows.map((r) => ({
      level: r.level,
      path: r.path,
      name: r.name,
      amount_yuan: r.amount,
      prev_yuan: r.prev,
      diff_yuan: r.diff,
      pct: r.pct,
    })),
    null,
    2,
  );
}

export function download(filename: string, text: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
