#!/usr/bin/env python3
"""Validate parsed budget CSVs and generate reports/validate_<year>.md (Slices S1 & S2)."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.parse_book import (
    PLAN_PREFIX_TO_FUNCTION,
    find_unapplied_corrections,
    has_reference_corrections,
    load_corrections,
    parse_part1_summary,
    parse_part3_expenditure,
    parse_part3_reference_tables,
    parse_part3_revenue,
    parse_single_amount,
    load_toc,
)


def fmt_yuan(val: int) -> str:
    return f"{val:,}"


def fmt_k_and_yuan(val_yuan: int) -> str:
    if val_yuan % 1000 == 0:
        return f"{val_yuan // 1000:,} 千元 ({val_yuan:,} 元)"
    return f"{val_yuan:,} 元"


def page_range_str(p_start: int, p_end: int) -> str:
    return f"p{p_start}" if p_start == p_end else f"p{p_start}–p{p_end}"


def format_diff_status(diff_yuan: int, diff_items: list[dict[str, Any]]) -> str:
    """Dynamically format hierarchy comparison status from actual non-zero fine-items."""
    if diff_yuan == 0:
        return "通過"
    descs = [
        f"{page_range_str(it['page_start'], it['page_end'])} {it['code']}"
        for it in diff_items
    ]
    source_clause = f"，源自 {'、'.join(descs)}" if descs else ""
    if diff_items and all(it["unresolved"] and not it["failed"] for it in diff_items):
        return f"未解決，待使用者查證（差 {fmt_yuan(diff_yuan)} 元{source_clause}）"
    return f"失敗（差 {fmt_yuan(diff_yuan)} 元{source_clause}）"


def validate_year(year: str, root_dir: Path = ROOT_DIR, partial: bool = False) -> dict[str, Any]:
    """Run all S1 validations on data/<year>/*.csv and raw/<year>/*.md, writing report."""
    year_str = str(year)
    raw_dir = root_dir / "raw" / year_str
    data_dir = root_dir / "data" / year_str
    corrections_path = root_dir / "data" / "corrections.csv"

    part1_text = (raw_dir / "part1.md").read_text(encoding="utf-8")
    part3_text = (raw_dir / "part3.md").read_text(encoding="utf-8")

    toc = load_toc(raw_dir, part1_text)
    corrections = load_corrections(corrections_path, year_str)

    _, sum_anomalies, sum_applied, part1_section_checks = parse_part1_summary(
        part1_text, year_str, toc, corrections, partial=partial
    )
    _, rev_headers, rev_anomalies, rev_applied, rev_header_count = parse_part3_revenue(
        part3_text, year_str, toc, corrections, partial=partial
    )
    (
        _,
        _,
        exp_plans_meta,
        exp_anomalies,
        exp_applied,
        exp_header_count,
    ) = parse_part3_expenditure(part3_text, year_str, toc, corrections, partial=partial)

    unregistered_anomalies = sum_anomalies + rev_anomalies + exp_anomalies
    # 參考表（p154 之後）修正：只有 corrections.csv 登記了 ref: 修正時才解析，讓未套用判定涵蓋它們。
    ref_applied: list[dict[str, Any]] = []
    if has_reference_corrections(corrections):
        _, ref_applied = parse_part3_reference_tables(
            part3_text, year_str, toc, partial=partial, corrections=corrections
        )
    applied_corrections = sum_applied + rev_applied + exp_applied + ref_applied
    unapplied_corrections = find_unapplied_corrections(corrections, applied_corrections)

    summary_csv_path = data_dir / "summary.csv"
    revenue_csv_path = data_dir / "revenue_items.csv"
    plans_csv_path = data_dir / "plans.csv"
    expenditure_csv_path = data_dir / "expenditure_items.csv"

    with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
        summary_rows = list(csv.DictReader(f))

    with revenue_csv_path.open("r", encoding="utf-8", newline="") as f:
        revenue_rows = list(csv.DictReader(f))

    with plans_csv_path.open("r", encoding="utf-8", newline="") as f:
        plans_rows = list(csv.DictReader(f))

    with expenditure_csv_path.open("r", encoding="utf-8", newline="") as f:
        expenditure_rows = list(csv.DictReader(f))

    csv_anomalies: list[dict[str, Any]] = []
    for r in revenue_rows:
        for col in ("unit_price", "amount_元"):
            _, ok = parse_single_amount(r[col], allow_empty=False)
            if not ok:
                csv_anomalies.append(
                    {
                        "page": int(r["page"]),
                        "source_table": "revenue_items.csv",
                        "locator": f"{r['code']}:{r['item_seq']}",
                        "field": col,
                        "raw_value": r[col],
                    }
                )
    for r in plans_rows:
        _, ok = parse_single_amount(r["總額"], allow_empty=False)
        if not ok:
            csv_anomalies.append(
                {
                    "page": int(r["page_start"]),
                    "source_table": "plans.csv",
                    "locator": r["plan_code"],
                    "field": "總額",
                    "raw_value": r["總額"],
                }
            )
    for r in expenditure_rows:
        for col in ("unit_price", "amount_元"):
            _, ok = parse_single_amount(r[col], allow_empty=False)
            if not ok:
                csv_anomalies.append(
                    {
                        "page": int(r["page"]),
                        "source_table": "expenditure_items.csv",
                        "locator": f"{r['plan_code']}:{r['用途別_code']}:{r['item_seq']}",
                        "field": col,
                        "raw_value": r[col],
                    }
                )
    for r in summary_rows:
        for col in ("本年度", "上年度", "前年度決算"):
            _, ok = parse_single_amount(r[col], allow_empty=True)
            if not ok:
                csv_anomalies.append(
                    {
                        "page": int(r["page"]),
                        "source_table": r["source_table"],
                        "locator": r["科目名稱"],
                        "field": col,
                        "raw_value": r[col],
                    }
                )

    all_unregistered = unregistered_anomalies + csv_anomalies

    # 1. Revenue detail items sum vs block header budget (20 fine-items)
    items_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in revenue_rows:
        items_by_code[r["code"]].append(r)

    fine_item_checks: list[dict[str, Any]] = []
    for hdr in rev_headers:
        code = hdr["code"]
        rows = items_by_code.get(code, [])
        detail_sum = 0
        for r in rows:
            val, ok = parse_single_amount(r["amount_元"], allow_empty=False)
            if ok and val is not None:
                detail_sum += val
        header_budget = hdr["header_budget_元"]
        diff = detail_sum - header_budget

        diff_key = (hdr["page_start"], code, "_known_diff")
        known_diff_corr = corrections.get(diff_key)

        if diff == 0:
            status = "通過"
            passed = True
            unresolved = False
            failed = False
        elif known_diff_corr is not None:
            reg_diff, ok_reg = parse_single_amount(known_diff_corr["old"], allow_empty=False)
            if ok_reg and reg_diff == diff and known_diff_corr["new"] == "UNRESOLVED":
                status = f"未解決，待使用者查證（已登記 _known_diff：{known_diff_corr['reason']}）"
                passed = False
                unresolved = True
                failed = False
            else:
                status = (
                    f"失敗（corrections.csv 登記之 _known_diff={known_diff_corr['old']} "
                    f"與實際差額 {diff} 不符）"
                )
                passed = False
                unresolved = False
                failed = True
        else:
            status = "失敗（未登記）"
            passed = False
            unresolved = False
            failed = True

        fine_item_checks.append(
            {
                "code": code,
                "name": hdr["name"],
                "page_start": hdr["page_start"],
                "page_end": hdr["page_end"],
                "item_count": len(rows),
                "detail_sum_元": detail_sum,
                "header_budget_元": header_budget,
                "diff_元": diff,
                "passed": passed,
                "unresolved": unresolved,
                "failed": failed,
                "status": status,
                "known_diff_correction": known_diff_corr if unresolved else None,
            }
        )

    unresolved_items = [chk for chk in fine_item_checks if chk["unresolved"]]

    # 2. Revenue hierarchy check against part1 歲入來源別預算總表
    part1_rev_table = [
        r for r in summary_rows if r["source_table"] == "歲入來源別預算總表"
    ]
    part1_total_row = next((r for r in part1_rev_table if r["科目名稱"] == "歲入合計"), None)
    part1_kuan_rows = [r for r in part1_rev_table if r["款"] and not r["項"]]
    part1_hsiang_rows = [r for r in part1_rev_table if r["款"] and r["項"]]

    subitem_header_sums: dict[str, int] = defaultdict(int)
    subitem_detail_sums: dict[str, int] = defaultdict(int)
    subitem_pages: dict[str, list[int]] = defaultdict(list)
    subitem_fine_items: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for chk in fine_item_checks:
        sub_name = chk["name"].split("-")[0].strip()
        subitem_header_sums[sub_name] += chk["header_budget_元"]
        subitem_detail_sums[sub_name] += chk["detail_sum_元"]
        subitem_pages[sub_name].extend([chk["page_start"], chk["page_end"]])
        subitem_fine_items[sub_name].append(chk)

    hsiang_checks: list[dict[str, Any]] = []
    kuan_from_hsiang_header: dict[str, int] = defaultdict(int)
    kuan_from_hsiang_detail: dict[str, int] = defaultdict(int)
    kuan_diff_fine_items: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for hr in part1_hsiang_rows:
        kuan = hr["款"]
        hsiang = hr["項"]
        subj = hr["科目名稱"]
        target_yuan = int(hr["本年度"])
        hdr_sum = subitem_header_sums.get(subj, 0)
        dtl_sum = subitem_detail_sums.get(subj, 0)
        pages = subitem_pages.get(subj, [])
        p_range = page_range_str(min(pages), max(pages)) if pages else "-"
        diff_fines = [c for c in subitem_fine_items.get(subj, []) if c["diff_元"] != 0]

        kuan_from_hsiang_header[kuan] += hdr_sum
        kuan_from_hsiang_detail[kuan] += dtl_sum
        kuan_diff_fine_items[kuan].extend(diff_fines)

        hsiang_checks.append(
            {
                "款": kuan,
                "項": hsiang,
                "科目名稱": subj,
                "summary_page": int(hr["page"]),
                "detail_page_range": p_range,
                "target_元": target_yuan,
                "header_sum_元": hdr_sum,
                "detail_sum_元": dtl_sum,
                "header_passed": hdr_sum == target_yuan,
                "detail_passed": dtl_sum == target_yuan,
                "diff_fine_items": diff_fines,
                "detail_status": format_diff_status(dtl_sum - target_yuan, diff_fines),
            }
        )

    kuan_checks: list[dict[str, Any]] = []
    total_kuan_target = 0
    total_kuan_header = 0
    total_kuan_detail = 0
    all_diff_fine_items: list[dict[str, Any]] = []

    for kr in part1_kuan_rows:
        kuan = kr["款"]
        subj = kr["科目名稱"]
        target_yuan = int(kr["本年度"])
        hdr_sum = kuan_from_hsiang_header.get(kuan, 0)
        dtl_sum = kuan_from_hsiang_detail.get(kuan, 0)
        diff_fines = kuan_diff_fine_items.get(kuan, [])

        total_kuan_target += target_yuan
        total_kuan_header += hdr_sum
        total_kuan_detail += dtl_sum
        all_diff_fine_items.extend(diff_fines)

        kuan_checks.append(
            {
                "款": kuan,
                "科目名稱": subj,
                "summary_page": int(kr["page"]),
                "target_元": target_yuan,
                "header_sum_元": hdr_sum,
                "detail_sum_元": dtl_sum,
                "header_passed": hdr_sum == target_yuan,
                "detail_passed": dtl_sum == target_yuan,
                "diff_fine_items": diff_fines,
                "detail_status": format_diff_status(dtl_sum - target_yuan, diff_fines),
            }
        )

    expected_grand_total_yuan = int(part1_total_row["本年度"]) if part1_total_row else total_kuan_target
    grand_total_page = int(part1_total_row["page"]) if part1_total_row else 0
    grand_detail_status = format_diff_status(
        total_kuan_detail - expected_grand_total_yuan, all_diff_fine_items
    )

    # 3. Expenditure checks (S2):
    #    (a) Every (plan_code, 用途別_code) detail sum == 用途別 subtotal
    #    (b) Every plan's 用途別 subtotals sum == plan 總額
    #    (c) Plan totals grouped by 政事別 == part1 歲出政事別預算總表 (歲出合計)
    exp_items_by_plan_use: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    exp_items_by_plan: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in expenditure_rows:
        exp_items_by_plan_use[(r["plan_code"], r["用途別_code"])].append(r)
        exp_items_by_plan[r["plan_code"]].append(r)

    expenditure_use_checks: list[dict[str, Any]] = []
    expenditure_plan_checks: list[dict[str, Any]] = []
    unresolved_exp_uses: list[dict[str, Any]] = []
    unresolved_exp_plans: list[dict[str, Any]] = []

    for p_meta in exp_plans_meta:
        p_code = p_meta["plan_code"]
        p_name = p_meta["name"]
        p_start = p_meta["page_start"]
        p_end = p_meta["page_end"]
        header_budget = p_meta["header_budget_元"]

        plan_use_checks: list[dict[str, Any]] = []
        use_subtotal_sum = 0
        for l2 in p_meta["level2_subtotals"]:
            u_code = l2["用途別_code"]
            u_name = l2["用途別"]
            u_start = l2["page_start"]
            u_end = l2["page_end"]
            u_subtotal = l2["subtotal_元"]
            use_subtotal_sum += u_subtotal

            u_rows = exp_items_by_plan_use.get((p_code, u_code), [])
            u_detail_sum = 0
            for r in u_rows:
                val, ok = parse_single_amount(r["amount_元"], allow_empty=False)
                if ok and val is not None:
                    u_detail_sum += val
            u_diff = u_detail_sum - u_subtotal

            u_loc = f"{p_code}:{u_code}"
            u_diff_key = (u_start, u_loc, "_known_diff")
            u_kd_corr = corrections.get(u_diff_key)

            if u_diff == 0:
                u_status = "通過"
                u_passed = True
                u_unresolved = False
                u_failed = False
            elif u_kd_corr is not None:
                reg_diff, ok_reg = parse_single_amount(u_kd_corr["old"], allow_empty=False)
                if ok_reg and reg_diff == u_diff and u_kd_corr["new"] == "UNRESOLVED":
                    u_status = f"未解決，待使用者查證（已登記 _known_diff：{u_kd_corr['reason']}）"
                    u_passed = False
                    u_unresolved = True
                    u_failed = False
                else:
                    u_status = (
                        f"失敗（corrections.csv 登記之 _known_diff={u_kd_corr['old']} "
                        f"與實際差額 {u_diff} 不符）"
                    )
                    u_passed = False
                    u_unresolved = False
                    u_failed = True
            else:
                u_status = "失敗（未登記）"
                u_passed = False
                u_unresolved = False
                u_failed = True

            u_chk = {
                "plan_code": p_code,
                "plan_name": p_name,
                "用途別_code": u_code,
                "用途別": u_name,
                "page_start": u_start,
                "page_end": u_end,
                "item_count": len(u_rows),
                "detail_sum_元": u_detail_sum,
                "subtotal_元": u_subtotal,
                "diff_元": u_diff,
                "passed": u_passed,
                "unresolved": u_unresolved,
                "failed": u_failed,
                "status": u_status,
                "known_diff_correction": u_kd_corr if u_unresolved else None,
            }
            expenditure_use_checks.append(u_chk)
            plan_use_checks.append(u_chk)
            if u_unresolved:
                unresolved_exp_uses.append(u_chk)

        p_rows = exp_items_by_plan.get(p_code, [])
        p_detail_sum = 0
        for r in p_rows:
            val, ok = parse_single_amount(r["amount_元"], allow_empty=False)
            if ok and val is not None:
                p_detail_sum += val

        subtotal_diff = use_subtotal_sum - header_budget
        detail_diff = p_detail_sum - header_budget

        p_diff_key = (p_start, p_code, "_known_diff")
        p_kd_corr = corrections.get(p_diff_key)

        if subtotal_diff == 0 and detail_diff == 0 and all(u["passed"] for u in plan_use_checks):
            p_status = "通過"
            p_passed = True
            p_unresolved = False
            p_failed = False
        elif p_kd_corr is not None:
            reg_diff, ok_reg = parse_single_amount(p_kd_corr["old"], allow_empty=False)
            if ok_reg and reg_diff == detail_diff and p_kd_corr["new"] == "UNRESOLVED":
                p_status = f"未解決，待使用者查證（已登記 _known_diff：{p_kd_corr['reason']}）"
                p_passed = False
                p_unresolved = True
                p_failed = False
            else:
                p_status = (
                    f"失敗（corrections.csv 登記之 _known_diff={p_kd_corr['old']} "
                    f"與實際差額 {detail_diff} 不符）"
                )
                p_passed = False
                p_unresolved = False
                p_failed = True
        elif any(u["unresolved"] for u in plan_use_checks) and not any(u["failed"] for u in plan_use_checks):
            p_status = "未解決，待使用者查證（源自用途別小計差額）"
            p_passed = False
            p_unresolved = True
            p_failed = False
        else:
            p_status = "失敗（未登記）"
            p_passed = False
            p_unresolved = False
            p_failed = True

        p_chk = {
            "code": p_code,
            "plan_code": p_code,
            "name": p_name,
            "dept": p_meta["dept"],
            "政事別": p_meta["政事別"],
            "政事別_項": p_meta["政事別_項"],
            "page_start": p_start,
            "page_end": p_end,
            "use_count": len(plan_use_checks),
            "item_count": len(p_rows),
            "use_subtotal_sum_元": use_subtotal_sum,
            "detail_sum_元": p_detail_sum,
            "header_budget_元": header_budget,
            "subtotal_diff_元": subtotal_diff,
            "diff_元": detail_diff,
            "passed": p_passed,
            "unresolved": p_unresolved,
            "failed": p_failed,
            "status": p_status,
            "known_diff_correction": p_kd_corr if p_unresolved else None,
        }
        expenditure_plan_checks.append(p_chk)
        if p_unresolved:
            unresolved_exp_plans.append(p_chk)

    # Expenditure hierarchy check against part1 歲出政事別預算總表
    part1_exp_table = [
        r for r in summary_rows if r["source_table"] == "歲出政事別預算總表"
    ]
    part1_exp_total_row = next((r for r in part1_exp_table if r["科目名稱"] == "歲出合計"), None)
    part1_exp_kuan_rows = [r for r in part1_exp_table if r["款"] and not r["項"]]
    part1_exp_hsiang_rows = [r for r in part1_exp_table if r["款"] and r["項"]]

    exp_hsiang_plan_sums: dict[str, int] = defaultdict(int)
    exp_hsiang_use_sums: dict[str, int] = defaultdict(int)
    exp_hsiang_detail_sums: dict[str, int] = defaultdict(int)
    exp_hsiang_pages: dict[str, list[int]] = defaultdict(list)
    exp_hsiang_plans: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for p_chk in expenditure_plan_checks:
        h_name = p_chk["政事別_項"]
        exp_hsiang_plan_sums[h_name] += p_chk["header_budget_元"]
        exp_hsiang_use_sums[h_name] += p_chk["use_subtotal_sum_元"]
        exp_hsiang_detail_sums[h_name] += p_chk["detail_sum_元"]
        exp_hsiang_pages[h_name].extend([p_chk["page_start"], p_chk["page_end"]])
        exp_hsiang_plans[h_name].append(p_chk)

    expenditure_hsiang_checks: list[dict[str, Any]] = []
    exp_kuan_from_plan: dict[str, int] = defaultdict(int)
    exp_kuan_from_use: dict[str, int] = defaultdict(int)
    exp_kuan_from_detail: dict[str, int] = defaultdict(int)
    exp_kuan_diff_plans: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for hr in part1_exp_hsiang_rows:
        kuan = hr["款"]
        hsiang = hr["項"]
        subj = hr["科目名稱"]
        target_yuan = int(hr["本年度"])
        plan_sum = exp_hsiang_plan_sums.get(subj, 0)
        use_sum = exp_hsiang_use_sums.get(subj, 0)
        dtl_sum = exp_hsiang_detail_sums.get(subj, 0)
        pages = exp_hsiang_pages.get(subj, [])
        p_range = page_range_str(min(pages), max(pages)) if pages else "-"
        diff_plans = [c for c in exp_hsiang_plans.get(subj, []) if c["diff_元"] != 0 or not c["passed"]]

        exp_kuan_from_plan[kuan] += plan_sum
        exp_kuan_from_use[kuan] += use_sum
        exp_kuan_from_detail[kuan] += dtl_sum
        exp_kuan_diff_plans[kuan].extend(diff_plans)

        expenditure_hsiang_checks.append(
            {
                "款": kuan,
                "項": hsiang,
                "科目名稱": subj,
                "summary_page": int(hr["page"]),
                "detail_page_range": p_range,
                "plan_count": len(exp_hsiang_plans.get(subj, [])),
                "target_元": target_yuan,
                "plan_sum_元": plan_sum,
                "use_subtotal_sum_元": use_sum,
                "detail_sum_元": dtl_sum,
                "plan_passed": plan_sum == target_yuan,
                "use_passed": use_sum == target_yuan,
                "detail_passed": dtl_sum == target_yuan,
                "diff_plans": diff_plans,
                "detail_status": format_diff_status(dtl_sum - target_yuan, diff_plans),
            }
        )

    expenditure_kuan_checks: list[dict[str, Any]] = []
    total_exp_target = 0
    total_exp_plan = 0
    total_exp_use = 0
    total_exp_detail = 0
    all_diff_exp_plans: list[dict[str, Any]] = []

    for kr in part1_exp_kuan_rows:
        kuan = kr["款"]
        subj = kr["科目名稱"]
        target_yuan = int(kr["本年度"])
        plan_sum = exp_kuan_from_plan.get(kuan, 0)
        use_sum = exp_kuan_from_use.get(kuan, 0)
        dtl_sum = exp_kuan_from_detail.get(kuan, 0)
        diff_plans = exp_kuan_diff_plans.get(kuan, [])

        total_exp_target += target_yuan
        total_exp_plan += plan_sum
        total_exp_use += use_sum
        total_exp_detail += dtl_sum
        all_diff_exp_plans.extend(diff_plans)

        expenditure_kuan_checks.append(
            {
                "款": kuan,
                "科目名稱": subj,
                "summary_page": int(kr["page"]),
                "target_元": target_yuan,
                "plan_sum_元": plan_sum,
                "use_subtotal_sum_元": use_sum,
                "detail_sum_元": dtl_sum,
                "plan_passed": plan_sum == target_yuan,
                "use_passed": use_sum == target_yuan,
                "detail_passed": dtl_sum == target_yuan,
                "diff_plans": diff_plans,
                "detail_status": format_diff_status(dtl_sum - target_yuan, diff_plans),
            }
        )

    expected_exp_grand_total_yuan = (
        int(part1_exp_total_row["本年度"]) if part1_exp_total_row else total_exp_target
    )
    exp_grand_total_page = int(part1_exp_total_row["page"]) if part1_exp_total_row else 7
    exp_grand_detail_status = format_diff_status(
        total_exp_detail - expected_exp_grand_total_yuan, all_diff_exp_plans
    )

    # 4. Cross-table conflict detection in summary.csv
    subj_field_records: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in summary_rows:
        subj = r["科目名稱"]
        for field in ("本年度", "上年度", "前年度決算"):
            val_str = r[field].strip()
            if val_str != "":
                subj_field_records[(subj, field)].append(
                    {
                        "source_table": r["source_table"],
                        "page": int(r["page"]),
                        "value_元": int(val_str),
                    }
                )

    summary_conflicts: list[dict[str, Any]] = []
    for (subj, field), recs in subj_field_records.items():
        distinct_vals = {rec["value_元"] for rec in recs}
        if len(distinct_vals) > 1:
            summary_conflicts.append(
                {
                    "科目名稱": subj,
                    "field": field,
                    "records": recs,
                }
            )

    # Generate markdown report
    report_dir = root_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"validate_{year_str}.md"

    lines: list[str] = []
    lines.append(f"# {year_str} 年度預算書資料驗證報告（S1 & S2）")
    lines.append("")

    # Summary of unresolved items at the top of the report (per R2)
    lines.append("## 摘要（未解決待查證項目）")
    lines.append("")
    if not unresolved_items and not unresolved_exp_plans and not unresolved_exp_uses:
        lines.append("- 無未解決待查證項目。")
    else:
        lines.append(f"- **歲入未解決，待使用者查證細目數**：**{len(unresolved_items)}**")
        for item in unresolved_items:
            p_str = page_range_str(item["page_start"], item["page_end"])
            reason_str = item["known_diff_correction"]["reason"] if item["known_diff_correction"] else ""
            lines.append(
                f"  - `{item['code']}` {item['name']}（{p_str}）：明細加總 `{fmt_yuan(item['detail_sum_元'])}` 元 "
                f"vs 表頭 `{fmt_yuan(item['header_budget_元'])}` 元（差額 `{fmt_yuan(item['diff_元'])}` 元）— "
                f"**未解決，待使用者查證**（{reason_str}）"
            )
        lines.append(f"- **歲出未解決，待使用者查證計畫／用途別數**：**{len(unresolved_exp_plans) + len(unresolved_exp_uses)}**")
        for u_item in unresolved_exp_uses:
            p_str = page_range_str(u_item["page_start"], u_item["page_end"])
            reason_str = u_item["known_diff_correction"]["reason"] if u_item["known_diff_correction"] else ""
            lines.append(
                f"  - `{u_item['plan_code']}:{u_item['用途別_code']}` {u_item['用途別']}（{p_str}）："
                f"明細加總 `{fmt_yuan(u_item['detail_sum_元'])}` 元 vs 小計 `{fmt_yuan(u_item['subtotal_元'])}` 元"
                f"（差額 `{fmt_yuan(u_item['diff_元'])}` 元）— **未解決，待使用者查證**（{reason_str}）"
            )
    lines.append("")

    lines.append("## 1. 頁碼推算與表頭數驗證")
    lines.append("")
    toc_rev_start, toc_rev_end = toc["歲入項目說明提要與預算明細表"]
    toc_rev_pages = toc_rev_end - toc_rev_start + 1
    lines.append(
        f"- **歲入項目說明提要與預算明細表**：目錄頁碼 p{toc_rev_start}–p{toc_rev_end}（共 {toc_rev_pages} 頁），"
        f"實際解析表頭數 **{rev_header_count}**，結果：**{'通過' if rev_header_count == toc_rev_pages else '失敗'}**"
    )
    toc_exp_start, toc_exp_end = toc["歲出計畫說明提要與各項費用明細表"]
    toc_exp_pages = toc_exp_end - toc_exp_start + 1
    lines.append(
        f"- **歲出計畫說明提要與各項費用明細表**：目錄頁碼 p{toc_exp_start}–p{toc_exp_end}（共 {toc_exp_pages} 頁），"
        f"實際解析表頭數 **{exp_header_count}**，結果：**{'通過' if exp_header_count == toc_exp_pages else '失敗'}**"
    )
    p1_min_page = min(s["page_start"] for s in part1_section_checks)
    p1_max_page = max(s["page_end"] for s in part1_section_checks)
    p1_all_passed = all(s["passed"] for s in part1_section_checks)
    lines.append(
        f"- **part1 分析表及比較總表（p{p1_min_page}–p{p1_max_page}，共 {len(part1_section_checks)} 張總表）**："
        f"各章節表頭數與目錄頁數比對結果：**{'通過' if p1_all_passed else '失敗'}**"
    )
    for sc in part1_section_checks:
        sc_range = page_range_str(sc["page_start"], sc["page_end"])
        lines.append(
            f"  - {sc['section_name']}（{sc_range}）：目錄 {sc['expected_pages']} 頁 / 實際表頭 {sc['actual_pages']}，{'通過' if sc['passed'] else '失敗'}"
        )
    lines.append("")

    lines.append("## 2. 數字欄位異常與 OCR 修正檢查")
    lines.append("")
    lines.append(f"- **數字欄位異常、未登記修正筆數**：**{len(all_unregistered)}**")
    lines.append(f"- **已登記並套用 `data/corrections.csv` 修正筆數**：**{len(applied_corrections)}**")
    lines.append(f"- **已登記但因 `old` 與 raw 不符而未套用之修正筆數**：**{len(unapplied_corrections)}**")
    lines.append("")
    if all_unregistered:
        lines.append("### 未登記數字欄位異常清單")
        lines.append("")
        lines.append("| 頁碼 | 來源表 | 定位 (locator) | 欄位 | 原始值 |")
        lines.append("|---|---|---|---|---|")
        for a in all_unregistered:
            lines.append(f"| p{a['page']} | {a['source_table']} | `{a['locator']}` | `{a['field']}` | `{a['raw_value']}` |")
        lines.append("")

    if unapplied_corrections:
        lines.append("### 已登記但未套用之修正清單（異常）")
        lines.append("")
        lines.append("| 頁碼 | 定位 (locator) | 欄位 | 預期原值 (old) | 修正值 (new) | 原因 (reason) |")
        lines.append("|---|---|---|---|---|---|")
        for c in unapplied_corrections:
            lines.append(
                f"| p{c['page']} | `{c['locator']}` | `{c['field']}` | `{c['old']}` | `{c['new']}` | {c['reason']} |"
            )
        lines.append("")

    lines.append("### 已登記套用之 OCR 修正清單（`data/corrections.csv`）")
    lines.append("")
    lines.append("| 頁碼 | 定位 (locator) | 欄位 | 原始值 (old) | 修正值 (new) | 原因 (reason) |")
    lines.append("|---|---|---|---|---|---|")
    for c in applied_corrections:
        lines.append(
            f"| p{c['page']} | `{c['locator']}` | `{c['field']}` | `{c['old']}` | `{c['new']}` | {c['reason']} |"
        )
    lines.append("")

    lines.append(f"## 3. 歲入明細加總檢查（{len(fine_item_checks)} 個細目逐一核對）")
    lines.append("")
    lines.append("| # | 細目編號 | 細目名稱 | 頁碼 | 明細筆數 | 明細加總 (元) | 表頭預算金額 (元) | 差額 (元) | 結果 |")
    lines.append("|---|---|---|---|---:|---:|---:|---:|---|")
    for idx, chk in enumerate(fine_item_checks, start=1):
        p_str = page_range_str(chk["page_start"], chk["page_end"])
        lines.append(
            f"| {idx} | `{chk['code']}` | {chk['name']} | {p_str} | {chk['item_count']} | "
            f"{fmt_yuan(chk['detail_sum_元'])} | {fmt_yuan(chk['header_budget_元'])} | "
            f"{fmt_yuan(chk['diff_元'])} | {chk['status']} |"
        )
    lines.append("")

    lines.append(
        f"## 4. 歲入階層加總檢查（細目 → 子目／項 → 款 → 總計 {fmt_yuan(expected_grand_total_yuan // 1000)} 千元）"
    )
    lines.append("")
    lines.append("### 4.1 子目／項層級核對（對照 part1 歲入來源別預算總表）")
    lines.append("")
    lines.append("| 款 | 項 | 子目／項名稱 | 總表頁碼 | 明細頁碼 | 總表金額 (元) | 細目表頭加總 (元) | 明細列加總 (元) | 表頭核對 | 明細核對 |")
    lines.append("|---|---|---|---|---|---:|---:|---:|---|---|")
    for hc in hsiang_checks:
        hdr_ok = "通過" if hc["header_passed"] else "失敗"
        lines.append(
            f"| {hc['款']} | {hc['項']} | {hc['科目名稱']} | p{hc['summary_page']} | {hc['detail_page_range']} | "
            f"{fmt_yuan(hc['target_元'])} | {fmt_yuan(hc['header_sum_元'])} | {fmt_yuan(hc['detail_sum_元'])} | "
            f"{hdr_ok} | {hc['detail_status']} |"
        )
    lines.append("")

    lines.append("### 4.2 款層級與歲入總計核對（對照 part1 歲入來源別預算總表）")
    lines.append("")
    lines.append("| 款 | 款名稱 | 總表頁碼 | 總表金額 (千元) | 總表金額 (元) | 子目／細目表頭加總 (元) | 明細列加總 (元) | 表頭核對 | 明細核對 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---|---|")
    for kc in kuan_checks:
        hdr_ok = "通過" if kc["header_passed"] else "失敗"
        lines.append(
            f"| {kc['款']} | {kc['科目名稱']} | p{kc['summary_page']} | {fmt_yuan(kc['target_元'] // 1000)} | "
            f"{fmt_yuan(kc['target_元'])} | {fmt_yuan(kc['header_sum_元'])} | {fmt_yuan(kc['detail_sum_元'])} | "
            f"{hdr_ok} | {kc['detail_status']} |"
        )
    grand_hdr_ok = "通過" if total_kuan_header == expected_grand_total_yuan else "失敗"
    lines.append(
        f"| **合計** | **歲入合計** | p{grand_total_page} | **{fmt_yuan(expected_grand_total_yuan // 1000)}** | "
        f"**{fmt_yuan(expected_grand_total_yuan)}** | **{fmt_yuan(total_kuan_header)}** | "
        f"**{fmt_yuan(total_kuan_detail)}** | **{grand_hdr_ok}** | **{grand_detail_status}** |"
    )
    lines.append("")

    lines.append("## 5. 總表之間的衝突檢查（`summary.csv`）")
    lines.append("")
    if not summary_conflicts:
        lines.append("- 無跨表數值衝突。")
    else:
        lines.append("| 科目名稱 | 欄位 | 衝突數值與來源表（附頁碼） |")
        lines.append("|---|---|---|")
        for conf in summary_conflicts:
            details = " vs ".join(
                f"{rec['source_table']} (p{rec['page']}): **{fmt_k_and_yuan(rec['value_元'])}**"
                for rec in conf["records"]
            )
            lines.append(f"| `{conf['科目名稱']}` | `{conf['field']}` | {details} |")
    lines.append("")

    # Section 6: S2 Expenditure detail & use-category checks
    passed_use_count = sum(1 for u in expenditure_use_checks if u["passed"])
    failed_use_count = sum(1 for u in expenditure_use_checks if u["failed"])
    unresolved_use_count = sum(1 for u in expenditure_use_checks if u["unresolved"])

    lines.append(f"## 6. 歲出計畫與用途別明細加總檢查（{len(expenditure_plan_checks)} 個工作計畫、{len(expenditure_use_checks)} 個二級用途別區塊）")
    lines.append("")
    lines.append(
        f"- **二級用途別小計核對（明細加總 = 用途別小計）**：共 **{len(expenditure_use_checks)}** 個用途別區塊，"
        f"通過 **{passed_use_count}**、未解決 **{unresolved_use_count}**、失敗 **{failed_use_count}**"
    )
    passed_plan_count = sum(1 for p in expenditure_plan_checks if p["passed"])
    failed_plan_count = sum(1 for p in expenditure_plan_checks if p["failed"])
    unresolved_plan_count = sum(1 for p in expenditure_plan_checks if p["unresolved"])
    lines.append(
        f"- **工作計畫總額核對（用途別小計加總 = 明細加總 = 計畫總額）**：共 **{len(expenditure_plan_checks)}** 個計畫，"
        f"通過 **{passed_plan_count}**、未解決 **{unresolved_plan_count}**、失敗 **{failed_plan_count}**"
    )
    lines.append("")

    non_passing_uses = [u for u in expenditure_use_checks if not u["passed"]]
    if non_passing_uses:
        lines.append("### 6.1 用途別明細加總與小計不一致清單")
        lines.append("")
        lines.append("| 計畫編號 | 計畫名稱 | 用途別 | 頁碼 | 明細筆數 | 明細加總 (元) | 用途別小計 (元) | 差額 (元) | 結果 |")
        lines.append("|---|---|---|---|---:|---:|---:|---:|---|")
        for u in non_passing_uses:
            u_p_str = page_range_str(u["page_start"], u["page_end"])
            lines.append(
                f"| `{u['plan_code']}` | {u['plan_name']} | `{u['用途別_code']}` {u['用途別']} | {u_p_str} | "
                f"{u['item_count']} | {fmt_yuan(u['detail_sum_元'])} | {fmt_yuan(u['subtotal_元'])} | "
                f"{fmt_yuan(u['diff_元'])} | {u['status']} |"
            )
        lines.append("")

    lines.append(f"### 6.2 {len(expenditure_plan_checks)} 個歲出工作計畫逐一核對表")
    lines.append("")
    lines.append("| # | 計畫編號 | 計畫名稱 | 承辦單位 | 政事別 | 頁碼 | 用途別數 | 明細筆數 | 用途別小計加總 (元) | 明細加總 (元) | 計畫總額 (元) | 差額 (元) | 結果 |")
    lines.append("|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for idx, p_chk in enumerate(expenditure_plan_checks, start=1):
        p_str = page_range_str(p_chk["page_start"], p_chk["page_end"])
        lines.append(
            f"| {idx} | `{p_chk['plan_code']}` | {p_chk['name']} | {p_chk['dept']} | {p_chk['政事別']} | {p_str} | "
            f"{p_chk['use_count']} | {p_chk['item_count']} | {fmt_yuan(p_chk['use_subtotal_sum_元'])} | "
            f"{fmt_yuan(p_chk['detail_sum_元'])} | {fmt_yuan(p_chk['header_budget_元'])} | "
            f"{fmt_yuan(p_chk['diff_元'])} | {p_chk['status']} |"
        )
    lines.append("")

    lines.append(
        f"## 7. 歲出政事別階層加總檢查（工作計畫 → 政事別項 → 政事別款 → 總計 {fmt_yuan(expected_exp_grand_total_yuan // 1000)} 千元）"
    )
    lines.append("")
    lines.append("### 7.1 政事別「項」層級核對（對照 part1 歲出政事別預算總表）")
    lines.append("")
    lines.append("| 款 | 項 | 政事別項名稱 | 總表頁碼 | 明細頁碼 | 計畫數 | 總表金額 (元) | 計畫總額加總 (元) | 用途別小計加總 (元) | 明細列加總 (元) | 計畫核對 | 明細核對 |")
    lines.append("|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for ehc in expenditure_hsiang_checks:
        p_ok = "通過" if ehc["plan_passed"] else "失敗"
        lines.append(
            f"| {ehc['款']} | {ehc['項']} | {ehc['科目名稱']} | p{ehc['summary_page']} | {ehc['detail_page_range']} | "
            f"{ehc['plan_count']} | {fmt_yuan(ehc['target_元'])} | {fmt_yuan(ehc['plan_sum_元'])} | "
            f"{fmt_yuan(ehc['use_subtotal_sum_元'])} | {fmt_yuan(ehc['detail_sum_元'])} | "
            f"{p_ok} | {ehc['detail_status']} |"
        )
    lines.append("")

    lines.append("### 7.2 政事別「款」層級與歲出總計核對（對照 part1 歲出政事別預算總表）")
    lines.append("")
    lines.append("| 款 | 政事別款名稱 | 總表頁碼 | 總表金額 (千元) | 總表金額 (元) | 計畫總額加總 (元) | 用途別小計加總 (元) | 明細列加總 (元) | 計畫核對 | 明細核對 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for ekc in expenditure_kuan_checks:
        p_ok = "通過" if ekc["plan_passed"] else "失敗"
        lines.append(
            f"| {ekc['款']} | {ekc['科目名稱']} | p{ekc['summary_page']} | {fmt_yuan(ekc['target_元'] // 1000)} | "
            f"{fmt_yuan(ekc['target_元'])} | {fmt_yuan(ekc['plan_sum_元'])} | {fmt_yuan(ekc['use_subtotal_sum_元'])} | "
            f"{fmt_yuan(ekc['detail_sum_元'])} | {p_ok} | {ekc['detail_status']} |"
        )
    exp_grand_plan_ok = "通過" if total_exp_plan == expected_exp_grand_total_yuan else "失敗"
    lines.append(
        f"| **合計** | **歲出合計** | p{exp_grand_total_page} | **{fmt_yuan(expected_exp_grand_total_yuan // 1000)}** | "
        f"**{fmt_yuan(expected_exp_grand_total_yuan)}** | **{fmt_yuan(total_exp_plan)}** | "
        f"**{fmt_yuan(total_exp_use)}** | **{fmt_yuan(total_exp_detail)}** | "
        f"**{exp_grand_plan_ok}** | **{exp_grand_detail_status}** |"
    )
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "year": year_str,
        "report_path": report_path,
        "part1_section_checks": part1_section_checks,
        "revenue_header_count": rev_header_count,
        "expenditure_header_count": exp_header_count,
        "unregistered_anomalies": all_unregistered,
        "applied_corrections": applied_corrections,
        "unapplied_corrections": unapplied_corrections,
        "fine_item_checks": fine_item_checks,
        "unresolved_items": unresolved_items,
        "hsiang_checks": hsiang_checks,
        "kuan_checks": kuan_checks,
        "expected_grand_total_yuan": expected_grand_total_yuan,
        "grand_total_page": grand_total_page,
        "total_kuan_header_yuan": total_kuan_header,
        "total_kuan_detail_yuan": total_kuan_detail,
        "expenditure_use_checks": expenditure_use_checks,
        "expenditure_plan_checks": expenditure_plan_checks,
        "unresolved_exp_uses": unresolved_exp_uses,
        "unresolved_exp_plans": unresolved_exp_plans,
        "expenditure_hsiang_checks": expenditure_hsiang_checks,
        "expenditure_kuan_checks": expenditure_kuan_checks,
        "expected_exp_grand_total_yuan": expected_exp_grand_total_yuan,
        "exp_grand_total_page": exp_grand_total_page,
        "total_exp_plan_yuan": total_exp_plan,
        "total_exp_use_yuan": total_exp_use,
        "total_exp_detail_yuan": total_exp_detail,
        "summary_conflicts": summary_conflicts,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    partial = "--partial" in args
    args = [a for a in args if a != "--partial"]
    if len(args) != 1:
        print("用法: python3 scripts/validate.py <年度> [--partial]", file=sys.stderr)
        return 1
    year = args[0]
    res = validate_year(year, partial=partial)
    unreg_count = len(res["unregistered_anomalies"])
    unapplied_count = len(res["unapplied_corrections"])
    failed_fine_items = [c for c in res["fine_item_checks"] if c["failed"]]
    failed_exp_uses = [c for c in res["expenditure_use_checks"] if c["failed"]]
    failed_exp_plans = [c for c in res["expenditure_plan_checks"] if c["failed"]]
    print(
        f"[{year}年度] 驗證報告已寫入 {res['report_path']}："
        f"未登記數字異常 {unreg_count} 筆、"
        f"未套用修正 {unapplied_count} 筆、"
        f"歲入未解決細目 {len(res['unresolved_items'])} 項、"
        f"歲出計畫通過 {sum(1 for p in res['expenditure_plan_checks'] if p['passed'])}/{len(res['expenditure_plan_checks'])}、"
        f"歲出用途別通過 {sum(1 for u in res['expenditure_use_checks'] if u['passed'])}/{len(res['expenditure_use_checks'])}、"
        f"跨表衝突 {len(res['summary_conflicts'])} 項。"
    )
    if (
        unreg_count > 0
        or unapplied_count > 0
        or failed_fine_items
        or failed_exp_uses
        or failed_exp_plans
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
