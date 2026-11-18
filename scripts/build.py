#!/usr/bin/env python3
"""將正規化預算 CSV 建置為 SQLite 資料庫與靜態網站 JSON (Slice S3: build.py)。

單位確認與說明：
- 經核對 `data/116/summary.csv`，各總表金額欄位（`本年度`、`上年度`、`前年度決算`）在 S1 `parse_book.py`
  匯出時已統一換算為「元」（例如歲入合計為 `312678000` 元、歲出合計為 `321081000` 元），
  並非千元，因此本腳本讀取 `summary.csv` 時直接轉為整數「元」，**不再 ×1000**。
- `revenue_items.csv`、`plans.csv`、`expenditure_items.csv` 之金額欄位亦皆為整數「元」。

未解決資料問題旗標 (`unresolved`)：
- 從 `data/corrections.csv` 讀取 `field == "_known_diff"` 且 `new == "UNRESOLVED"` 的列（old 為實際差額，
  例如某細目明細加總與表頭的差額），不寫死於程式碼中。
- 在 SQLite (`revenue_items`、`plans`、`expenditure_items`) 與 JSON (`site/data/<年度>.json`、`search.json`)
  對應項目帶上 `unresolved`、`unresolved_diff_元`（JSON 亦提供 `diff_元`）與 `note` / `unresolved_note`。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent


def _parse_int(val: str | None, allow_empty: bool = False) -> int | None:
    s = (val or "").strip()
    if not s:
        if allow_empty:
            return None
        raise ValueError("Expected integer value, got empty string")
    return int(s.replace(",", ""))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_known_diffs(data_dir: Path) -> dict[tuple[int, str], dict[str, Any]]:
    """讀取 `data/corrections.csv` 中的 `_known_diff` 列，回傳 `(year, locator) -> info` 字典。"""
    corr_path = data_dir / "corrections.csv"
    result: dict[tuple[int, str], dict[str, Any]] = {}
    for row in _read_csv(corr_path):
        field = (row.get("field") or "").strip()
        if field != "_known_diff":
            continue
        status = (row.get("new") or "").strip()
        if status != "UNRESOLVED":
            continue
        year = int((row.get("year") or "0").strip())
        page = int((row.get("page") or "0").strip())
        locator = (row.get("locator") or "").strip()
        diff_yuan = _parse_int(row.get("old"), allow_empty=False)
        reason = (row.get("reason") or "").strip()
        result[(year, locator)] = {
            "year": year,
            "page": page,
            "locator": locator,
            "diff_元": diff_yuan if diff_yuan is not None else 0,
            "status": status,
            "note": reason,
        }
    return result


# 暫時不納入建置的年度，資料驗證通過後再移除（見 docs/TODO.md）。
# 目前沒有需要跳過的年度；114 已於資料驗證通過後納入（T5）。機制保留，供日後資料不完整的年度使用。
SKIPPED_YEARS: frozenset[int] = frozenset()


def discover_years(data_dir: Path) -> list[int]:
    """掃描 `data_dir` 下所有數字命名、且已有 summary.csv 的年度子目錄（排除 SKIPPED_YEARS），依年度升冪排序。"""
    if not data_dir.exists():
        return []
    years: list[int] = []
    for child in data_dir.iterdir():
        if child.is_dir() and child.name.isdigit() and int(child.name) not in SKIPPED_YEARS:
            if (child / "summary.csv").exists():
                years.append(int(child.name))
    years.sort()
    return years


def _init_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA page_size = 4096;

        CREATE TABLE summary (
            year INTEGER NOT NULL,
            source_book TEXT NOT NULL,
            source_table TEXT NOT NULL,
            page INTEGER NOT NULL,
            款 TEXT NOT NULL,
            項 TEXT NOT NULL,
            科目名稱 TEXT NOT NULL,
            本年度 INTEGER,
            上年度 INTEGER,
            前年度決算 INTEGER
        );

        CREATE TABLE revenue_items (
            year INTEGER NOT NULL,
            page INTEGER NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            item_seq INTEGER NOT NULL,
            unit TEXT NOT NULL,
            qty TEXT NOT NULL,
            unit_price INTEGER NOT NULL,
            amount_元 INTEGER NOT NULL,
            note TEXT NOT NULL,
            dept TEXT NOT NULL,
            unresolved INTEGER NOT NULL DEFAULT 0,
            unresolved_diff_元 INTEGER,
            unresolved_note TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE plans (
            year INTEGER NOT NULL,
            page_start INTEGER NOT NULL,
            page_end INTEGER NOT NULL,
            plan_code TEXT NOT NULL,
            name TEXT NOT NULL,
            dept TEXT NOT NULL,
            政事別 TEXT NOT NULL,
            總額 INTEGER NOT NULL,
            unresolved INTEGER NOT NULL DEFAULT 0,
            unresolved_diff_元 INTEGER,
            unresolved_note TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE expenditure_items (
            year INTEGER NOT NULL,
            page INTEGER NOT NULL,
            plan_code TEXT NOT NULL,
            用途別_code TEXT NOT NULL,
            用途別 TEXT NOT NULL,
            unit TEXT NOT NULL,
            qty TEXT NOT NULL,
            unit_price INTEGER NOT NULL,
            amount_元 INTEGER NOT NULL,
            說明 TEXT NOT NULL,
            經費來源 TEXT NOT NULL,
            item_seq INTEGER NOT NULL,
            unresolved INTEGER NOT NULL DEFAULT 0,
            unresolved_diff_元 INTEGER,
            unresolved_note TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE crosswalk_codes (
            from_year INTEGER NOT NULL,
            from_code TEXT NOT NULL,
            to_year INTEGER NOT NULL,
            to_code TEXT NOT NULL,
            note TEXT NOT NULL
        );

        CREATE TABLE crosswalk_items (
            item_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            year INTEGER NOT NULL,
            scope_key TEXT NOT NULL,
            item_seq INTEGER NOT NULL
        );

        CREATE TABLE crosswalk_items_candidates (
            kind TEXT NOT NULL,
            scope_key TEXT NOT NULL,
            from_year INTEGER NOT NULL,
            from_item_seq INTEGER,
            to_year INTEGER NOT NULL,
            to_item_seq INTEGER,
            status TEXT NOT NULL,
            similarity REAL NOT NULL,
            from_text TEXT NOT NULL,
            to_text TEXT NOT NULL
        );

        CREATE INDEX idx_summary_year_table ON summary(year, source_table, 科目名稱);
        CREATE INDEX idx_summary_page ON summary(page);
        CREATE INDEX idx_revenue_items_year_code ON revenue_items(year, code);
        CREATE INDEX idx_revenue_items_page ON revenue_items(page);
        CREATE INDEX idx_plans_year_plan_code ON plans(year, plan_code);
        CREATE INDEX idx_plans_page ON plans(page_start, page_end);
        CREATE INDEX idx_expenditure_items_year_plan_code ON expenditure_items(year, plan_code);
        CREATE INDEX idx_expenditure_items_page ON expenditure_items(page);
        """
    )


def _build_year_data(
    year: int,
    year_dir: Path,
    known_diffs: dict[tuple[int, str], dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    """載入單一年度的 CSV 並建構 SQLite 資料列、年度 JSON 結構與搜尋索引文件。"""
    raw_summary = _read_csv(year_dir / "summary.csv")
    raw_revenue = _read_csv(year_dir / "revenue_items.csv")
    raw_plans = _read_csv(year_dir / "plans.csv")
    raw_expenditure = _read_csv(year_dir / "expenditure_items.csv")

    summary_rows: list[dict[str, Any]] = []
    for r in raw_summary:
        summary_rows.append(
            {
                "year": int(r["year"]),
                "source_book": r["source_book"].strip(),
                "source_table": r["source_table"].strip(),
                "page": int(r["page"]),
                "款": r["款"].strip(),
                "項": r["項"].strip(),
                "科目名稱": r["科目名稱"].strip(),
                "本年度": _parse_int(r["本年度"], allow_empty=True),
                "上年度": _parse_int(r["上年度"], allow_empty=True),
                "前年度決算": _parse_int(r["前年度決算"], allow_empty=True),
            }
        )

    revenue_rows: list[dict[str, Any]] = []
    for r in raw_revenue:
        y = int(r["year"])
        code = r["code"].strip()
        kd = known_diffs.get((y, code))
        revenue_rows.append(
            {
                "year": y,
                "page": int(r["page"]),
                "code": code,
                "name": r["name"].strip(),
                "item_seq": int(r["item_seq"]),
                "unit": r["unit"].strip(),
                "qty": r["qty"].strip(),
                "unit_price": _parse_int(r["unit_price"], allow_empty=False) or 0,
                "amount_元": _parse_int(r["amount_元"], allow_empty=False) or 0,
                "note": r["note"].strip(),
                "dept": r["dept"].strip(),
                "unresolved": 1 if kd else 0,
                "unresolved_diff_元": kd["diff_元"] if kd else None,
                "unresolved_note": kd["note"] if kd else "",
            }
        )
    revenue_rows.sort(key=lambda x: (x["page"], x["code"], x["item_seq"]))

    plans_rows: list[dict[str, Any]] = []
    for r in raw_plans:
        y = int(r["year"])
        p_code = r["plan_code"].strip()
        kd = known_diffs.get((y, p_code))
        plans_rows.append(
            {
                "year": y,
                "page_start": int(r["page_start"]),
                "page_end": int(r["page_end"]),
                "plan_code": p_code,
                "name": r["name"].strip(),
                "dept": r["dept"].strip(),
                "政事別": r["政事別"].strip(),
                "總額": _parse_int(r["總額"], allow_empty=False) or 0,
                "unresolved": 1 if kd else 0,
                "unresolved_diff_元": kd["diff_元"] if kd else None,
                "unresolved_note": kd["note"] if kd else "",
            }
        )
    plans_rows.sort(key=lambda x: (x["page_start"], x["plan_code"]))

    expenditure_rows: list[dict[str, Any]] = []
    for r in raw_expenditure:
        y = int(r["year"])
        p_code = r["plan_code"].strip()
        u_code = r["用途別_code"].strip()
        kd = known_diffs.get((y, f"{p_code}:{u_code}")) or known_diffs.get((y, p_code))
        expenditure_rows.append(
            {
                "year": y,
                "page": int(r["page"]),
                "plan_code": p_code,
                "用途別_code": u_code,
                "用途別": r["用途別"].strip(),
                "unit": r["unit"].strip(),
                "qty": r["qty"].strip(),
                "unit_price": _parse_int(r["unit_price"], allow_empty=False) or 0,
                "amount_元": _parse_int(r["amount_元"], allow_empty=False) or 0,
                "說明": r["說明"].strip(),
                "經費來源": r["經費來源"].strip(),
                "item_seq": int(r["item_seq"]),
                "unresolved": 1 if kd else 0,
                "unresolved_diff_元": kd["diff_元"] if kd else None,
                "unresolved_note": kd["note"] if kd else "",
            }
        )
    expenditure_rows.sort(
        key=lambda x: (x["page"], x["plan_code"], x["用途別_code"], x["item_seq"])
    )

    # ------------------------------------------------------------------
    # Build Revenue Hierarchy: 款 -> 項 -> 子目 -> 細目 (-> items 明細)
    # ------------------------------------------------------------------
    rev_items_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rev_code_order: list[str] = []
    for r in revenue_rows:
        c = r["code"]
        if c not in rev_items_by_code:
            rev_code_order.append(c)
        rev_items_by_code[c].append(r)

    fine_nodes_by_subname: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_unresolved_records: list[dict[str, Any]] = []
    total_rev_detail_sum = 0

    for c in rev_code_order:
        items = rev_items_by_code[c]
        first = items[0]
        full_name = first["name"]
        if "-" in full_name:
            sub_name, short_name = [p.strip() for p in full_name.split("-", 1)]
        else:
            sub_name, short_name = full_name, full_name

        detail_sum = sum(it["amount_元"] for it in items)
        total_rev_detail_sum += detail_sum
        kd = known_diffs.get((year, c))
        diff_yuan = kd["diff_元"] if kd else 0
        # detail_sum - header_budget = diff_yuan => header_budget = detail_sum - diff_yuan
        header_amount = detail_sum - diff_yuan
        p_start = min(it["page"] for it in items)
        p_end = max(it["page"] for it in items)
        is_unresolved = bool(kd)
        unresolved_note = kd["note"] if kd else ""

        item_objs = [
            {
                "item_seq": it["item_seq"],
                "page": it["page"],
                "code": it["code"],
                "name": it["name"],
                "unit": it["unit"],
                "qty": it["qty"],
                "unit_price": it["unit_price"],
                "amount_元": it["amount_元"],
                "note": it["note"],
                "dept": it["dept"],
                "unresolved": bool(it["unresolved"]),
            }
            for it in items
        ]

        fine_node: dict[str, Any] = {
            "level": "細目",
            "code": c,
            "name": full_name,
            "short_name": short_name,
            "sub_name": sub_name,
            "dept": first["dept"],
            "amount_元": header_amount,
            "detail_amount_元": detail_sum,
            "diff_元": diff_yuan,
            "page": p_start,
            "page_start": p_start,
            "page_end": p_end,
            "unresolved": is_unresolved,
            "note": unresolved_note,
            "unresolved_note": unresolved_note,
            "children": item_objs,
        }
        fine_nodes_by_subname[sub_name].append(fine_node)

        if is_unresolved:
            all_unresolved_records.append(
                {
                    "kind": "revenue",
                    "code": c,
                    "name": full_name,
                    "page": p_start,
                    "page_start": p_start,
                    "page_end": p_end,
                    "amount_元": header_amount,
                    "detail_amount_元": detail_sum,
                    "diff_元": diff_yuan,
                    "unresolved": True,
                    "note": unresolved_note,
                }
            )

    rev_summary_rows = [
        r for r in summary_rows if r["source_table"] == "歲入來源別預算總表"
    ]
    rev_comp_by_key: dict[tuple[str, str, str], dict[str, Any]] = {
        (r["款"], r["項"], r["科目名稱"]): r
        for r in summary_rows
        if r["source_table"] == "歲入來源別預算比較總表"
    }

    rev_total_row = next(
        (r for r in rev_summary_rows if r["科目名稱"] == "歲入合計"), None
    )
    rev_kuan_rows = [r for r in rev_summary_rows if r["款"] and not r["項"]]
    rev_hsiang_rows_by_kuan: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rev_summary_rows:
        if r["款"] and r["項"]:
            rev_hsiang_rows_by_kuan[r["款"]].append(r)

    rev_kuan_nodes: list[dict[str, Any]] = []
    for kr in rev_kuan_rows:
        kuan_code = kr["款"]
        kuan_name = kr["科目名稱"]
        kuan_amount = kr["本年度"] or 0
        comp_k = rev_comp_by_key.get((kuan_code, "", kuan_name), {})

        hsiang_nodes: list[dict[str, Any]] = []
        for hr in rev_hsiang_rows_by_kuan.get(kuan_code, []):
            hsiang_code = hr["項"]
            hsiang_name = hr["科目名稱"]
            hsiang_amount = hr["本年度"] or 0
            comp_h = rev_comp_by_key.get((kuan_code, hsiang_code, hsiang_name), {})

            fines = fine_nodes_by_subname.get(hsiang_name, [])
            if fines:
                sub_code = fines[0]["code"][:9] + "00"
                p_start = min(fn["page_start"] for fn in fines)
                p_end = max(fn["page_end"] for fn in fines)
                detail_amt = sum(fn["detail_amount_元"] for fn in fines)
                sub_amt = sum(fn["amount_元"] for fn in fines)
                sub_unresolved = any(fn["unresolved"] for fn in fines)
                sub_notes = [fn["note"] for fn in fines if fn["unresolved"] and fn["note"]]
            else:
                sub_code = f"{kuan_code}-{hsiang_code}"
                p_start = hr["page"]
                p_end = hr["page"]
                detail_amt = hsiang_amount
                sub_amt = hsiang_amount
                sub_unresolved = False
                sub_notes = []

            sub_node: dict[str, Any] = {
                "level": "子目",
                "code": sub_code,
                "name": hsiang_name,
                "amount_元": sub_amt,
                "detail_amount_元": detail_amt,
                "page": p_start,
                "page_start": p_start,
                "page_end": p_end,
                "unresolved": sub_unresolved,
                "note": "；".join(sub_notes),
                "children": fines,
            }

            hsiang_node: dict[str, Any] = {
                "level": "項",
                "code": f"{kuan_code}-{hsiang_code}",
                "款": kuan_code,
                "項": hsiang_code,
                "name": hsiang_name,
                "amount_元": hsiang_amount,
                "detail_amount_元": detail_amt,
                "上年度_元": comp_h.get("上年度"),
                "前年度決算_元": comp_h.get("前年度決算"),
                "summary_page": hr["page"],
                "page": p_start,
                "page_start": p_start,
                "page_end": p_end,
                "unresolved": sub_unresolved,
                "note": "；".join(sub_notes),
                "children": [sub_node],
            }
            hsiang_nodes.append(hsiang_node)

        if hsiang_nodes:
            k_p_start = min(hn["page_start"] for hn in hsiang_nodes)
            k_p_end = max(hn["page_end"] for hn in hsiang_nodes)
            k_detail_amt = sum(hn["detail_amount_元"] for hn in hsiang_nodes)
            k_unresolved = any(hn["unresolved"] for hn in hsiang_nodes)
            k_notes = [hn["note"] for hn in hsiang_nodes if hn["unresolved"] and hn["note"]]
        else:
            k_p_start = kr["page"]
            k_p_end = kr["page"]
            k_detail_amt = kuan_amount
            k_unresolved = False
            k_notes = []

        rev_kuan_nodes.append(
            {
                "level": "款",
                "code": kuan_code,
                "款": kuan_code,
                "name": kuan_name,
                "amount_元": kuan_amount,
                "detail_amount_元": k_detail_amt,
                "上年度_元": comp_k.get("上年度"),
                "前年度決算_元": comp_k.get("前年度決算"),
                "summary_page": kr["page"],
                "page": k_p_start,
                "page_start": k_p_start,
                "page_end": k_p_end,
                "unresolved": k_unresolved,
                "note": "；".join(k_notes),
                "children": hsiang_nodes,
            }
        )

    revenue_total_yuan = (
        rev_total_row["本年度"]
        if rev_total_row and rev_total_row["本年度"] is not None
        else sum(k["amount_元"] for k in rev_kuan_nodes)
    )
    revenue_summary_page = rev_total_row["page"] if rev_total_row else 4
    rev_min_page = min((r["page"] for r in revenue_rows), default=revenue_summary_page)
    rev_max_page = max((r["page"] for r in revenue_rows), default=revenue_summary_page)

    # ------------------------------------------------------------------
    # Build Expenditure Hierarchy: 政事別 -> 機關(dept) -> 工作計畫 -> 用途別 -> 明細
    # ------------------------------------------------------------------
    exp_items_by_plan: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in expenditure_rows:
        exp_items_by_plan[r["plan_code"]].append(r)

    plans_by_func: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in plans_rows:
        plans_by_func[p["政事別"]].append(p)

    exp_summary_rows = [
        r for r in summary_rows if r["source_table"] == "歲出政事別預算總表"
    ]
    exp_comp_by_name: dict[str, dict[str, Any]] = {
        r["科目名稱"]: r
        for r in summary_rows
        if r["source_table"] == "歲出政事別預算比較總表" and r["款"] and not r["項"]
    }
    exp_total_row = next(
        (r for r in exp_summary_rows if r["科目名稱"] == "歲出合計"), None
    )
    exp_kuan_rows = [r for r in exp_summary_rows if r["款"] and not r["項"]]

    exp_func_nodes: list[dict[str, Any]] = []
    for kr in exp_kuan_rows:
        kuan_code = kr["款"]
        func_name = kr["科目名稱"]
        func_amount = kr["本年度"] or 0
        comp_f = exp_comp_by_name.get(func_name, {})

        func_plans = plans_by_func.get(func_name, [])
        # Group by dept preserving appearance order in plans.csv
        dept_order: list[str] = []
        plans_by_dept: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in func_plans:
            d = p["dept"]
            if d not in plans_by_dept:
                dept_order.append(d)
            plans_by_dept[d].append(p)

        dept_nodes: list[dict[str, Any]] = []
        for dept_name in dept_order:
            d_plans = plans_by_dept[dept_name]
            plan_nodes: list[dict[str, Any]] = []
            for p in d_plans:
                p_code = p["plan_code"]
                p_items = exp_items_by_plan.get(p_code, [])

                # Group items by 用途別_code preserving first-seen order
                use_order: list[str] = []
                items_by_use: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for it in p_items:
                    u_code = it["用途別_code"]
                    if u_code not in items_by_use:
                        use_order.append(u_code)
                    items_by_use[u_code].append(it)

                use_nodes: list[dict[str, Any]] = []
                for u_code in use_order:
                    u_items = items_by_use[u_code]
                    first_u = u_items[0]
                    u_name = first_u["用途別"]
                    u_amt = sum(it["amount_元"] for it in u_items)
                    u_p_start = min(it["page"] for it in u_items)
                    u_p_end = max(it["page"] for it in u_items)
                    u_kd = known_diffs.get((year, f"{p_code}:{u_code}"))
                    u_unresolved = bool(u_kd)
                    u_note = u_kd["note"] if u_kd else ""

                    detail_nodes = [
                        {
                            "level": "明細",
                            "item_seq": it["item_seq"],
                            "page": it["page"],
                            "plan_code": it["plan_code"],
                            "用途別_code": it["用途別_code"],
                            "用途別": it["用途別"],
                            "unit": it["unit"],
                            "qty": it["qty"],
                            "unit_price": it["unit_price"],
                            "amount_元": it["amount_元"],
                            "說明": it["說明"],
                            "經費來源": it["經費來源"],
                            "unresolved": bool(it["unresolved"]),
                        }
                        for it in u_items
                    ]

                    use_nodes.append(
                        {
                            "level": "用途別",
                            "code": u_code,
                            "用途別_code": u_code,
                            "name": u_name,
                            "用途別": u_name,
                            "plan_code": p_code,
                            "amount_元": u_amt,
                            "page": u_p_start,
                            "page_start": u_p_start,
                            "page_end": u_p_end,
                            "經費來源": first_u["經費來源"],
                            "unresolved": u_unresolved,
                            "note": u_note,
                            "children": detail_nodes,
                        }
                    )

                p_detail_sum = sum(u["amount_元"] for u in use_nodes)
                p_kd = known_diffs.get((year, p_code))
                p_unresolved = bool(p_kd) or any(u["unresolved"] for u in use_nodes)
                p_note = p_kd["note"] if p_kd else ""

                plan_nodes.append(
                    {
                        "level": "工作計畫",
                        "code": p_code,
                        "plan_code": p_code,
                        "name": p["name"],
                        "dept": dept_name,
                        "政事別": func_name,
                        "amount_元": p["總額"],
                        "detail_amount_元": p_detail_sum,
                        "page": p["page_start"],
                        "page_start": p["page_start"],
                        "page_end": p["page_end"],
                        "unresolved": p_unresolved,
                        "note": p_note,
                        "children": use_nodes,
                    }
                )

            d_amt = sum(pn["amount_元"] for pn in plan_nodes)
            d_detail_amt = sum(pn["detail_amount_元"] for pn in plan_nodes)
            d_p_start = min(pn["page_start"] for pn in plan_nodes)
            d_p_end = max(pn["page_end"] for pn in plan_nodes)
            d_unresolved = any(pn["unresolved"] for pn in plan_nodes)

            dept_nodes.append(
                {
                    "level": "機關",
                    "dept": dept_name,
                    "name": dept_name,
                    "政事別": func_name,
                    "amount_元": d_amt,
                    "detail_amount_元": d_detail_amt,
                    "page": d_p_start,
                    "page_start": d_p_start,
                    "page_end": d_p_end,
                    "unresolved": d_unresolved,
                    "children": plan_nodes,
                }
            )

        if dept_nodes:
            f_p_start = min(dn["page_start"] for dn in dept_nodes)
            f_p_end = max(dn["page_end"] for dn in dept_nodes)
            f_detail_amt = sum(dn["detail_amount_元"] for dn in dept_nodes)
            f_unresolved = any(dn["unresolved"] for dn in dept_nodes)
        else:
            f_p_start = kr["page"]
            f_p_end = kr["page"]
            f_detail_amt = func_amount
            f_unresolved = False

        exp_func_nodes.append(
            {
                "level": "政事別",
                "code": kuan_code,
                "款": kuan_code,
                "name": func_name,
                "政事別": func_name,
                "amount_元": func_amount,
                "detail_amount_元": f_detail_amt,
                "上年度_元": comp_f.get("上年度"),
                "前年度決算_元": comp_f.get("前年度決算"),
                "summary_page": kr["page"],
                "page": f_p_start,
                "page_start": f_p_start,
                "page_end": f_p_end,
                "unresolved": f_unresolved,
                "children": dept_nodes,
            }
        )

    plans_total_yuan = sum(p["總額"] for p in plans_rows)
    expenditure_detail_sum_yuan = sum(r["amount_元"] for r in expenditure_rows)
    expenditure_total_yuan = (
        exp_total_row["本年度"]
        if exp_total_row and exp_total_row["本年度"] is not None
        else plans_total_yuan
    )
    expenditure_summary_page = exp_total_row["page"] if exp_total_row else 7
    exp_min_page = min((p["page_start"] for p in plans_rows), default=expenditure_summary_page)
    exp_max_page = max((p["page_end"] for p in plans_rows), default=expenditure_summary_page)

    # Overview current/capital accounts & balance
    nature_rows = {
        r["科目名稱"]: r
        for r in summary_rows
        if r["source_table"] == "歲入歲出性質及餘絀簡明比較分析表"
    }
    cashflow_rows = {
        r["科目名稱"]: r
        for r in summary_rows
        if r["source_table"] == "收支簡明比較分析表"
    }

    summary_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in summary_rows:
        summary_by_table[r["source_table"]].append(r)

    year_json: dict[str, Any] = {
        "year": year,
        "overview": {
            "revenue_total_元": revenue_total_yuan,
            "revenue_detail_sum_元": total_rev_detail_sum,
            "expenditure_total_元": expenditure_total_yuan,
            "expenditure_plan_sum_元": plans_total_yuan,
            "expenditure_detail_sum_元": expenditure_detail_sum_yuan,
            "balance_元": (nature_rows.get("歲入歲出餘絀") or {}).get("本年度"),
            "prior_surplus_used_元": (
                cashflow_rows.get("預計移用以前年度歲計賸餘調節因應數") or {}
            ).get("本年度"),
            "current_account": {
                "revenue_元": (nature_rows.get("經常門-歲入") or {}).get("本年度") or 0,
                "expenditure_元": (nature_rows.get("經常門-歲出") or {}).get("本年度") or 0,
                "surplus_元": (nature_rows.get("經常門-經常門賸餘") or {}).get("本年度") or 0,
                "page": (nature_rows.get("經常門-歲入") or {}).get("page") or 2,
            },
            "capital_account": {
                "revenue_元": (nature_rows.get("資本門-歲入") or {}).get("本年度") or 0,
                "expenditure_元": (nature_rows.get("資本門-歲出") or {}).get("本年度") or 0,
                "shortfall_元": (nature_rows.get("資本門-資本門差短") or {}).get("本年度") or 0,
                "page": (nature_rows.get("資本門-歲出") or {}).get("page") or 2,
            },
            "unresolved_items": all_unresolved_records,
        },
        "revenue": {
            "total_元": revenue_total_yuan,
            "detail_sum_元": total_rev_detail_sum,
            "page": revenue_summary_page,
            "page_start": rev_min_page,
            "page_end": rev_max_page,
            "hierarchy": rev_kuan_nodes,
        },
        "expenditure": {
            "total_元": expenditure_total_yuan,
            "plan_sum_元": plans_total_yuan,
            "detail_sum_元": expenditure_detail_sum_yuan,
            "page": expenditure_summary_page,
            "page_start": exp_min_page,
            "page_end": exp_max_page,
            "hierarchy": exp_func_nodes,
        },
        "summary_tables": dict(summary_by_table),
    }

    # ------------------------------------------------------------------
    # Build Search Index Documents for this year
    # ------------------------------------------------------------------
    search_docs: list[dict[str, Any]] = []

    for r in revenue_rows:
        search_docs.append(
            {
                "id": f"{year}-revenue-{r['code']}-{r['item_seq']}",
                "year": year,
                "kind": "revenue",
                "code": r["code"],
                "name": r["name"],
                "text": r["note"],
                "page": r["page"],
                "amount_元": r["amount_元"],
                "dept": r["dept"],
                "unresolved": bool(r["unresolved"]),
            }
        )

    plan_name_by_code = {p["plan_code"]: p["name"] for p in plans_rows}
    plan_dept_by_code = {p["plan_code"]: p["dept"] for p in plans_rows}
    for p in plans_rows:
        search_docs.append(
            {
                "id": f"{year}-plan-{p['plan_code']}",
                "year": year,
                "kind": "plan",
                "code": p["plan_code"],
                "name": p["name"],
                "text": f"{p['政事別']} {p['dept']} {p['name']}",
                "page": p["page_start"],
                "page_start": p["page_start"],
                "page_end": p["page_end"],
                "amount_元": p["總額"],
                "dept": p["dept"],
                "unresolved": bool(p["unresolved"]),
            }
        )

    for r in expenditure_rows:
        p_name = plan_name_by_code.get(r["plan_code"], "")
        p_dept = plan_dept_by_code.get(r["plan_code"], "")
        search_docs.append(
            {
                "id": f"{year}-expenditure-{r['plan_code']}-{r['用途別_code']}-{r['item_seq']}",
                "year": year,
                "kind": "expenditure",
                "code": r["plan_code"],
                "用途別_code": r["用途別_code"],
                "name": f"{p_name} - {r['用途別']}" if p_name else r["用途別"],
                "text": r["說明"],
                "page": r["page"],
                "amount_元": r["amount_元"],
                "dept": p_dept,
                "unresolved": bool(r["unresolved"]),
            }
        )

    for idx, r in enumerate(summary_rows, start=1):
        code_parts = [p for p in (r["款"], r["項"]) if p]
        code_str = "-".join(code_parts)
        search_docs.append(
            {
                "id": f"{year}-summary-{idx:04d}",
                "year": year,
                "kind": "summary",
                "code": code_str,
                "name": r["科目名稱"],
                "text": f"{r['source_table']} {r['科目名稱']}",
                "page": r["page"],
                "amount_元": r["本年度"],
                "dept": "",
                "unresolved": False,
            }
        )

    return (
        summary_rows,
        revenue_rows,
        plans_rows,
        expenditure_rows,
        year_json,
        search_docs,
    )


def _write_json_deterministic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
    path.write_text(content, encoding="utf-8")


def _collect_year_compare_items(
    year: int,
    revenue_rows: list[dict[str, Any]],
    year_json: dict[str, Any],
    known_diffs: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """擷取單一年度可供跨年度比較的項目（revenue 各層與所有細目、plan、object）。"""
    items: dict[str, dict[str, Any]] = {}
    hierarchy_fine_codes: set[str] = set()

    def walk_rev(nodes: list[dict[str, Any]], parent_key: str | None = None) -> None:
        for n in nodes:
            lvl = n["level"]
            code = n["code"]
            key = f"revenue:{code}"
            if lvl == "細目":
                hierarchy_fine_codes.add(code)
                continue
            ch_keys = [f"revenue:{ch['code']}" for ch in n.get("children", [])]
            items[key] = {
                "kind": "revenue",
                "level": lvl,
                "code": code,
                "name": n["name"],
                "amount_元": n["amount_元"],
                "page": n["page"],
                "page_start": n.get("page_start", n["page"]),
                "page_end": n.get("page_end", n["page"]),
                "unresolved": bool(n.get("unresolved", False)),
                "in_hierarchy": True,
                "children_keys": ch_keys,
                "parent_key": parent_key,
                "dept": n.get("dept", ""),
            }
            walk_rev(n.get("children", []), key)

    walk_rev(year_json["revenue"]["hierarchy"], None)

    # 細目取自 revenue_items.csv 的所有 code
    rev_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rev_code_order: list[str] = []
    for r in revenue_rows:
        c = r["code"]
        if c not in rev_by_code:
            rev_code_order.append(c)
        rev_by_code[c].append(r)

    # 記錄細目在 hierarchy 中的 parent_key
    fine_parent_by_code: dict[str, str] = {}
    for kuan in year_json["revenue"]["hierarchy"]:
        for hsiang in kuan.get("children", []):
            for sub in hsiang.get("children", []):
                sub_key = f"revenue:{sub['code']}"
                for fine in sub.get("children", []):
                    fine_parent_by_code[fine["code"]] = sub_key

    for c in rev_code_order:
        r_list = rev_by_code[c]
        first = r_list[0]
        detail_sum = sum(it["amount_元"] for it in r_list)
        kd = known_diffs.get((year, c))
        diff_yuan = kd["diff_元"] if kd else 0
        header_amount = detail_sum - diff_yuan
        p_start = min(it["page"] for it in r_list)
        p_end = max(it["page"] for it in r_list)
        key = f"revenue:{c}"
        items[key] = {
            "kind": "revenue",
            "level": "細目",
            "code": c,
            "name": first["name"],
            "amount_元": header_amount,
            "page": p_start,
            "page_start": p_start,
            "page_end": p_end,
            "unresolved": bool(kd),
            "in_hierarchy": c in hierarchy_fine_codes,
            "children_keys": [],
            "parent_key": fine_parent_by_code.get(c),
            "dept": first.get("dept", ""),
        }

    # 歲出：工作計畫 (plan) 與 用途別 (object)
    for func_node in year_json["expenditure"]["hierarchy"]:
        func_name = func_node["name"]
        for dept_node in func_node.get("children", []):
            dept_name = dept_node["name"]
            for plan_node in dept_node.get("children", []):
                p_code = plan_node["code"]
                plan_key = f"plan:{p_code}"
                use_nodes = plan_node.get("children", [])
                ch_keys = [f"object:{p_code}|{u['code']}" for u in use_nodes]
                items[plan_key] = {
                    "kind": "plan",
                    "level": "工作計畫",
                    "code": p_code,
                    "name": plan_node["name"],
                    "amount_元": plan_node["amount_元"],
                    "page": plan_node["page"],
                    "page_start": plan_node.get("page_start", plan_node["page"]),
                    "page_end": plan_node.get("page_end", plan_node["page"]),
                    "unresolved": bool(plan_node.get("unresolved", False)),
                    "in_hierarchy": True,
                    "children_keys": ch_keys,
                    "parent_key": None,
                    "dept": dept_name,
                    "政事別": func_name,
                }
                for u in use_nodes:
                    u_code = u["code"]
                    obj_code = f"{p_code}|{u_code}"
                    obj_key = f"object:{obj_code}"
                    items[obj_key] = {
                        "kind": "object",
                        "level": "用途別",
                        "code": obj_code,
                        "plan_code": p_code,
                        "用途別_code": u_code,
                        "name": u["name"],
                        "plan_name": plan_node["name"],
                        "amount_元": u["amount_元"],
                        "page": u["page"],
                        "page_start": u.get("page_start", u["page"]),
                        "page_end": u.get("page_end", u["page"]),
                        "unresolved": bool(u.get("unresolved", False)),
                        "in_hierarchy": True,
                        "children_keys": [],
                        "parent_key": plan_key,
                        "dept": dept_name,
                        "政事別": func_name,
                    }

    return items


def _build_compare_json(
    y1: int,
    y2: int,
    items1: dict[str, dict[str, Any]],
    items2: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """合併兩年度項目並建立 compare.json 結構。"""
    s1, s2 = str(y1), str(y2)
    kind_order = {"revenue": 0, "plan": 1, "object": 2}
    rev_level_order = {"款": 0, "項": 1, "子目": 2, "細目": 3}

    all_keys = sorted(
        set(items1.keys()) | set(items2.keys()),
        key=lambda k: (
            kind_order.get((items2.get(k) or items1[k])["kind"], 9),
            rev_level_order.get((items2.get(k) or items1[k])["level"], 9),
            (items2.get(k) or items1[k])["code"],
        ),
    )

    entries: dict[str, dict[str, Any]] = {}
    for key in all_keys:
        n1 = items1.get(key)
        n2 = items2.get(key)
        ref = n2 or n1
        assert ref is not None

        kind = ref["kind"]
        level = ref["level"]
        code = ref["code"]

        if n1 is not None and n2 is not None:
            status = "both"
        elif n1 is not None:
            status = f"only_{s1}"
        else:
            status = f"only_{s2}"

        name1 = n1["name"] if n1 is not None else None
        name2 = n2["name"] if n2 is not None else None
        name_changed = bool(n1 is not None and n2 is not None and name1 != name2)

        a1 = n1["amount_元"] if n1 is not None else None
        a2 = n2["amount_元"] if n2 is not None else None
        diff_yuan = (a2 if a2 is not None else 0) - (a1 if a1 is not None else 0)

        if a1 is not None and a2 is not None and a1 == 0 and a2 == 0:
            pct: float | int | None = 0
        elif a1 is None or a1 == 0:
            pct = None
        else:
            pct = round((diff_yuan / a1) * 100, 2)

        p1 = (
            {
                "page": n1["page"],
                "page_start": n1["page_start"],
                "page_end": n1["page_end"],
            }
            if n1 is not None
            else None
        )
        p2 = (
            {
                "page": n2["page"],
                "page_start": n2["page_start"],
                "page_end": n2["page_end"],
            }
            if n2 is not None
            else None
        )

        ch1 = n1["children_keys"] if n1 is not None else []
        ch2 = n2["children_keys"] if n2 is not None else []
        merged_children = sorted(
            set(ch1) | set(ch2),
            key=lambda ck: ck.split(":", 1)[1] if ":" in ck else ck,
        )

        unresolved = bool(
            (n1 and n1["unresolved"]) or (n2 and n2["unresolved"])
        )
        in_hierarchy = bool(
            (n1 and n1["in_hierarchy"]) or (n2 and n2["in_hierarchy"])
        )
        parent_key = (n2.get("parent_key") if n2 else None) or (
            n1.get("parent_key") if n1 else None
        )
        dept = (n2.get("dept") if n2 else None) or (
            n1.get("dept") if n1 else ""
        ) or ""

        entry: dict[str, Any] = {
            "key": key,
            "kind": kind,
            "level": level,
            "code": code,
            "name": {s1: name1, s2: name2},
            "display_name": name2 if name2 is not None else name1,
            "amount_元": {s1: a1, s2: a2},
            "diff_元": diff_yuan,
            "pct": pct,
            "page": {s1: p1, s2: p2},
            "status": status,
            "name_changed": name_changed,
            "unresolved": unresolved,
            "in_hierarchy": in_hierarchy,
            "children": merged_children,
            "parent_key": parent_key,
            "dept": dept,
        }
        entries[key] = entry

    return {
        "years": [y1, y2],
        "from_year": y1,
        "to_year": y2,
        "entries": entries,
    }


def build(
    data_dir: Path | str = ROOT_DIR / "data",
    out_dir: Path | str = ROOT_DIR / "build",
    site_dir: Path | str = ROOT_DIR / "site" / "data",
) -> dict[str, Any]:
    """掃描 `data_dir/<年度>/`，產生 `budget.sqlite` 與 `site_dir/*.json`。"""
    data_path = Path(data_dir)
    out_path = Path(out_dir)
    site_path = Path(site_dir)

    years = discover_years(data_path)
    known_diffs = load_known_diffs(data_path)

    out_path.mkdir(parents=True, exist_ok=True)
    site_path.mkdir(parents=True, exist_ok=True)

    sqlite_path = out_path / "budget.sqlite"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{sqlite_path}{suffix}")
        if candidate.exists():
            candidate.unlink()

    all_search_docs: list[dict[str, Any]] = []
    year_summaries: list[dict[str, Any]] = []
    compare_items_by_year: dict[int, dict[str, dict[str, Any]]] = {}

    conn = sqlite3.connect(str(sqlite_path))
    try:
        _init_sqlite_schema(conn)

        for y in years:
            (
                summary_rows,
                revenue_rows,
                plans_rows,
                expenditure_rows,
                year_json,
                search_docs,
            ) = _build_year_data(y, data_path / str(y), known_diffs)
            compare_items_by_year[y] = _collect_year_compare_items(
                y, revenue_rows, year_json, known_diffs
            )

            conn.executemany(
                """
                INSERT INTO summary (
                    year, source_book, source_table, page, 款, 項, 科目名稱, 本年度, 上年度, 前年度決算
                ) VALUES (
                    :year, :source_book, :source_table, :page, :款, :項, :科目名稱, :本年度, :上年度, :前年度決算
                )
                """,
                summary_rows,
            )

            conn.executemany(
                """
                INSERT INTO revenue_items (
                    year, page, code, name, item_seq, unit, qty, unit_price, amount_元, note, dept,
                    unresolved, unresolved_diff_元, unresolved_note
                ) VALUES (
                    :year, :page, :code, :name, :item_seq, :unit, :qty, :unit_price, :amount_元, :note, :dept,
                    :unresolved, :unresolved_diff_元, :unresolved_note
                )
                """,
                revenue_rows,
            )

            conn.executemany(
                """
                INSERT INTO plans (
                    year, page_start, page_end, plan_code, name, dept, 政事別, 總額,
                    unresolved, unresolved_diff_元, unresolved_note
                ) VALUES (
                    :year, :page_start, :page_end, :plan_code, :name, :dept, :政事別, :總額,
                    :unresolved, :unresolved_diff_元, :unresolved_note
                )
                """,
                plans_rows,
            )

            conn.executemany(
                """
                INSERT INTO expenditure_items (
                    year, page, plan_code, 用途別_code, 用途別, unit, qty, unit_price, amount_元,
                    說明, 經費來源, item_seq, unresolved, unresolved_diff_元, unresolved_note
                ) VALUES (
                    :year, :page, :plan_code, :用途別_code, :用途別, :unit, :qty, :unit_price, :amount_元,
                    :說明, :經費來源, :item_seq, :unresolved, :unresolved_diff_元, :unresolved_note
                )
                """,
                expenditure_rows,
            )

            _write_json_deterministic(site_path / f"{y}.json", year_json)
            all_search_docs.extend(search_docs)
            year_summaries.append(
                {
                    "year": y,
                    "revenue_total_元": year_json["overview"]["revenue_total_元"],
                    "expenditure_total_元": year_json["overview"]["expenditure_total_元"],
                    "unresolved_count": len(year_json["overview"]["unresolved_items"]),
                }
            )

        # Crosswalk CSVs (optional: tolerate missing files)
        crosswalk_dir = data_path / "crosswalk"
        codes_rows: list[dict[str, Any]] = []
        for r in _read_csv(crosswalk_dir / "codes.csv"):
            fy = _parse_int(r.get("from_year"), allow_empty=True)
            ty = _parse_int(r.get("to_year"), allow_empty=True)
            if fy is None or ty is None:
                continue
            codes_rows.append(
                {
                    "from_year": fy,
                    "from_code": (r.get("from_code") or "").strip(),
                    "to_year": ty,
                    "to_code": (r.get("to_code") or "").strip(),
                    "note": (r.get("note") or "").strip(),
                }
            )
        codes_rows.sort(
            key=lambda x: (x["from_year"], x["to_year"], x["from_code"], x["to_code"])
        )
        if codes_rows:
            conn.executemany(
                """
                INSERT INTO crosswalk_codes (from_year, from_code, to_year, to_code, note)
                VALUES (:from_year, :from_code, :to_year, :to_code, :note)
                """,
                codes_rows,
            )

        items_rows: list[dict[str, Any]] = []
        for r in _read_csv(crosswalk_dir / "items.csv"):
            yr = _parse_int(r.get("year"), allow_empty=True)
            seq = _parse_int(r.get("item_seq"), allow_empty=True)
            if yr is None or seq is None:
                continue
            items_rows.append(
                {
                    "item_id": (r.get("item_id") or "").strip(),
                    "kind": (r.get("kind") or "").strip(),
                    "year": yr,
                    "scope_key": (r.get("scope_key") or "").strip(),
                    "item_seq": seq,
                }
            )
        items_rows.sort(
            key=lambda x: (x["kind"], x["item_id"], x["year"], x["scope_key"], x["item_seq"])
        )
        if items_rows:
            conn.executemany(
                """
                INSERT INTO crosswalk_items (item_id, kind, year, scope_key, item_seq)
                VALUES (:item_id, :kind, :year, :scope_key, :item_seq)
                """,
                items_rows,
            )

        candidates_rows: list[dict[str, Any]] = []
        for r in _read_csv(crosswalk_dir / "items_candidates.csv"):
            fy = _parse_int(r.get("from_year"), allow_empty=True)
            ty = _parse_int(r.get("to_year"), allow_empty=True)
            if fy is None or ty is None:
                continue
            candidates_rows.append(
                {
                    "kind": (r.get("kind") or "").strip(),
                    "scope_key": (r.get("scope_key") or "").strip(),
                    "from_year": fy,
                    "from_item_seq": _parse_int(r.get("from_item_seq"), allow_empty=True),
                    "to_year": ty,
                    "to_item_seq": _parse_int(r.get("to_item_seq"), allow_empty=True),
                    "status": (r.get("status") or "").strip(),
                    "similarity": float((r.get("similarity") or "0").strip()),
                    "from_text": (r.get("from_text") or "").strip(),
                    "to_text": (r.get("to_text") or "").strip(),
                }
            )
        candidates_rows.sort(
            key=lambda x: (
                x["kind"],
                x["scope_key"],
                x["from_year"],
                x["to_year"],
                x["from_item_seq"] or 0,
                x["to_item_seq"] or 0,
            )
        )
        if candidates_rows:
            conn.executemany(
                """
                INSERT INTO crosswalk_items_candidates (
                    kind, scope_key, from_year, from_item_seq, to_year, to_item_seq,
                    status, similarity, from_text, to_text
                ) VALUES (
                    :kind, :scope_key, :from_year, :from_item_seq, :to_year, :to_item_seq,
                    :status, :similarity, :from_text, :to_text
                )
                """,
                candidates_rows,
            )

        conn.commit()
    finally:
        conn.close()

    index_json: dict[str, Any] = {
        "years": years,
        "default_year": years[-1] if years else None,
        "year_summaries": year_summaries,
        "crosswalk": {
            "codes": codes_rows,
            "items": items_rows,
            "items_candidates": candidates_rows,
        },
    }
    _write_json_deterministic(site_path / "index.json", index_json)
    _write_json_deterministic(site_path / "search.json", all_search_docs)

    compare_path = site_path / "compare.json"
    if len(years) >= 2:
        y1, y2 = years[-2], years[-1]
        compare_json = _build_compare_json(
            y1, y2, compare_items_by_year[y1], compare_items_by_year[y2]
        )
        _write_json_deterministic(compare_path, compare_json)
    elif compare_path.exists():
        compare_path.unlink()

    return {
        "sqlite_path": sqlite_path,
        "site_dir": site_path,
        "years": years,
        "search_doc_count": len(all_search_docs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="將 data/<年度>/*.csv 建置為 build/budget.sqlite 與 site/data/*.json"
    )
    parser.add_argument(
        "--data-dir",
        default=str(ROOT_DIR / "data"),
        help="CSV 資料根目錄（預設：data）",
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT_DIR / "build"),
        help="SQLite 輸出目錄（預設：build）",
    )
    parser.add_argument(
        "--site-dir",
        default=str(ROOT_DIR / "site" / "data"),
        help="靜態網站 JSON 輸出目錄（預設：site/data）",
    )
    args = parser.parse_args(argv)
    build(
        data_dir=Path(args.data_dir),
        out_dir=Path(args.out_dir),
        site_dir=Path(args.site_dir),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
