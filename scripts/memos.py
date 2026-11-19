#!/usr/bin/env python3
"""Shared helpers for loading, locating, and validating data/memos.csv and data/pdf_sources.csv."""

from __future__ import annotations

import csv
import datetime
import re
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent

VALID_SCOPES = frozenset(
    {
        "revenue_item",
        "expenditure_item",
        "plan",
        "summary",
        "reference_cell",
        "page",
    }
)

VALID_TYPES = frozenset(
    {
        "print_typo",
        "print_inconsistent",
        "print_layout",
        "data_gap",
    }
)

VALID_STATUSES = frozenset(
    {
        "confirmed",
        "pending_publisher",
    }
)

MEMO_COLUMNS = (
    "memo_id",
    "year",
    "scope",
    "page",
    "locator",
    "field",
    "type",
    "printed_text",
    "data_text",
    "suggested_text",
    "note",
    "pdf_file",
    "pdf_page",
    "verified_method",
    "verified_on",
    "evidence",
    "status",
)

PDF_SOURCE_COLUMNS = (
    "year",
    "pdf_file",
    "book_page_from",
    "book_page_to",
    "pdf_page_offset",
    "note",
)

_REF_CELL_RE = re.compile(r"^r(\d+)c(\d+)$")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_pdf_sources(root_dir: Path = ROOT_DIR) -> list[dict[str, str]]:
    """Load data/pdf_sources.csv rows."""
    return _read_csv_rows(root_dir / "data" / "pdf_sources.csv")


def load_memos(
    root_dir: Path = ROOT_DIR,
    memos_path: Path | None = None,
) -> list[dict[str, str]]:
    """Load data/memos.csv rows."""
    return _read_csv_rows(memos_path if memos_path is not None else root_dir / "data" / "memos.csv")


def check_memos_csv_integrity(
    root_dir: Path = ROOT_DIR,
    memos_path: Path | None = None,
) -> list[str]:
    """Check that memos.csv has all required columns and matching column counts per row."""
    path = memos_path if memos_path is not None else root_dir / "data" / "memos.csv"
    if not path.is_file():
        return []
    errors: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return ["data/memos.csv 為空檔案，缺少表頭"]
        missing = [col for col in MEMO_COLUMNS if col not in header]
        if missing:
            errors.append(f"data/memos.csv 缺少必要欄位：{', '.join(missing)}")
        expected_len = len(header)
        for line_no, row in enumerate(reader, start=2):
            if len(row) != expected_len:
                errors.append(
                    f"data/memos.csv 第 {line_no} 列欄位數不符（表頭 {expected_len} 欄，實際 {len(row)} 欄）"
                )
    return errors


def validate_memos_global(root_dir: Path = ROOT_DIR) -> list[str]:
    """Cross-year checks on data/memos.csv: schema integrity and valid data/<year>/ directories."""
    errors = check_memos_csv_integrity(root_dir=root_dir)
    if errors:
        return errors

    data_dir = root_dir / "data"
    valid_years: set[str] = set()
    if data_dir.is_dir():
        for child in data_dir.iterdir():
            if child.is_dir() and child.name.isdigit():
                valid_years.add(child.name)

    for idx, m in enumerate(load_memos(root_dir=root_dir), start=2):
        y = (m.get("year") or "").strip()
        mid = (m.get("memo_id") or "").strip() or f"第 {idx} 列"
        if not y or not y.isdigit() or y not in valid_years:
            errors.append(f"備註 {mid} 的 year={y!r} 無對應資料年度目錄（data/{y}/ 不存在）")
    return errors


def find_pdf_source(
    pdf_sources: list[dict[str, str]],
    year: str,
    pdf_file: str,
    book_page: int,
) -> dict[str, str] | None:
    """Return the matching pdf_sources row for (year, pdf_file, book_page), or None."""
    year_str = str(year)
    for src in pdf_sources:
        if src.get("year") != year_str or src.get("pdf_file") != pdf_file:
            continue
        try:
            p_from = int(src["book_page_from"])
            p_to = int(src["book_page_to"])
        except (KeyError, ValueError):
            continue
        if p_from <= book_page <= p_to:
            return src
    return None


def load_year_tables(year: str, root_dir: Path = ROOT_DIR) -> dict[str, list[dict[str, str]]]:
    """Load all normalized CSV tables for a given year."""
    year_dir = root_dir / "data" / str(year)
    return {
        "revenue_items": _read_csv_rows(year_dir / "revenue_items.csv"),
        "expenditure_items": _read_csv_rows(year_dir / "expenditure_items.csv"),
        "plans": _read_csv_rows(year_dir / "plans.csv"),
        "summary": _read_csv_rows(year_dir / "summary.csv"),
        "reference_tables": _read_csv_rows(year_dir / "reference_tables.csv"),
    }


def _page_exists_in_year(page: int, year_tables: dict[str, list[dict[str, str]]]) -> bool:
    """Return True if any table in year_tables covers the given book page."""
    page_str = str(page)
    for key in ("revenue_items", "expenditure_items", "summary", "reference_tables"):
        if any(row.get("page") == page_str for row in year_tables.get(key, [])):
            return True
    for row in year_tables.get("plans", []):
        try:
            if int(row["page_start"]) <= page <= int(row["page_end"]):
                return True
        except (KeyError, ValueError):
            continue
    return False


def locate_memo_rows(
    memo: dict[str, str],
    year_tables: dict[str, list[dict[str, str]]],
) -> tuple[list[dict[str, str]], str | None]:
    """Locate matching CSV row(s) for a memo based on its scope, locator, and page.

    Returns (matched_rows, error_message). For scope='page', returns ([], None) on success.
    """
    scope = memo.get("scope", "")
    locator = memo.get("locator", "")
    try:
        page = int(memo.get("page", ""))
    except ValueError:
        return [], f"page 非合法整數：{memo.get('page', '')!r}"

    if scope == "page":
        if locator != "":
            return [], f"scope=page 時 locator 必須為空字串，實際為 {locator!r}"
        if not _page_exists_in_year(page, year_tables):
            return [], f"年度資料中找不到頁碼 p{page}"
        return [], None

    if scope == "revenue_item":
        parts = locator.split(":")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return [], f"revenue_item locator 格式錯誤：{locator!r}（應為 <細目編號>:<item_seq>）"
        code, item_seq = parts
        rows = [
            r
            for r in year_tables.get("revenue_items", [])
            if r.get("code") == code and r.get("item_seq") == item_seq
        ]
        return rows, None

    if scope == "expenditure_item":
        parts = locator.split(":")
        if len(parts) != 3 or not all(parts):
            return [], f"expenditure_item locator 格式錯誤：{locator!r}（應為 <計畫編號>:<用途別代碼>:<item_seq>）"
        plan_code, use_code, item_seq = parts
        rows = [
            r
            for r in year_tables.get("expenditure_items", [])
            if r.get("plan_code") == plan_code
            and r.get("用途別_code") == use_code
            and r.get("item_seq") == item_seq
        ]
        return rows, None

    if scope == "plan":
        if not locator:
            return [], "plan locator 不可為空"
        rows = [
            r for r in year_tables.get("plans", []) if r.get("plan_code") == locator
        ]
        return rows, None

    if scope == "summary":
        parts = locator.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return [], f"summary locator 格式錯誤：{locator!r}（應為 <source_table>:<科目名稱>）"
        source_table, subject = parts
        rows = [
            r
            for r in year_tables.get("summary", [])
            if r.get("source_table") == source_table and r.get("科目名稱") == subject
        ]
        return rows, None

    if scope == "reference_cell":
        m = _REF_CELL_RE.match(locator)
        if not m:
            return [], f"reference_cell locator 格式錯誤：{locator!r}（應為 r<列>c<欄>）"
        row_idx, col_idx = m.group(1), m.group(2)
        page_str = str(page)
        rows = [
            r
            for r in year_tables.get("reference_tables", [])
            if r.get("page") == page_str
            and r.get("row_idx") == row_idx
            and r.get("col_idx") == col_idx
        ]
        return rows, None

    return [], f"不支援的 scope：{scope!r}"


def _row_matches_page(scope: str, row: dict[str, str], page: int) -> bool:
    if scope == "plan":
        try:
            return int(row["page_start"]) <= page <= int(row["page_end"])
        except (KeyError, ValueError):
            return False
    try:
        return int(row.get("page", "")) == page
    except ValueError:
        return False


def validate_memos(year: str, root_dir: Path = ROOT_DIR) -> dict[str, Any]:
    """Validate all memos for `year` against rules V1-V7."""
    year_str = str(year)
    all_memos = load_memos(root_dir)
    pdf_sources = load_pdf_sources(root_dir)

    id_counts: dict[str, int] = {}
    for m in all_memos:
        mid = m.get("memo_id", "")
        id_counts[mid] = id_counts.get(mid, 0) + 1

    year_memos = [m for m in all_memos if m.get("year") == year_str]
    if not year_memos:
        return {
            "year": year_str,
            "memos": [],
            "results": [],
            "passed_count": 0,
            "failed_count": 0,
        }

    year_tables = load_year_tables(year_str, root_dir)
    results: list[dict[str, Any]] = []

    for m in year_memos:
        errors: list[str] = []
        memo_id = (m.get("memo_id") or "").strip()
        scope = (m.get("scope") or "").strip()
        page_raw = (m.get("page") or "").strip()
        locator = m.get("locator") or ""
        field = (m.get("field") or "").strip()
        m_type = (m.get("type") or "").strip()
        printed_text = m.get("printed_text") or ""
        data_text = m.get("data_text") or ""
        suggested_text = m.get("suggested_text") or ""
        note = (m.get("note") or "").strip()
        pdf_file = (m.get("pdf_file") or "").strip()
        pdf_page_raw = (m.get("pdf_page") or "").strip()
        verified_method = (m.get("verified_method") or "").strip()
        verified_on = (m.get("verified_on") or "").strip()
        evidence = (m.get("evidence") or "").strip()
        status = (m.get("status") or "").strip()

        # V1: 欄位與列舉值合法、memo_id 唯一
        if not memo_id:
            errors.append("V1: memo_id 不可為空")
        elif id_counts.get(memo_id, 0) > 1:
            errors.append(f"V1: memo_id 重複：{memo_id}")
        if scope not in VALID_SCOPES:
            errors.append(f"V1: scope 不合法：{scope!r}")
        if m_type not in VALID_TYPES:
            errors.append(f"V1: type 不合法：{m_type!r}")
        if status not in VALID_STATUSES:
            errors.append(f"V1: status 不合法：{status!r}")
        if not note:
            errors.append("V1: note 不可為空")
        if not verified_method:
            errors.append("V1: verified_method 不可為空")
        if scope != "page" and not field:
            errors.append("V1: field 不可為空（scope=page 除外）")

        page_int: int | None = None
        try:
            page_int = int(page_raw)
            if page_int <= 0:
                errors.append(f"V1: page 必須為正整數：{page_raw!r}")
                page_int = None
        except ValueError:
            errors.append(f"V1: page 非合法整數：{page_raw!r}")

        # V2 & V3: locator 恰好定位一列、頁碼一致、data_text 逐字相等
        if scope in VALID_SCOPES and page_int is not None:
            matched, loc_err = locate_memo_rows(m, year_tables)
            if loc_err:
                errors.append(f"V2: {loc_err}")
            elif scope != "page":
                if len(matched) != 1:
                    errors.append(
                        f"V2: locator {locator!r}（scope={scope}）應恰好定位 1 列，實際為 {len(matched)} 列"
                    )
                else:
                    row = matched[0]
                    if not _row_matches_page(scope, row, page_int):
                        actual_p = (
                            f"{row.get('page_start')}–{row.get('page_end')}"
                            if scope == "plan"
                            else row.get("page")
                        )
                        errors.append(f"V2: page={page_int} 與資料列頁碼（{actual_p}）不符")
                    if data_text != "":
                        if field not in row:
                            errors.append(f"V3: 資料列無欄位 {field!r}")
                        elif row[field] != data_text:
                            errors.append(
                                f"V3: data_text 與資料列 {field!r} 不符（備註={data_text!r}，資料={row[field]!r}）"
                            )
            else:
                if data_text != "":
                    errors.append("V3: scope=page 時 data_text 應為空")

        # V4: print_typo 必須有 printed_text、suggested_text 且兩者不同
        if m_type == "print_typo":
            if not printed_text or not suggested_text:
                errors.append("V4: print_typo 必須同時填寫 printed_text 與 suggested_text")
            elif printed_text == suggested_text:
                errors.append("V4: print_typo 的 printed_text 與 suggested_text 不可相同")

        # V5: pdf_file 必須在 pdf_sources.csv 內，且 pdf_page 與 page 依對照表一致
        if not pdf_file:
            errors.append("V5: pdf_file 不可為空")
        else:
            try:
                pdf_page_int = int(pdf_page_raw)
            except ValueError:
                errors.append(f"V5: pdf_page 非合法整數：{pdf_page_raw!r}")
                pdf_page_int = None

            if page_int is not None and pdf_page_int is not None:
                src = find_pdf_source(pdf_sources, year_str, pdf_file, page_int)
                if src is None:
                    errors.append(
                        f"V5: pdf_sources.csv 找不到 {year_str} 年 {pdf_file!r} 涵蓋 p{page_int} 的區段"
                    )
                else:
                    expected_pdf_page = page_int + int(src["pdf_page_offset"])
                    if pdf_page_int != expected_pdf_page:
                        errors.append(
                            f"V5: pdf_page={pdf_page_int} 與對照表推算（{page_int} + {src['pdf_page_offset']} = {expected_pdf_page}）不符"
                        )

        # V6: evidence 若有值，必須為 docs/evidence/ 相對路徑、不含 ..、且檔案必須存在
        if evidence:
            norm_ev = evidence.replace("\\", "/")
            if Path(evidence).is_absolute() or norm_ev.startswith("/"):
                errors.append(f"V6: evidence 不可為絕對路徑：{evidence}")
            elif ".." in norm_ev.split("/"):
                errors.append(f"V6: evidence 路徑不可含 '..'：{evidence}")
            elif not norm_ev.startswith("docs/evidence/"):
                errors.append(f"V6: evidence 路徑必須以 'docs/evidence/' 開頭：{evidence}")
            elif not (root_dir / evidence).is_file():
                errors.append(f"V6: evidence 檔案不存在：{evidence}")

        # V7: verified_on 為合法 YYYY-MM-DD 日期
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", verified_on):
            errors.append(f"V7: verified_on 格式不符 YYYY-MM-DD：{verified_on!r}")
        else:
            try:
                datetime.date.fromisoformat(verified_on)
            except ValueError:
                errors.append(f"V7: verified_on 非合法日期：{verified_on!r}")

        results.append(
            {
                "memo_id": memo_id,
                "scope": scope,
                "page": page_raw,
                "locator": locator,
                "type": m_type,
                "status": status,
                "passed": len(errors) == 0,
                "errors": errors,
            }
        )

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = len(results) - passed_count
    return {
        "year": year_str,
        "memos": year_memos,
        "results": results,
        "passed_count": passed_count,
        "failed_count": failed_count,
    }
