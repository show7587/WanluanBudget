import { fmtInt } from "@/data/format";

export interface ReferenceCell {
  r: number;
  c: number;
  rs?: number;
  cs?: number;
  t?: string | null;
  v?: number | null;
}

export interface ReferenceTable {
  page: number;
  table_seq: number;
  source_table: string;
  unit?: string | null;
  note?: string | null;
  notes?: string | string[] | null;
  rows: number;
  cols: number;
  cells: ReferenceCell[];
}

export interface ReferenceData {
  year: number;
  note?: string | null;
  notes?: string | string[] | null;
  tables: ReferenceTable[];
}

export interface TocGroup {
  name: string;
  pages: number[];
  range: string;
}

export interface RenderedCell {
  key: string;
  rowspan?: number;
  colspan?: number;
  text: string;
  isNumeric: boolean;
  scope?: "col" | "colgroup";
}

export interface RenderedTableGrid {
  headerRows: RenderedCell[][];
  bodyRows: RenderedCell[][];
}

const cache = new Map<number, Promise<ReferenceData>>();

/** 載入指定年度的參考表 JSON（預設 data/reference_<年>.json，可用 VITE_DATA_BASE 覆寫） */
export function fetchReferenceData(year: number): Promise<ReferenceData> {
  if (!cache.has(year)) {
    const base = import.meta.env?.VITE_DATA_BASE ?? "data/";
    const file = `reference_${year}.json`;
    const req = fetch(`${base}${file}`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`載入 ${file} 失敗（HTTP ${res.status}）`);
        }
        try {
          const parsed = (await res.json()) as ReferenceData;
          if (!parsed || !Array.isArray(parsed.tables)) {
            throw new Error(`載入 ${file} 失敗（資料格式不正確）`);
          }
          return parsed;
        } catch (err) {
          if (err instanceof Error && err.message.startsWith("載入 ")) throw err;
          throw new Error(`載入 ${file} 失敗（內容不是 JSON）`);
        }
      })
      .catch((err) => {
        // 失敗時不快取，讓使用者重新整理或切換年度後可重試
        cache.delete(year);
        throw err;
      });
    cache.set(year, req);
  }
  return cache.get(year)!;
}

/** 依頁碼與 table_seq 排序參考表 */
export function sortReferenceTables(tables: readonly ReferenceTable[]): ReferenceTable[] {
  return [...tables].sort((a, b) => a.page - b.page || a.table_seq - b.table_seq);
}

/** 取得所有不重複的頁碼清單（升冪） */
export function collectReferencePages(tables: readonly ReferenceTable[]): number[] {
  const seen = new Set<number>();
  for (const t of tables) seen.add(t.page);
  return [...seen].sort((a, b) => a - b);
}

/** 取得指定頁碼的所有表格（依 table_seq 升冪） */
export function tablesForPage(tables: readonly ReferenceTable[], page: number): ReferenceTable[] {
  return tables
    .filter((t) => t.page === page)
    .sort((a, b) => a.table_seq - b.table_seq);
}

/** 建立目次分組：相鄰同名 source_table 合併為一組並去重頁碼 */
export function buildTocGroups(tables: readonly ReferenceTable[]): TocGroup[] {
  const sorted = sortReferenceTables(tables);
  const raw: Array<{ name: string; pages: number[] }> = [];
  for (const tb of sorted) {
    const last = raw[raw.length - 1];
    if (last && last.name === tb.source_table) {
      if (!last.pages.includes(tb.page)) last.pages.push(tb.page);
    } else {
      raw.push({ name: tb.source_table, pages: [tb.page] });
    }
  }
  return raw.map((g) => {
    const start = g.pages[0];
    const end = g.pages[g.pages.length - 1];
    return {
      name: g.name,
      pages: g.pages,
      range: start === end ? `p${start}` : `p${start}–${end}`,
    };
  });
}

/** 彙整表格或頁面的提示訊息（同時支援 note 與 notes 欄位） */
export function collectNotes(...sources: Array<string | string[] | null | undefined>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const src of sources) {
    const items = Array.isArray(src) ? src : src ? [src] : [];
    for (const item of items) {
      const trimmed = item.trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        out.push(trimmed);
      }
    }
  }
  return out;
}

/** 判斷儲存格是否為數值格 */
export function isNumericCell(cell: ReferenceCell): boolean {
  return cell.v !== null && cell.v !== undefined;
}

/** 還原儲存格顯示文字：以原書文字 t 為主（保留 01/001 代碼與千分位格式），無 t 時才以 v 千分位格式化 */
export function formatCellText(cell: ReferenceCell): string {
  if (cell.t !== null && cell.t !== undefined && cell.t !== "") {
    return cell.t;
  }
  if (cell.v !== null && cell.v !== undefined) {
    return fmtInt(cell.v);
  }
  return "";
}

/**
 * 計算表頭列數（確保不切斷任何 rowspan）：
 * 1. 從第 0 列開始做 rowspan 閉包。
 * 2. 若第 0 列是整列跨欄群組標題（如「資本支出」「全年度人事費」），且第 1 列無數值格，則將第 1 列納入表頭並再做一次閉包。
 */
export function detectHeaderRowCount(table: ReferenceTable): number {
  const totalRows = Math.max(0, table.rows);
  if (totalRows === 0) return 0;

  const byRow = new Map<number, ReferenceCell[]>();
  for (const cell of table.cells) {
    const list = byRow.get(cell.r);
    if (list) list.push(cell);
    else byRow.set(cell.r, [cell]);
  }

  const expandClosure = (initialEnd: number): number => {
    let end = Math.min(initialEnd, totalRows);
    let changed = true;
    while (changed) {
      changed = false;
      for (const cell of table.cells) {
        if (cell.r < end) {
          const reach = cell.r + Math.max(1, cell.rs ?? 1);
          if (reach > end) {
            end = Math.min(reach, totalRows);
            changed = true;
          }
        }
      }
    }
    return end;
  };

  let headerEnd = expandClosure(1);
  if (headerEnd === 1 && totalRows > 1) {
    const row0 = byRow.get(0) ?? [];
    const row1 = byRow.get(1) ?? [];
    const row0AllMultiCol = row0.length > 0 && row0.every((cell) => (cell.cs ?? 1) > 1);
    const row1HasNumeric = row1.some(isNumericCell);
    if (row0AllMultiCol && !row1HasNumeric) {
      headerEnd = expandClosure(2);
    }
  }

  return headerEnd;
}

/** 將參考表的 cells 依 r 分列、每列依 c 排序，切分為 thead 與 tbody（含 rowspan/colspan，不補空格） */
export function buildTableGrid(table: ReferenceTable): RenderedTableGrid {
  const byRow = new Map<number, ReferenceCell[]>();
  for (const cell of table.cells) {
    const list = byRow.get(cell.r);
    if (list) list.push(cell);
    else byRow.set(cell.r, [cell]);
  }

  const headerEnd = detectHeaderRowCount(table);
  const headerRows: RenderedCell[][] = [];
  const bodyRows: RenderedCell[][] = [];

  for (let r = 0; r < table.rows; r++) {
    const rowCells = (byRow.get(r) ?? [])
      .slice()
      .sort((a, b) => a.c - b.c)
      .map((cell): RenderedCell => {
        const rs = cell.rs && cell.rs > 1 ? cell.rs : undefined;
        const cs = cell.cs && cell.cs > 1 ? cell.cs : undefined;
        const isHeader = r < headerEnd;
        return {
          key: `${cell.r}-${cell.c}`,
          rowspan: rs,
          colspan: cs,
          text: formatCellText(cell),
          isNumeric: isNumericCell(cell),
          scope: isHeader ? (cs ? "colgroup" : "col") : undefined,
        };
      });

    if (r < headerEnd) {
      headerRows.push(rowCells);
    } else {
      bodyRows.push(rowCells);
    }
  }

  return { headerRows, bodyRows };
}
