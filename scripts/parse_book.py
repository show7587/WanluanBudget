#!/usr/bin/env python3
"""Parse raw budget book markdown files into normalized CSVs (Slices S1 & S2)."""

from __future__ import annotations

import csv
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent

SUMMARY_FIELDNAMES = [
    "year",
    "source_book",
    "source_table",
    "page",
    "款",
    "項",
    "科目名稱",
    "本年度",
    "上年度",
    "前年度決算",
]

REVENUE_FIELDNAMES = [
    "year",
    "page",
    "code",
    "name",
    "item_seq",
    "unit",
    "qty",
    "unit_price",
    "amount_元",
    "note",
    "dept",
]

PLANS_FIELDNAMES = [
    "year",
    "page_start",
    "page_end",
    "plan_code",
    "name",
    "dept",
    "政事別",
    "總額",
]

EXPENDITURE_FIELDNAMES = [
    "year",
    "page",
    "plan_code",
    "用途別_code",
    "用途別",
    "unit",
    "qty",
    "unit_price",
    "amount_元",
    "說明",
    "經費來源",
    "item_seq",
]

CORRECTIONS_FIELDNAMES = [
    "year",
    "page",
    "locator",
    "field",
    "old",
    "new",
    "reason",
]

# Map first 2 digits of 11-char expenditure plan_code to (政事別_款, 政事別_項)
PLAN_PREFIX_TO_FUNCTION: dict[str, tuple[str, str]] = {
    "32": ("一般政務支出", "行政支出"),
    "33": ("一般政務支出", "立法支出"),
    "37": ("一般政務支出", "民政支出"),
    "40": ("一般政務支出", "財務支出"),
    "51": ("教育科學文化支出", "教育支出"),
    "53": ("教育科學文化支出", "文化支出"),
    "56": ("經濟發展支出", "農業支出"),
    "57": ("經濟發展支出", "工業支出"),
    "58": ("經濟發展支出", "交通支出"),
    "59": ("經濟發展支出", "其他經濟服務支出"),
    "62": ("社會福利支出", "社會救助支出"),
    "63": ("社會福利支出", "福利服務支出"),
    "71": ("社區發展及環境保護支出", "環境保護支出"),
    "72": ("社區發展及環境保護支出", "社區發展支出"),
    "76": ("退休撫卹支出", "退休撫卹給付支出"),
    "89": ("補助及其他支出", "其他支出"),
}

SINGLE_COMMA_AMOUNT_RE = re.compile(r"^-?\d{1,3}(,\d{3})+$")
SINGLE_PLAIN_AMOUNT_RE = re.compile(r"^-?\d+$")


class HTMLTableGridParser(HTMLParser):
    """Parse an HTML <table> into a 2D list of strings with rowspan/colspan expanded."""

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_cell_parts: list[str] = []
        self.current_rowspan = 1
        self.current_colspan = 1
        self.raw_rows: list[list[tuple[str, int, int]]] = []
        self.current_row: list[tuple[str, int, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower == "table":
            self.in_table = True
            self.raw_rows = []
        elif self.in_table and tag_lower == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_row and tag_lower in ("td", "th"):
            self.in_cell = True
            self.current_cell_parts = []
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            try:
                self.current_rowspan = max(1, int(attr_dict.get("rowspan", "1") or "1"))
            except ValueError:
                self.current_rowspan = 1
            try:
                self.current_colspan = max(1, int(attr_dict.get("colspan", "1") or "1"))
            except ValueError:
                self.current_colspan = 1

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("td", "th") and self.in_cell:
            text = re.sub(r"\s+", " ", "".join(self.current_cell_parts)).strip()
            self.current_row.append((text, self.current_rowspan, self.current_colspan))
            self.in_cell = False
        elif tag_lower == "tr" and self.in_row:
            self.raw_rows.append(self.current_row)
            self.in_row = False
        elif tag_lower == "table" and self.in_table:
            self.in_table = False


def parse_html_table(table_html: str) -> list[list[str]]:
    """Expand a single <table>...</table> string into a 2D rectangular grid."""
    parser = HTMLTableGridParser()
    parser.feed(table_html)
    occupied: dict[tuple[int, int], str] = {}
    max_col = 0
    total_rows = len(parser.raw_rows)

    for r_idx, row_cells in enumerate(parser.raw_rows):
        c_idx = 0
        for text, rowspan, colspan in row_cells:
            while (r_idx, c_idx) in occupied:
                c_idx += 1
            for dr in range(rowspan):
                for dc in range(colspan):
                    target_r = r_idx + dr
                    target_c = c_idx + dc
                    if target_r < total_rows:
                        occupied[(target_r, target_c)] = text
            c_idx += colspan
            if c_idx > max_col:
                max_col = c_idx

    grid: list[list[str]] = []
    for r_idx in range(total_rows):
        row = [occupied.get((r_idx, c_idx), "") for c_idx in range(max_col)]
        grid.append(row)
    return grid


def parse_single_amount(raw_val: str, allow_empty: bool = False) -> tuple[int | None, bool]:
    """Validate and parse a single integer amount string without silent coercion."""
    s = raw_val.strip()
    if s in ("", "-"):
        if allow_empty:
            return (None, True)
        return (None, False)
    if SINGLE_COMMA_AMOUNT_RE.match(s) or SINGLE_PLAIN_AMOUNT_RE.match(s):
        return (int(s.replace(",", "")), True)
    return (None, False)


def eval_qty_value(qty_str: str) -> tuple[float | None, bool]:
    """Evaluate a quantity string like '1', '14', '14×12' into a number."""
    s = qty_str.strip()
    if not s:
        return (None, False)
    parts = re.split(r"[×*xX]", s)
    product = 1.0
    for p in parts:
        p_clean = p.strip()
        # 原書數量欄偶爾印有千分位逗號（例如 54,000 票），逗號只可出現在每三位之前
        if re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", p_clean):
            p_clean = p_clean.replace(",", "")
        if not re.match(r"^\d+(\.\d+)?$", p_clean):
            return (None, False)
        product *= float(p_clean)
    return (product, True)


def parse_toc(part1_text: str) -> dict[str, tuple[int, int]]:
    """Extract section page ranges (start_page, end_page) from the TOC in part1.md."""
    toc: dict[str, tuple[int, int]] = {}
    lines = [ln.strip() for ln in part1_text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        m = re.match(r"^第\s*(\d+)\s*頁至第\s*(\d+)\s*頁$", line)
        if m and i > 0:
            prev_line = lines[i - 1]
            title = re.sub(r"^[一二三四五六七八九十]+、", "", prev_line).strip()
            base_title = re.sub(r"\(.*?\)$", "", title).strip()
            start_p, end_p = int(m.group(1)), int(m.group(2))
            toc[title] = (start_p, end_p)
            if base_title not in toc:
                toc[base_title] = (start_p, end_p)
    return toc


def load_toc(raw_dir: Path, part1_text: str) -> dict[str, tuple[int, int]]:
    """Read the TOC from part1.md; if the scan has no TOC page, fall back to a hand-made raw/<年度>/toc.md."""
    toc = parse_toc(part1_text)
    if toc:
        return toc
    toc_path = raw_dir / "toc.md"
    if toc_path.exists():
        return parse_toc(toc_path.read_text(encoding="utf-8"))
    return toc


def load_corrections(corrections_path: Path, year: str) -> dict[tuple[int, str, str], dict[str, str]]:
    """Load OCR corrections for the given year keyed by (page, locator, field).

    Raises ValueError if any row has mismatched column count or empty reason.
    """
    corrections: dict[tuple[int, str, str], dict[str, str]] = {}
    if not corrections_path.exists():
        return corrections
    with corrections_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if list(reader.fieldnames or []) != CORRECTIONS_FIELDNAMES:
            raise ValueError(
                f"corrections.csv 表頭欄位不符：預期 {CORRECTIONS_FIELDNAMES}，實際 {reader.fieldnames}"
            )
        for line_idx, row in enumerate(reader, start=2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"corrections.csv 第 {line_idx} 列欄位數與表頭不符：{row!r}")
            if not row.get("reason", "").strip():
                raise ValueError(f"corrections.csv 第 {line_idx} 列 reason 不可為空：{row!r}")
            if str(row.get("year", "")).strip() != str(year):
                continue
            page = int(row["page"])
            locator = row["locator"].strip()
            field = row["field"].strip()
            corrections[(page, locator, field)] = row
    return corrections


def find_unapplied_corrections(
    corrections: dict[tuple[int, str, str], dict[str, str]],
    applied_corrections: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return corrections registered in corrections.csv that were never matched/applied."""
    applied_keys = {
        (int(c["page"]), c["locator"].strip(), c["field"].strip()) for c in applied_corrections
    }
    return [corr for key, corr in corrections.items() if key not in applied_keys]


def normalize_summary_subject(source_table: str, raw_name: str, section_prefix: str = "") -> str:
    """Normalize summary subject names so cross-table comparisons align on identical subjects."""
    name = re.sub(r"\s+", "", raw_name.strip())
    if source_table == "歲入歲出簡明比較分析表":
        if name == "一、歲入合計":
            return "歲入合計"
        if name == "二、歲出合計":
            return "歲出合計"
        if name == "三、歲入歲出餘絀":
            return "歲入歲出餘絀"
        return re.sub(r"^\d+\.", "", name)

    if source_table == "歲入歲出性質及餘絀簡明比較分析表":
        if name in ("一、經常門", "二、資本門"):
            return name
        if name == "三、歲入歲出餘絀":
            return "歲入歲出餘絀"
        cleaned = re.sub(r"^(\([一二三]\)|\d+\.)", "", name)
        if section_prefix:
            return f"{section_prefix}-{cleaned}"
        return cleaned

    if source_table == "收支簡明比較分析表":
        if name == "(一)歲入":
            return "歲入合計"
        if name == "(一)歲出":
            return "歲出合計"
        return re.sub(r"^([一二三]、|\([一二三]\))", "", name)

    if source_table in ("歲入來源別預算總表", "歲入來源別預算比較總表"):
        if name in ("合計", "經資門合計"):
            return "歲入合計"
        return name

    if source_table in ("歲出政事別預算總表", "歲出政事別預算比較總表", "歲出機關別預算比較總表"):
        if name in ("合計", "經資門合計"):
            return "歲出合計"
        return name

    return name


PART1_SECTIONS = [
    ("歲入歲出簡明比較分析表", "歲入歲出簡明比較分析表"),
    ("歲入歲出性質及餘絀簡明比較分析表", "歲入歲出性質及餘絀簡明比較分析表"),
    ("收支簡明比較分析表", "收支簡明比較分析表"),
    ("歲入來源別預算總表", "歲入來源別預算總表"),
    ("歲入來源別預算比較總表(經資門併計)", "歲入來源別預算比較總表"),
    ("歲出政事別預算總表", "歲出政事別預算總表"),
    ("歲出政事別預算比較總表(經資門併計)", "歲出政事別預算比較總表"),
    ("歲出機關別預算比較總表(經資門併計)", "歲出機關別預算比較總表"),
]


def extract_tables_with_preceding_text(md_text: str) -> list[tuple[str, str]]:
    """Return list of (preceding_text, table_html) for every <table> in md_text."""
    results: list[tuple[str, str]] = []
    pos = 0
    for m in re.finditer(r"<table\b[^>]*>.*?</table>", md_text, flags=re.DOTALL | re.IGNORECASE):
        preceding = md_text[pos : m.start()]
        results.append((preceding, m.group(0)))
        pos = m.end()
    return results


def split_merged_summary_tables(table_html: str) -> list[str]:
    """Split one <table> that OCR merged from several pages (a second 「科目」 header row inside) into one table per page."""
    rows = re.findall(r"<tr\b[^>]*>.*?</tr>", table_html, flags=re.DOTALL | re.IGNORECASE)
    cut_idx = [
        i
        for i, r in enumerate(rows)
        if i > 0 and re.search(r"<td\b[^>]*>\s*科目\s*</td>", r)
    ]
    if not cut_idx:
        return [table_html]
    bounds = [0] + cut_idx + [len(rows)]
    return ["<table>" + "".join(rows[a:b]) + "</table>" for a, b in zip(bounds, bounds[1:])]


def parse_part1_summary(
    part1_text: str,
    year: str,
    toc: dict[str, tuple[int, int]],
    corrections: dict[tuple[int, str, str], dict[str, str]],
    partial: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse all summary tables in part1.md, verify page counts, and return rows in 元.

    partial=True（OCR 品質較差的年度）：先拆開被合併的跨頁表格，標題文字無法識別時改依目錄順序逐頁分派。
    """
    blocks = extract_tables_with_preceding_text(part1_text)
    if partial:
        expanded: list[tuple[str, str]] = []
        for preceding, table_html in blocks:
            pieces = split_merged_summary_tables(table_html)
            expanded.append((preceding, pieces[0]))
            expanded.extend(("", piece) for piece in pieces[1:])
        blocks = expanded
    section_tables: dict[str, list[str]] = {canon: [] for _, canon in PART1_SECTIONS}
    label_failed = False

    for preceding, table_html in blocks:
        matched_canon = None
        best_pos = -1
        for _, canon in PART1_SECTIONS:
            idx = preceding.rfind(canon)
            if idx > best_pos or (idx == best_pos and idx != -1 and len(canon) > len(matched_canon or "")):
                best_pos = idx
                matched_canon = canon
        if matched_canon is None:
            if not partial:
                raise ValueError(f"無法識別 part1 表格所屬章節，前導文字：{preceding.strip()[-80:]}")
            label_failed = True
            break
        section_tables[matched_canon].append(table_html)

    assignment = "標題"
    if partial:
        label_ok = not label_failed and all(
            len(section_tables[canon])
            == (toc.get(key) or toc[canon])[1] - (toc.get(key) or toc[canon])[0] + 1
            for key, canon in PART1_SECTIONS
            if key in toc or canon in toc
        )
        if not label_ok:
            # 標題被 OCR 弄丟或錯置：依目錄順序逐頁分派
            assignment = "目錄順序"
            section_tables = {canon: [] for _, canon in PART1_SECTIONS}
            cursor = 0
            for key, canon in PART1_SECTIONS:
                if key not in toc and canon not in toc:
                    continue
                sp, ep = toc.get(key) or toc[canon]
                section_tables[canon] = [t for _, t in blocks[cursor : cursor + (ep - sp + 1)]]
                cursor += ep - sp + 1

    summary_rows: list[dict[str, Any]] = []
    unregistered_anomalies: list[dict[str, Any]] = []
    applied_corrections: list[dict[str, Any]] = []
    part1_section_checks: list[dict[str, Any]] = []

    for toc_key, canon_table_name in PART1_SECTIONS:
        if toc_key not in toc and canon_table_name not in toc:
            raise ValueError(f"目次中找不到章節：{toc_key}")
        start_page, end_page = toc.get(toc_key) or toc[canon_table_name]
        expected_pages = end_page - start_page + 1
        tables = section_tables[canon_table_name]
        if len(tables) != expected_pages:
            raise ValueError(
                f"章節「{canon_table_name}」表頭數 ({len(tables)}) != 目錄頁數 ({expected_pages}, p{start_page}-p{end_page})"
            )
        part1_section_checks.append(
            {
                "section_name": canon_table_name,
                "page_start": start_page,
                "page_end": end_page,
                "expected_pages": expected_pages,
                "actual_pages": len(tables),
                "passed": len(tables) == expected_pages,
                "assignment": assignment,
            }
        )

        current_kuan = ""
        for idx, table_html in enumerate(tables):
            page = start_page + idx
            grid = parse_html_table(table_html)
            if not grid:
                continue

            if canon_table_name in ("歲入歲出簡明比較分析表", "歲入歲出性質及餘絀簡明比較分析表"):
                section_prefix = ""
                for r in grid[2:]:
                    raw_subj = r[0].strip()
                    if not raw_subj:
                        continue
                    if canon_table_name == "歲入歲出性質及餘絀簡明比較分析表":
                        if "經常門" in raw_subj and raw_subj.startswith("一、"):
                            section_prefix = "經常門"
                            continue
                        if "資本門" in raw_subj and raw_subj.startswith("二、"):
                            section_prefix = "資本門"
                            continue
                    subj = normalize_summary_subject(canon_table_name, raw_subj, section_prefix)
                    vals: dict[str, str] = {}
                    for field_name, col_idx in (("本年度", 1), ("上年度", 3), ("前年度決算", 5)):
                        raw_v = r[col_idx] if col_idx < len(r) else ""
                        val_int, ok = parse_single_amount(raw_v, allow_empty=True)
                        if not ok:
                            unregistered_anomalies.append(
                                {
                                    "page": page,
                                    "source_table": canon_table_name,
                                    "locator": f"{canon_table_name}:{subj}",
                                    "field": field_name,
                                    "raw_value": raw_v,
                                }
                            )
                            vals[field_name] = ""
                        else:
                            vals[field_name] = str(val_int * 1000) if val_int is not None else ""
                    summary_rows.append(
                        {
                            "year": year,
                            "source_book": "part1",
                            "source_table": canon_table_name,
                            "page": page,
                            "款": "",
                            "項": "",
                            "科目名稱": subj,
                            "本年度": vals["本年度"],
                            "上年度": vals["上年度"],
                            "前年度決算": vals["前年度決算"],
                        }
                    )

            elif canon_table_name == "收支簡明比較分析表":
                for r in grid[1:]:
                    raw_subj = r[0].strip()
                    if not raw_subj:
                        continue
                    subj = normalize_summary_subject(canon_table_name, raw_subj)
                    vals = {}
                    for field_name, col_idx in (("本年度", 1), ("上年度", 2), ("前年度決算", 3)):
                        raw_v = r[col_idx] if col_idx < len(r) else ""
                        val_int, ok = parse_single_amount(raw_v, allow_empty=True)
                        if not ok:
                            unregistered_anomalies.append(
                                {
                                    "page": page,
                                    "source_table": canon_table_name,
                                    "locator": f"{canon_table_name}:{subj}",
                                    "field": field_name,
                                    "raw_value": raw_v,
                                }
                            )
                            vals[field_name] = ""
                        else:
                            vals[field_name] = str(val_int * 1000) if val_int is not None else ""
                    summary_rows.append(
                        {
                            "year": year,
                            "source_book": "part1",
                            "source_table": canon_table_name,
                            "page": page,
                            "款": "",
                            "項": "",
                            "科目名稱": subj,
                            "本年度": vals["本年度"],
                            "上年度": vals["上年度"],
                            "前年度決算": vals["前年度決算"],
                        }
                    )

            elif canon_table_name in ("歲入來源別預算總表", "歲出政事別預算總表"):
                for r in grid[2:]:
                    kuan = r[0].strip()
                    hsiang = r[1].strip()
                    raw_name = r[2].strip()
                    if not raw_name:
                        continue
                    locator = f"{canon_table_name}:{kuan}-{hsiang}-{raw_name}"
                    if (page, locator, "款") in corrections:
                        corr = corrections[(page, locator, "款")]
                        if kuan == corr["old"]:
                            kuan = corr["new"]
                            applied_corrections.append(corr)
                    if (page, locator, "項") in corrections:
                        corr = corrections[(page, locator, "項")]
                        if hsiang == corr["old"]:
                            hsiang = corr["new"]
                            applied_corrections.append(corr)
                    if (page, locator, "科目名稱") in corrections:
                        corr = corrections[(page, locator, "科目名稱")]
                        if raw_name == corr["old"]:
                            raw_name = corr["new"]
                            applied_corrections.append(corr)
                    if kuan:
                        current_kuan = kuan
                    elif hsiang and current_kuan:
                        kuan = current_kuan
                    subj = normalize_summary_subject(canon_table_name, raw_name)
                    raw_v = r[5] if len(r) > 5 else ""
                    val_int, ok = parse_single_amount(raw_v, allow_empty=True)
                    if not ok:
                        unregistered_anomalies.append(
                            {
                                "page": page,
                                "source_table": canon_table_name,
                                "locator": locator,
                                "field": "本年度",
                                "raw_value": raw_v,
                            }
                        )
                        curr_val = ""
                    else:
                        curr_val = str(val_int * 1000) if val_int is not None else ""
                    summary_rows.append(
                        {
                            "year": year,
                            "source_book": "part1",
                            "source_table": canon_table_name,
                            "page": page,
                            "款": kuan,
                            "項": hsiang,
                            "科目名稱": subj,
                            "本年度": curr_val,
                            "上年度": "",
                            "前年度決算": "",
                        }
                    )

            elif canon_table_name in ("歲入來源別預算比較總表", "歲出政事別預算比較總表"):
                for r in grid[2:]:
                    kuan = r[0].strip()
                    hsiang = r[1].strip()
                    raw_name = r[2].strip()
                    if not raw_name:
                        continue
                    if kuan:
                        current_kuan = kuan
                    elif hsiang and current_kuan:
                        kuan = current_kuan
                    locator = f"{canon_table_name}:{kuan}-{hsiang}"
                    if (page, locator, "科目名稱") in corrections:
                        corr = corrections[(page, locator, "科目名稱")]
                        if raw_name == corr["old"]:
                            raw_name = corr["new"]
                            applied_corrections.append(corr)
                    subj = normalize_summary_subject(canon_table_name, raw_name)
                    vals = {}
                    for field_name, col_idx in (("本年度", 3), ("上年度", 4), ("前年度決算", 5)):
                        raw_v = r[col_idx] if col_idx < len(r) else ""
                        val_int, ok = parse_single_amount(raw_v, allow_empty=True)
                        if not ok:
                            unregistered_anomalies.append(
                                {
                                    "page": page,
                                    "source_table": canon_table_name,
                                    "locator": f"{locator}:{subj}",
                                    "field": field_name,
                                    "raw_value": raw_v,
                                }
                            )
                            vals[field_name] = ""
                        else:
                            vals[field_name] = str(val_int * 1000) if val_int is not None else ""
                    summary_rows.append(
                        {
                            "year": year,
                            "source_book": "part1",
                            "source_table": canon_table_name,
                            "page": page,
                            "款": kuan,
                            "項": hsiang,
                            "科目名稱": subj,
                            "本年度": vals["本年度"],
                            "上年度": vals["上年度"],
                            "前年度決算": vals["前年度決算"],
                        }
                    )

            elif canon_table_name == "歲出機關別預算比較總表":
                for r in grid[2:]:
                    kuan = r[0].strip()
                    raw_name = r[1].strip()
                    if not raw_name:
                        continue
                    subj = normalize_summary_subject(canon_table_name, raw_name)
                    vals = {}
                    for field_name, col_idx in (("本年度", 2), ("上年度", 3), ("前年度決算", 4)):
                        raw_v = r[col_idx] if col_idx < len(r) else ""
                        val_int, ok = parse_single_amount(raw_v, allow_empty=True)
                        if not ok:
                            unregistered_anomalies.append(
                                {
                                    "page": page,
                                    "source_table": canon_table_name,
                                    "locator": f"{canon_table_name}:{kuan}-{subj}",
                                    "field": field_name,
                                    "raw_value": raw_v,
                                }
                            )
                            vals[field_name] = ""
                        else:
                            vals[field_name] = str(val_int * 1000) if val_int is not None else ""
                    summary_rows.append(
                        {
                            "year": year,
                            "source_book": "part1",
                            "source_table": canon_table_name,
                            "page": page,
                            "款": kuan,
                            "項": "",
                            "科目名稱": subj,
                            "本年度": vals["本年度"],
                            "上年度": vals["上年度"],
                            "前年度決算": vals["前年度決算"],
                        }
                    )

    return summary_rows, unregistered_anomalies, applied_corrections, part1_section_checks


def parse_part3_revenue(
    part3_text: str,
    year: str,
    toc: dict[str, tuple[int, int]],
    corrections: dict[tuple[int, str, str], dict[str, str]],
    partial: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Parse Part3 revenue detail tables (歲入項目說明提要), infer pages, and apply corrections.

    partial=True：表頭文字被 OCR 漏掉時，改取 part3 開頭的 <table>（歲入明細在最前面，共目錄頁數張）。
    """
    toc_key = "歲入項目說明提要與預算明細表"
    if toc_key not in toc:
        raise ValueError(f"目次中找不到章節：{toc_key}")
    start_page, end_page = toc[toc_key]
    expected_pages = end_page - start_page + 1

    blocks = extract_tables_with_preceding_text(part3_text)
    revenue_tables: list[str] = []
    for preceding, table_html in blocks:
        if "歲入項目說明提要" in preceding:
            revenue_tables.append(table_html)

    if partial and len(revenue_tables) != expected_pages:
        revenue_tables = [t for _, t in blocks[:expected_pages]]

    header_count = len(revenue_tables)
    if header_count != expected_pages and not partial:
        raise ValueError(
            f"章節「{toc_key}」表頭數 ({header_count}) != 目錄頁數 ({expected_pages}, p{start_page}-p{end_page})"
        )

    revenue_items: list[dict[str, Any]] = []
    revenue_headers_meta: list[dict[str, Any]] = []
    unregistered_anomalies: list[dict[str, Any]] = []
    applied_corrections: list[dict[str, Any]] = []

    current_code = ""
    current_name = ""
    current_dept = ""
    current_raw_row_seq = 0
    current_item_seq = 0
    current_header_k: int | None = None

    for idx, table_html in enumerate(revenue_tables):
        page = start_page + idx
        grid = parse_html_table(table_html)
        if not grid:
            continue

        first_row = grid[0]
        if any("來源別子目及細目編號" in cell for cell in first_row):
            code_name_cell = ""
            dept_cell = ""
            budget_cell = ""
            for c_i, cell_val in enumerate(first_row):
                if "來源別子目及細目編號" in cell_val:
                    for next_c in range(c_i + 1, len(first_row)):
                        if first_row[next_c] != cell_val and first_row[next_c].strip():
                            code_name_cell = first_row[next_c].strip()
                            break
                elif cell_val.strip() == "承辦單位":
                    for next_c in range(c_i + 1, len(first_row)):
                        if first_row[next_c] != cell_val and first_row[next_c].strip():
                            dept_cell = first_row[next_c].strip()
                            break
                elif cell_val.strip() == "預算金額":
                    for next_c in range(c_i + 1, len(first_row)):
                        if first_row[next_c] != cell_val and first_row[next_c].strip():
                            budget_cell = first_row[next_c].strip()
                            break

            m_code = re.match(r"^(\d{11})\s*(.*)$", code_name_cell)
            if not m_code:
                raise ValueError(f"p{page} 無法解析 11 碼歲入細目編號：{code_name_cell!r}")
            current_code = m_code.group(1)
            current_name = m_code.group(2).strip()
            current_dept = dept_cell
            current_raw_row_seq = 0
            current_item_seq = 0

            m_budget = re.match(r"^([0-9,]+)\s*千元$", budget_cell)
            if not m_budget:
                raise ValueError(f"p{page} ({current_code}) 無法解析表頭預算金額：{budget_cell!r}")
            header_val_k, ok = parse_single_amount(m_budget.group(1), allow_empty=False)
            if not ok or header_val_k is None:
                raise ValueError(f"p{page} ({current_code}) 表頭預算金額格式異常：{budget_cell!r}")
            current_header_k = header_val_k

            revenue_headers_meta.append(
                {
                    "year": year,
                    "code": current_code,
                    "name": current_name,
                    "dept": current_dept,
                    "page_start": page,
                    "page_end": page,
                    "header_budget_元": header_val_k * 1000,
                }
            )
        else:
            if not current_code:
                raise ValueError(f"p{page} 出現續頁但前無細目表頭")
            revenue_headers_meta[-1]["page_end"] = page

        col_header_r = None
        for r_i, r in enumerate(grid):
            if any("科目名稱及編號" in c for c in r):
                col_header_r = r_i
                break
        if col_header_r is None:
            raise ValueError(f"p{page} 找不到「科目名稱及編號」欄位表頭列")

        hdr_row = grid[col_header_r]
        col_unit = hdr_row.index("單位")
        col_qty = hdr_row.index("數量")
        col_price = hdr_row.index("單價")
        col_amount = hdr_row.index("預算數")
        col_note = hdr_row.index("說明及收入依據")

        for r in grid[col_header_r + 1 :]:
            current_raw_row_seq += 1
            locator = f"{current_code}:{current_raw_row_seq}"

            row_action_key = (page, locator, "_row_action")
            if row_action_key in corrections:
                corr = corrections[row_action_key]
                raw_amt_check = r[col_amount].strip()
                if raw_amt_check == corr["old"] and corr["new"] == "DROP_SUBTOTAL_ROW":
                    applied_corrections.append(corr)
                    continue

            row_fields = {
                "unit": r[col_unit].strip(),
                "qty": r[col_qty].strip(),
                "unit_price": r[col_price].strip(),
                "amount_元": r[col_amount].strip(),
                "note": r[col_note].strip(),
            }

            for f_name in ("unit", "qty", "unit_price", "amount_元", "note"):
                c_key = (page, locator, f_name)
                if c_key in corrections:
                    corr = corrections[c_key]
                    if row_fields[f_name] == corr["old"]:
                        row_fields[f_name] = corr["new"]
                        applied_corrections.append(corr)

            split_counts = {k: len(v.split("||")) for k, v in row_fields.items() if "||" in v}
            if split_counts:
                n_parts = max(split_counts.values())
                expanded_rows = []
                for p_i in range(n_parts):
                    sub = {}
                    for k, v in row_fields.items():
                        parts = v.split("||")
                        sub[k] = parts[p_i].strip() if p_i < len(parts) else parts[-1].strip()
                    expanded_rows.append(sub)
            else:
                expanded_rows = [row_fields]

            for sub_row in expanded_rows:
                current_item_seq += 1
                # 表頭預算金額為 0 千元的細目，原書的單價與預算數欄是空白，視為 0（不是 OCR 漏字）
                zero_budget_blank = (
                    current_header_k == 0
                    and sub_row["unit_price"].strip() in ("", "-")
                    and sub_row["amount_元"].strip() in ("", "-")
                )
                if zero_budget_blank:
                    sub_row["unit_price"] = "0"
                    sub_row["amount_元"] = "0"
                u_price, ok_price = parse_single_amount(sub_row["unit_price"], allow_empty=False)
                amt_val, ok_amt = parse_single_amount(sub_row["amount_元"], allow_empty=False)
                qty_val, ok_qty = eval_qty_value(sub_row["qty"])

                if not ok_price or u_price is None:
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "unit_price",
                            "raw_value": sub_row["unit_price"],
                        }
                    )
                if not ok_amt or amt_val is None:
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "amount_元",
                            "raw_value": sub_row["amount_元"],
                        }
                    )
                if not ok_qty or qty_val is None:
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "qty",
                            "raw_value": sub_row["qty"],
                        }
                    )

                if ok_price and ok_amt and ok_qty and u_price is not None and amt_val is not None and qty_val is not None:
                    expected_amt = round(qty_val * u_price)
                    if expected_amt != amt_val:
                        unregistered_anomalies.append(
                            {
                                "page": page,
                                "source_table": toc_key,
                                "locator": locator,
                                "field": "amount_元(單價×數量不符)",
                                "raw_value": f"qty={sub_row['qty']}, unit_price={sub_row['unit_price']}, amount_元={sub_row['amount_元']}",
                            }
                        )

                revenue_items.append(
                    {
                        "year": year,
                        "page": page,
                        "code": current_code,
                        "name": current_name,
                        "item_seq": current_item_seq,
                        "unit": sub_row["unit"],
                        "qty": sub_row["qty"],
                        "unit_price": str(u_price) if u_price is not None else sub_row["unit_price"],
                        "amount_元": str(amt_val) if amt_val is not None else sub_row["amount_元"],
                        "note": sub_row["note"],
                        "dept": current_dept,
                    }
                )

    # Match _known_diff entries against actual fine-item sum differences
    for hdr in revenue_headers_meta:
        code = hdr["code"]
        diff_key = (hdr["page_start"], code, "_known_diff")
        if diff_key in corrections:
            corr = corrections[diff_key]
            actual_sum = 0
            for item in revenue_items:
                if item["code"] == code:
                    v, ok = parse_single_amount(item["amount_元"], allow_empty=False)
                    if ok and v is not None:
                        actual_sum += v
            actual_diff = actual_sum - hdr["header_budget_元"]
            reg_diff, ok_reg = parse_single_amount(corr["old"], allow_empty=False)
            if ok_reg and reg_diff is not None and reg_diff == actual_diff and corr["new"] == "UNRESOLVED":
                applied_corrections.append(corr)

    return revenue_items, revenue_headers_meta, unregistered_anomalies, applied_corrections, header_count


def parse_part3_expenditure(
    part3_text: str,
    year: str,
    toc: dict[str, tuple[int, int]],
    corrections: dict[tuple[int, str, str], dict[str, str]],
    partial: bool = False,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
]:
    """Parse Part3 expenditure detail tables (歲出計畫說明提要), infer pages, and apply corrections.

    partial=True：來源檔被截斷（歲出明細頁數少於目錄）時，只解析現有的頁，不報錯；
    表頭文字漏掉時，改取歲入明細之後的 <table>，頁碼自目錄起始頁依序推算。
    """
    toc_key = "歲出計畫說明提要與各項費用明細表"
    if toc_key not in toc:
        raise ValueError(f"目次中找不到章節：{toc_key}")
    start_page, end_page = toc[toc_key]
    expected_pages = end_page - start_page + 1

    blocks = extract_tables_with_preceding_text(part3_text)
    expenditure_tables: list[str] = []
    for preceding, table_html in blocks:
        if "歲出計畫說明提要" in preceding:
            expenditure_tables.append(table_html)

    if partial and len(expenditure_tables) != expected_pages:
        rev_start, rev_end = toc["歲入項目說明提要與預算明細表"]
        rev_pages = rev_end - rev_start + 1
        expenditure_tables = [t for _, t in blocks[rev_pages : rev_pages + expected_pages]]

    header_count = len(expenditure_tables)
    if header_count != expected_pages and not partial:
        raise ValueError(
            f"章節「{toc_key}」表頭數 ({header_count}) != 目錄頁數 ({expected_pages}, p{start_page}-p{end_page})"
        )

    plans_rows: list[dict[str, Any]] = []
    plans_meta: list[dict[str, Any]] = []
    expenditure_items: list[dict[str, Any]] = []
    unregistered_anomalies: list[dict[str, Any]] = []
    applied_corrections: list[dict[str, Any]] = []

    current_plan_code = ""
    current_raw_row_seq = 0
    current_funding_source = ""
    current_use_code = ""
    current_use_name = ""
    current_use_item_seq = 0

    for idx, table_html in enumerate(expenditure_tables):
        page = start_page + idx
        grid = parse_html_table(table_html)
        if not grid:
            continue

        first_row = next(
            (r for r in grid[:2] if any("業務計畫及工作計畫名稱與編號" in cell for cell in r)),
            grid[0],
        )
        if any("業務計畫及工作計畫名稱與編號" in cell for cell in first_row):
            code_name_cell = ""
            dept_cell = ""
            budget_cell = ""
            for c_i, cell_val in enumerate(first_row):
                if "業務計畫及工作計畫名稱與編號" in cell_val:
                    for next_c in range(c_i + 1, len(first_row)):
                        if first_row[next_c] != cell_val and first_row[next_c].strip():
                            code_name_cell = first_row[next_c].strip()
                            break
                elif cell_val.strip() == "承辦單位":
                    for next_c in range(c_i + 1, len(first_row)):
                        if first_row[next_c] != cell_val and first_row[next_c].strip():
                            dept_cell = first_row[next_c].strip()
                            break
                elif cell_val.strip() == "預算金額":
                    for next_c in range(c_i + 1, len(first_row)):
                        if first_row[next_c] != cell_val and first_row[next_c].strip():
                            budget_cell = first_row[next_c].strip()
                            break

            m_code = re.match(r"^([0-9a-zA-Z]{11})\s*(.*)$", code_name_cell)
            if not m_code:
                raise ValueError(f"p{page} 無法解析 11 碼歲出工作計畫編號：{code_name_cell!r}")
            current_plan_code = m_code.group(1)
            plan_name = m_code.group(2).strip()

            dept_corr_key = (page, current_plan_code, "dept")
            if dept_corr_key in corrections:
                corr = corrections[dept_corr_key]
                if dept_cell == corr["old"]:
                    dept_cell = corr["new"]
                    applied_corrections.append(corr)

            prefix = current_plan_code[:2]
            if prefix not in PLAN_PREFIX_TO_FUNCTION:
                raise ValueError(f"p{page} ({current_plan_code}) 未知的政事別前綴：{prefix!r}")
            func_kuan, func_hsiang = PLAN_PREFIX_TO_FUNCTION[prefix]

            m_budget = re.match(r"^([0-9,]+)\s*千元$", budget_cell)
            if not m_budget:
                raise ValueError(f"p{page} ({current_plan_code}) 無法解析表頭預算金額：{budget_cell!r}")
            header_val_k, ok = parse_single_amount(m_budget.group(1), allow_empty=False)
            if not ok or header_val_k is None:
                raise ValueError(f"p{page} ({current_plan_code}) 表頭預算金額格式異常：{budget_cell!r}")
            header_budget_yuan = header_val_k * 1000

            current_raw_row_seq = 0
            current_funding_source = ""
            current_use_code = ""
            current_use_name = ""
            current_use_item_seq = 0

            plan_row = {
                "year": year,
                "page_start": page,
                "page_end": page,
                "plan_code": current_plan_code,
                "name": plan_name,
                "dept": dept_cell,
                "政事別": func_kuan,
                "總額": str(header_budget_yuan),
            }
            plans_rows.append(plan_row)
            plans_meta.append(
                {
                    "year": year,
                    "page_start": page,
                    "page_end": page,
                    "plan_code": current_plan_code,
                    "name": plan_name,
                    "dept": dept_cell,
                    "政事別": func_kuan,
                    "政事別_項": func_hsiang,
                    "header_budget_元": header_budget_yuan,
                    "total_row_budget_元": None,
                    "funding_source": "",
                    "level1_subtotals": [],
                    "level2_subtotals": [],
                }
            )
        else:
            if not current_plan_code:
                raise ValueError(f"p{page} 出現續頁但前無工作計畫表頭")
            plans_rows[-1]["page_end"] = page
            plans_meta[-1]["page_end"] = page

        col_header_r = None
        for r_i, r in enumerate(grid):
            if any("用途別科目" in c for c in r):
                col_header_r = r_i
                break
        if col_header_r is None:
            raise ValueError(f"p{page} 找不到「用途別科目」欄位表頭列")

        hdr_row = grid[col_header_r]
        col_subj = next(i for i, c in enumerate(hdr_row) if "用途別科目" in c)
        col_unit = hdr_row.index("單位")
        col_qty = hdr_row.index("數量")
        col_price = hdr_row.index("單價")
        col_amount = hdr_row.index("預算數")
        col_note = hdr_row.index("說明")

        for r in grid[col_header_r + 1 :]:
            current_raw_row_seq += 1
            locator = f"{current_plan_code}:{current_raw_row_seq}"

            row_action_key = (page, locator, "_row_action")
            if row_action_key in corrections:
                corr = corrections[row_action_key]
                raw_amt_check = r[col_amount].strip()
                if raw_amt_check == corr["old"] and corr["new"] == "DROP_SUBTOTAL_ROW":
                    applied_corrections.append(corr)
                    continue

            row_fields = {
                "用途別科目": r[col_subj].strip(),
                "unit": r[col_unit].strip(),
                "qty": r[col_qty].strip(),
                "unit_price": r[col_price].strip(),
                "amount_元": r[col_amount].strip(),
                "說明": r[col_note].strip(),
            }

            for f_name in ("用途別科目", "unit", "qty", "unit_price", "amount_元", "說明"):
                c_key = (page, locator, f_name)
                if c_key in corrections:
                    corr = corrections[c_key]
                    if row_fields[f_name] == corr["old"]:
                        row_fields[f_name] = corr["new"]
                        applied_corrections.append(corr)

            split_counts = {k: len(v.split("||")) for k, v in row_fields.items() if "||" in v}
            if split_counts:
                n_parts = max(split_counts.values())
                expanded_rows: list[dict[str, str]] = []
                for p_i in range(n_parts):
                    sub: dict[str, str] = {}
                    subj_parts = row_fields["用途別科目"].split("||")
                    sub_subj = (
                        subj_parts[p_i].strip()
                        if p_i < len(subj_parts)
                        else (subj_parts[-1].strip() if "||" not in row_fields["用途別科目"] else "")
                    )
                    sub["用途別科目"] = sub_subj
                    is_header_or_subtotal_subrow = sub_subj != "" and "||" in row_fields["用途別科目"]
                    for k in ("unit", "qty", "unit_price", "amount_元", "說明"):
                        v = row_fields[k]
                        if "||" in v:
                            parts = v.split("||")
                            sub[k] = parts[p_i].strip() if p_i < len(parts) else ""
                        elif is_header_or_subtotal_subrow and k in ("unit", "qty", "unit_price"):
                            sub[k] = ""
                        else:
                            sub[k] = v.strip()
                    expanded_rows.append(sub)
            else:
                expanded_rows = [row_fields]

            for sub_row in expanded_rows:
                subj_str = sub_row["用途別科目"].strip()
                unit_str = sub_row["unit"].strip()
                qty_str = sub_row["qty"].strip()
                price_str = sub_row["unit_price"].strip()
                amt_str = sub_row["amount_元"].strip()
                note_str = sub_row["說明"].strip()

                is_summary_like = unit_str == "" and qty_str == "" and price_str == ""

                if is_summary_like:
                    if subj_str == "合計":
                        amt_val, ok_amt = parse_single_amount(amt_str, allow_empty=False)
                        if not ok_amt or amt_val is None:
                            unregistered_anomalies.append(
                                {
                                    "page": page,
                                    "source_table": toc_key,
                                    "locator": locator,
                                    "field": "amount_元(合計)",
                                    "raw_value": amt_str,
                                }
                            )
                        else:
                            plans_meta[-1]["total_row_budget_元"] = amt_val
                        plans_meta[-1]["funding_source"] = note_str
                        current_funding_source = note_str
                        continue

                    m_use = re.match(r"^(\d{4})\s*(.+)$", subj_str)
                    if m_use:
                        use_code = m_use.group(1)
                        use_name = re.sub(r"\s+", "", m_use.group(2).strip())
                        amt_val, ok_amt = parse_single_amount(amt_str, allow_empty=False)
                        if not ok_amt or amt_val is None:
                            unregistered_anomalies.append(
                                {
                                    "page": page,
                                    "source_table": toc_key,
                                    "locator": locator,
                                    "field": f"amount_元({use_code}小計)",
                                    "raw_value": amt_str,
                                }
                            )
                        if use_code.endswith("00"):
                            current_funding_source = note_str or plans_meta[-1]["funding_source"]
                            plans_meta[-1]["level1_subtotals"].append(
                                {
                                    "page": page,
                                    "code": use_code,
                                    "name": use_name,
                                    "subtotal_元": amt_val if amt_val is not None else 0,
                                    "funding_source": current_funding_source,
                                }
                            )
                        else:
                            current_use_code = use_code
                            current_use_name = use_name
                            current_use_item_seq = 0
                            plans_meta[-1]["level2_subtotals"].append(
                                {
                                    "page_start": page,
                                    "page_end": page,
                                    "用途別_code": use_code,
                                    "用途別": use_name,
                                    "subtotal_元": amt_val if amt_val is not None else 0,
                                    "經費來源": current_funding_source,
                                }
                            )
                        continue

                    # Summary-like row without valid subject (e.g. missing unit/qty/unit_price on detail row)
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "unit/qty/unit_price",
                            "raw_value": f"subj={subj_str!r}, amount_元={amt_str!r}, 說明={note_str!r}",
                        }
                    )
                    continue

                # Detail item row
                if not current_use_code:
                    # Wait: what if a detail row appears before a level-2 subtotal row was seen
                    # (e.g. if the level-2 subtotal row was missing or merged)?
                    m_use_inline = re.match(r"^(\d{4})\s*(.+)$", subj_str)
                    if m_use_inline and not m_use_inline.group(1).endswith("00"):
                        current_use_code = m_use_inline.group(1)
                        current_use_name = re.sub(r"\s+", "", m_use_inline.group(2).strip())
                        current_use_item_seq = 0
                        plans_meta[-1]["level2_subtotals"].append(
                            {
                                "page_start": page,
                                "page_end": page,
                                "用途別_code": current_use_code,
                                "用途別": current_use_name,
                                "subtotal_元": 0,
                                "經費來源": current_funding_source,
                            }
                        )
                    else:
                        unregistered_anomalies.append(
                            {
                                "page": page,
                                "source_table": toc_key,
                                "locator": locator,
                                "field": "用途別科目",
                                "raw_value": subj_str,
                            }
                        )

                if plans_meta[-1]["level2_subtotals"]:
                    plans_meta[-1]["level2_subtotals"][-1]["page_end"] = page

                current_use_item_seq += 1
                u_price, ok_price = parse_single_amount(price_str, allow_empty=False)
                amt_val, ok_amt = parse_single_amount(amt_str, allow_empty=False)
                qty_val, ok_qty = eval_qty_value(qty_str)

                if not ok_price or u_price is None:
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "unit_price",
                            "raw_value": price_str,
                        }
                    )
                if not ok_amt or amt_val is None:
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "amount_元",
                            "raw_value": amt_str,
                        }
                    )
                if not ok_qty or qty_val is None:
                    unregistered_anomalies.append(
                        {
                            "page": page,
                            "source_table": toc_key,
                            "locator": locator,
                            "field": "qty",
                            "raw_value": qty_str,
                        }
                    )

                if (
                    ok_price
                    and ok_amt
                    and ok_qty
                    and u_price is not None
                    and amt_val is not None
                    and qty_val is not None
                ):
                    expected_amt = round(qty_val * u_price)
                    if expected_amt != amt_val:
                        unregistered_anomalies.append(
                            {
                                "page": page,
                                "source_table": toc_key,
                                "locator": locator,
                                "field": "amount_元(單價×數量不符)",
                                "raw_value": f"qty={qty_str}, unit_price={price_str}, amount_元={amt_str}",
                            }
                        )

                expenditure_items.append(
                    {
                        "year": year,
                        "page": page,
                        "plan_code": current_plan_code,
                        "用途別_code": current_use_code,
                        "用途別": current_use_name,
                        "unit": unit_str,
                        "qty": qty_str,
                        "unit_price": str(u_price) if u_price is not None else price_str,
                        "amount_元": str(amt_val) if amt_val is not None else amt_str,
                        "說明": note_str,
                        "經費來源": current_funding_source,
                        "item_seq": current_use_item_seq,
                    }
                )

    # Check _known_diff at plan level or (plan_code, 用途別_code) level if any
    for p_meta in plans_meta:
        p_code = p_meta["plan_code"]
        plan_diff_key = (p_meta["page_start"], p_code, "_known_diff")
        if plan_diff_key in corrections:
            corr = corrections[plan_diff_key]
            actual_sum = sum(
                int(it["amount_元"])
                for it in expenditure_items
                if it["plan_code"] == p_code and parse_single_amount(it["amount_元"])[1]
            )
            actual_diff = actual_sum - p_meta["header_budget_元"]
            reg_diff, ok_reg = parse_single_amount(corr["old"], allow_empty=False)
            if ok_reg and reg_diff == actual_diff and corr["new"] == "UNRESOLVED":
                applied_corrections.append(corr)

        for l2 in p_meta["level2_subtotals"]:
            u_code = l2["用途別_code"]
            u_loc = f"{p_code}:{u_code}"
            u_diff_key = (l2["page_start"], u_loc, "_known_diff")
            if u_diff_key in corrections:
                corr = corrections[u_diff_key]
                actual_u_sum = sum(
                    int(it["amount_元"])
                    for it in expenditure_items
                    if it["plan_code"] == p_code
                    and it["用途別_code"] == u_code
                    and parse_single_amount(it["amount_元"])[1]
                )
                actual_u_diff = actual_u_sum - l2["subtotal_元"]
                reg_diff, ok_reg = parse_single_amount(corr["old"], allow_empty=False)
                if ok_reg and reg_diff == actual_u_diff and corr["new"] == "UNRESOLVED":
                    applied_corrections.append(corr)

    return (
        plans_rows,
        expenditure_items,
        plans_meta,
        unregistered_anomalies,
        applied_corrections,
        header_count,
    )


REFERENCE_TABLES_FIELDNAMES = [
    "year",
    "source_book",
    "source_table",
    "page",
    "table_seq",
    "row_idx",
    "col_idx",
    "rowspan",
    "colspan",
    "text",
    "value_num",
]

REFERENCE_VALUE_RE = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$")


REFERENCE_LOCATOR_PREFIX = "ref:"


def reference_cell_locator(row_idx: int, col_idx: int) -> str:
    """Locator used in corrections.csv for one reference-table cell (field is always 'text')."""
    return f"{REFERENCE_LOCATOR_PREFIX}r{row_idx}c{col_idx}"


def has_reference_corrections(corrections: dict[tuple[int, str, str], dict[str, str]]) -> bool:
    """True when corrections.csv registers any correction for reference-table cells."""
    return any(loc.startswith(REFERENCE_LOCATOR_PREFIX) for (_, loc, _) in corrections)


def parse_part3_reference_tables(
    part3_text: str,
    year: str,
    toc: dict[str, tuple[int, int]],
    partial: bool = False,
    corrections: dict[tuple[int, str, str], dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the reference tables that follow the expenditure detail tables in part3 (通用長格式，一格一列).

    回傳 (rows, applied_corrections)。corrections.csv 可用 page + locator `ref:r{row_idx}c{col_idx}`
    + field `text` 修正單一儲存格；僅在儲存格原文與 old 逐字相同時套用，套用後才判定 value_num。

    假設：「歲出計畫說明提要與各項費用明細表」之後，part3 依序為目次中起始頁大於該章節結束頁的
    各參考表（三、各機關歲出一級用途別科目分析總表 … 十二、歲出按職能及經濟性綜合分類表），
    且每頁恰好一張 <table>。表數 != 頁數時 raise ValueError，不靜默輸出。
    不修正 OCR 內容；text 只移除 HTML 標籤並正規化空白，value_num 僅在整格為單一數字時填入。
    """
    toc_key = "歲出計畫說明提要與各項費用明細表"
    if toc_key not in toc:
        raise ValueError(f"目次中找不到章節：{toc_key}")
    exp_start, exp_end = toc[toc_key]
    expected_exp_pages = exp_end - exp_start + 1

    # 後續章節（依頁序，同頁範圍只留第一個標題＝parse_toc 的完整 title）
    sections: list[tuple[str, int, int]] = []
    seen_ranges: set[tuple[int, int]] = set()
    for title, (s, e) in toc.items():
        if s > exp_end and (s, e) not in seen_ranges:
            seen_ranges.add((s, e))
            sections.append((title, s, e))
    sections.sort(key=lambda x: x[1])
    if not sections:
        raise ValueError(f"目次中找不到「{toc_key}」之後的參考表章節")
    total_pages = sum(e - s + 1 for _, s, e in sections)

    blocks = extract_tables_with_preceding_text(part3_text)
    exp_indices = [i for i, (pre, _) in enumerate(blocks) if "歲出計畫說明提要" in pre]
    if len(exp_indices) == expected_exp_pages:
        last_exp_idx = exp_indices[-1]
    elif partial:
        rev_start, rev_end = toc["歲入項目說明提要與預算明細表"]
        last_exp_idx = (rev_end - rev_start + 1) + expected_exp_pages - 1
    else:
        raise ValueError(
            f"章節「{toc_key}」表頭數 ({len(exp_indices)}) != 目錄頁數 ({expected_exp_pages})，無法定位參考表"
        )

    ref_tables = [t for _, t in blocks[last_exp_idx + 1 :]]
    if len(ref_tables) != total_pages:
        raise ValueError(
            f"參考表 <table> 數 ({len(ref_tables)}) != 目錄頁數 ({total_pages})，每頁一表假設不成立"
        )

    rows: list[dict[str, Any]] = []
    applied_corrections: list[dict[str, Any]] = []
    corrections = corrections or {}
    table_iter = iter(ref_tables)
    for title, s, e in sections:
        for page in range(s, e + 1):
            table_html = next(table_iter)
            parser = HTMLTableGridParser()
            parser.feed(table_html)
            occupied: set[tuple[int, int]] = set()
            for r_idx, row_cells in enumerate(parser.raw_rows):
                c_idx = 0
                for text, rowspan, colspan in row_cells:
                    while (r_idx, c_idx) in occupied:
                        c_idx += 1
                    for dr in range(rowspan):
                        for dc in range(colspan):
                            occupied.add((r_idx + dr, c_idx + dc))
                    corr = corrections.get((page, reference_cell_locator(r_idx, c_idx), "text"))
                    if corr is not None and text == corr["old"]:
                        text = corr["new"]
                        applied_corrections.append(corr)
                    value_num = ""
                    if REFERENCE_VALUE_RE.match(text):
                        value_num = text.replace(",", "")
                    rows.append(
                        {
                            "year": year,
                            "source_book": "part3",
                            "source_table": title,
                            "page": page,
                            "table_seq": 1,
                            "row_idx": r_idx,
                            "col_idx": c_idx,
                            "rowspan": rowspan,
                            "colspan": colspan,
                            "text": text,
                            "value_num": value_num,
                        }
                    )
                    c_idx += colspan
    return rows, applied_corrections


def parse_book(
    year: str,
    root_dir: Path = ROOT_DIR,
    partial: bool = False,
    reference_tables: bool = False,
) -> dict[str, Any]:
    """Parse part1 summary tables and part3 revenue & expenditure items for the given year and write CSVs."""
    raw_dir = root_dir / "raw" / str(year)
    part1_path = raw_dir / "part1.md"
    part3_path = raw_dir / "part3.md"
    corrections_path = root_dir / "data" / "corrections.csv"

    if not part1_path.exists():
        raise FileNotFoundError(f"找不到檔案：{part1_path}")
    if not part3_path.exists():
        raise FileNotFoundError(f"找不到檔案：{part3_path}")

    part1_text = part1_path.read_text(encoding="utf-8")
    part3_text = part3_path.read_text(encoding="utf-8")

    toc = load_toc(raw_dir, part1_text)
    corrections = load_corrections(corrections_path, str(year))

    summary_rows, sum_anomalies, sum_applied, part1_section_checks = parse_part1_summary(
        part1_text, str(year), toc, corrections, partial=partial
    )
    rev_items, rev_headers, rev_anomalies, rev_applied, rev_header_count = parse_part3_revenue(
        part3_text, str(year), toc, corrections, partial=partial
    )
    (
        plans_rows,
        exp_items,
        plans_meta,
        exp_anomalies,
        exp_applied,
        exp_header_count,
    ) = parse_part3_expenditure(part3_text, str(year), toc, corrections, partial=partial)

    # 參考表只有在帶 --reference-tables 或 corrections.csv 登記了參考表修正時才解析，
    # 後者是為了讓「已登記但未套用」的判定涵蓋參考表儲存格；CSV 仍只在帶旗標時才寫出。
    ref_rows: list[dict[str, Any]] = []
    ref_applied: list[dict[str, Any]] = []
    if reference_tables or has_reference_corrections(corrections):
        ref_rows, ref_applied = parse_part3_reference_tables(
            part3_text, str(year), toc, partial=partial, corrections=corrections
        )

    all_applied = sum_applied + rev_applied + exp_applied + ref_applied
    unapplied_corrections = find_unapplied_corrections(corrections, all_applied)

    out_dir = root_dir / "data" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_csv_path = out_dir / "summary.csv"
    with summary_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(summary_rows)

    revenue_csv_path = out_dir / "revenue_items.csv"
    with revenue_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVENUE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rev_items)

    plans_csv_path = out_dir / "plans.csv"
    with plans_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLANS_FIELDNAMES)
        writer.writeheader()
        writer.writerows(plans_rows)

    expenditure_csv_path = out_dir / "expenditure_items.csv"
    with expenditure_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPENDITURE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(exp_items)

    if reference_tables:
        ref_csv_path = out_dir / "reference_tables.csv"
        with ref_csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REFERENCE_TABLES_FIELDNAMES)
            writer.writeheader()
            writer.writerows(ref_rows)

    return {
        "reference_table_rows": ref_rows,
        "year": str(year),
        "toc": toc,
        "part1_section_checks": part1_section_checks,
        "summary_rows": summary_rows,
        "revenue_items": rev_items,
        "revenue_headers": rev_headers,
        "revenue_header_count": rev_header_count,
        "plans_rows": plans_rows,
        "expenditure_items": exp_items,
        "plans_meta": plans_meta,
        "expenditure_header_count": exp_header_count,
        "unregistered_anomalies": sum_anomalies + rev_anomalies + exp_anomalies,
        "applied_corrections": all_applied,
        "unapplied_corrections": unapplied_corrections,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    partial = "--partial" in args
    reference_tables = "--reference-tables" in args
    args = [a for a in args if a not in ("--partial", "--reference-tables")]
    if len(args) != 1:
        print("用法: python3 scripts/parse_book.py <年度> [--partial] [--reference-tables]", file=sys.stderr)
        return 1
    year = args[0]
    result = parse_book(year, partial=partial, reference_tables=reference_tables)
    print(
        f"[{year}年度] 解析完成：summary.csv {len(result['summary_rows'])} 筆、"
        f"revenue_items.csv {len(result['revenue_items'])} 筆（{len(result['revenue_headers'])} 個細目，"
        f"歲入明細表頭數 {result['revenue_header_count']} 頁）、"
        f"plans.csv {len(result['plans_rows'])} 筆、"
        f"expenditure_items.csv {len(result['expenditure_items'])} 筆（歲出明細表頭數 {result['expenditure_header_count']} 頁）、"
        f"套用修正 {len(result['applied_corrections'])} 筆、"
        f"未套用修正 {len(result['unapplied_corrections'])} 筆、"
        f"未登記數字異常 {len(result['unregistered_anomalies'])} 筆。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
