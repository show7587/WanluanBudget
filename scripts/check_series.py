#!/usr/bin/env python3
"""series.json 獨立檢核（D1–D9，依 docs/PLAN-series.md §5 與 docs/series-contract.md）。

獨立性：
- 不 import scripts/build.py；所有規則依 docs/series-contract.md 的文字自行實作。
- 金額一律從 data/<年>/*.csv 重算；site/data/<年>.json 只在 D9 用來取節點清單。
- 只用標準函式庫。

用法：
    python3 scripts/check_series.py [--series PATH] [--report PATH] [--skip-build] [--skip-baseline]

任一檢核失敗 → 退出碼 1。不一致一律列入報告，不自動修正。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVENUE_SUMMARY_TABLE = "歲入來源別預算總表"
SAMPLE_SEED = 20261121
SAMPLE_PER_KIND = 4  # revenue / plan / object 各 4 → 每年 12 項（≥10）
MAX_DETAIL_ROWS = 60

# CLAUDE.md「驗證輸出的基準（目前）」
VALIDATE_BASELINE = {
    "114": {"args": ["114", "--partial"], "plans": (50, 50), "objects": (291, 291), "dept": (2, 2),
            "conflicts": 2, "memos": (20, 20)},
    "115": {"args": ["115"], "plans": (48, 48), "objects": (300, 300), "dept": (2, 2),
            "conflicts": 0, "memos": (5, 5)},
    "116": {"args": ["116"], "plans": (49, 49), "objects": (296, 296), "dept": (2, 2),
            "conflicts": 2, "memos": (3, 3)},
}


# ---------------------------------------------------------------- 共用

class Result:
    def __init__(self, code: str, title: str):
        self.code = code
        self.title = title
        self.status = "通過"  # 通過／失敗／略過
        self.notes: list[str] = []      # 說明（不影響結果）
        self.failures: list[str] = []   # 失敗明細（一列一條）
        self.tables: list[tuple[str, list[str], list[list]]] = []  # 附表（不影響結果）

    def fail(self, msg: str):
        self.failures.append(msg)
        self.status = "失敗"

    def skip(self, why: str):
        self.status = "略過"
        self.notes.append(why)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_int(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return int(float(s))


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def split_key(key: str):
    """canonical／原始 key → (kind, code)；去掉 `@<年>` 後綴。"""
    kind, _, rest = key.partition(":")
    code = re.sub(r"@\d+$", "", rest)
    return kind, code


def revenue_level(code: str) -> str:
    if "-" in code:
        return "項"
    if len(code) == 2:
        return "款"
    return "子目" if code.endswith("00") else "細目"


def fmt(v):
    return "—" if v is None else (f"{v:,}" if isinstance(v, int) else str(v))


# ---------------------------------------------------------------- CSV 重算（D1 基礎）

def load_known_diffs():
    """corrections.csv 中 field=_known_diff 且 new=UNRESOLVED 的列：{(年, 細目編號): 差額元}。"""
    p = ROOT / "data" / "corrections.csv"
    out: dict[tuple[int, str], int] = {}
    if not p.exists():
        return out
    for r in read_csv(p):
        if r.get("field") == "_known_diff" and (r.get("new") or "").strip() == "UNRESOLVED":
            out[(int(r["year"]), r["locator"].strip())] = to_int(r.get("old")) or 0
    return out


def hierarchy_subitems(year: int) -> dict[str, list[str]]:
    """site/data/<年>.json 歲入階層中的子目節點：{子目code: [其下細目 code]}（只取節點 code/level）。"""
    p = ROOT / "site" / "data" / f"{year}.json"
    out: dict[str, list[str]] = {}
    if not p.exists():
        return out

    def walk(nodes):
        for n in nodes:
            if n.get("level") == "子目":
                out[n["code"]] = [c["code"] for c in (n.get("children") or []) if c.get("level") == "細目"]
            walk(n.get("children") or [])

    walk(load_json(p).get("revenue", {}).get("hierarchy", []))
    return out


def recompute_year(year: int):
    """從 CSV 重算某年度所有項目。回傳 {原始key: {amount, level, kind, code, page}}。
    子目是否存在以 <年>.json 歲入階層的節點為準，金額由 CSV 細目加總。"""
    d = ROOT / "data" / str(year)
    out: dict[str, dict] = {}

    # 款／項：summary.csv 歲入來源別預算總表 的「本年度」（CSV 已是元）
    for r in read_csv(d / "summary.csv"):
        if r.get("source_table") != REVENUE_SUMMARY_TABLE:
            continue
        kuan, xiang = (r.get("款") or "").strip(), (r.get("項") or "").strip()
        if not kuan:
            continue  # 歲入合計
        code = f"{kuan}-{xiang}" if xiang else kuan
        amount = to_int(r.get("本年度"))
        if amount is None:
            continue
        out[f"revenue:{code}"] = {"amount": amount, "level": "項" if xiang else "款", "kind": "revenue",
                                  "code": code, "page": to_int(r.get("page"))}

    # 細目：明細加總 − _known_diff；子目：階層中的子目，金額＝其下細目加總
    known = load_known_diffs()
    detail: dict[str, int] = defaultdict(int)
    page_of: dict[str, int] = {}
    for r in read_csv(d / "revenue_items.csv"):
        code = r["code"].strip()
        detail[code] += to_int(r.get("amount_元")) or 0
        pg = to_int(r.get("page"))
        if pg is not None and (code not in page_of or pg < page_of[code]):
            page_of[code] = pg
    for code, amt in detail.items():
        out[f"revenue:{code}"] = {"amount": amt - known.get((year, code), 0), "level": "細目", "kind": "revenue",
                                  "code": code, "page": page_of.get(code)}
    for scode, kids in hierarchy_subitems(year).items():
        pages = [page_of[c] for c in kids if c in page_of]
        out[f"revenue:{scode}"] = {"amount": sum(out[f"revenue:{c}"]["amount"] for c in kids if f"revenue:{c}" in out),
                                   "level": "子目", "kind": "revenue", "code": scode,
                                   "page": min(pages) if pages else None}

    # plan：plans.csv 總額
    for r in read_csv(d / "plans.csv"):
        code = r["plan_code"].strip()
        amt = to_int(r.get("總額"))
        if amt is None:
            continue
        out[f"plan:{code}"] = {"amount": amt, "level": "工作計畫", "kind": "plan", "code": code,
                               "page": to_int(r.get("page_start"))}

    # object：expenditure_items.csv 依計畫＋用途別加總
    obj: dict[str, int] = defaultdict(int)
    obj_page: dict[str, int] = {}
    for r in read_csv(d / "expenditure_items.csv"):
        code = f"{r['plan_code'].strip()}|{r['用途別_code'].strip()}"
        obj[code] += to_int(r.get("amount_元")) or 0
        pg = to_int(r.get("page"))
        if pg is not None and (code not in obj_page or pg < obj_page[code]):
            obj_page[code] = pg
    for code, amt in obj.items():
        out[f"object:{code}"] = {"amount": amt, "level": "用途別", "kind": "object", "code": code,
                                 "page": obj_page.get(code)}
    return out


# ---------------------------------------------------------------- canonical key（契約 §3，自行實作）

def load_codes():
    p = ROOT / "data" / "crosswalk" / "codes.csv"
    return read_csv(p) if p.exists() else []


def build_step_maps(codes_rows):
    """{Y: (from_to: {from_code: to_code}, to_set: {to_code})}，僅取 to_year == from_year+1 的列。"""
    steps: dict[int, tuple[dict, set]] = {}
    for r in codes_rows:
        fy, ty = int(r["from_year"]), int(r["to_year"])
        if ty != fy + 1:
            continue
        m, s = steps.setdefault(fy, ({}, set()))
        m[r["from_code"]] = r["to_code"]
        s.add(r["to_code"])
    return steps


def canonical_of(kind: str, code: str, year: int, last_year: int, steps) -> str:
    """契約 §3.1~3.2：revenue 才套 crosswalk；其他 kind 原樣。"""
    if kind != "revenue":
        return f"{kind}:{code}"
    cur = code
    for y in range(year, last_year):
        if y not in steps:
            continue
        m, s = steps[y]
        if cur in m:
            cur = m[cur]
        elif cur in s:
            return f"revenue:{cur}@{y}"  # 進入 y+1 時斷鏈 → 斷鏈前代碼 @ y
    return f"revenue:{cur}"


def resolve(aliases: dict, year, key: str) -> str:
    """契約 §3「解析順序」：先查 aliases，查不到才直接當 canonical key。"""
    return aliases.get(f"{year}:{key}", key)


# ---------------------------------------------------------------- D1

def check_d1(series, recomputed, steps, last_year, res: Result):
    items = series["items"]
    years = series["years"]
    known = load_known_diffs()
    res.notes.append(f"`_known_diff`（corrections.csv，new=UNRESOLVED）目前登記 {len(known)} 筆；細目 ＝ 明細加總 − old。"
                     + ("".join(f"\n  - {y}年 {c}：{v:,}" for (y, c), v in sorted(known.items())) if known else ""))
    res.notes.append("子目的存在以 site/data/<年>.json 歲入階層節點為準（只取 code/level），金額＝其下細目 CSV 加總；"
                     "不在階層的細目只檢查細目本身。")
    covered: set[tuple[str, int]] = set()
    checked = 0
    for y in years:
        for okey, info in sorted(recomputed[y].items()):
            canon = canonical_of(info["kind"], info["code"], y, last_year, steps)
            covered.add((canon, y))
            it = items.get(canon)
            checked += 1
            if it is None:
                res.fail(f"{canon} {y}年：CSV 重算 {fmt(info['amount'])}（原始 key {okey}），series 沒有此 key")
                continue
            sv = it.get("amount_元", {}).get(str(y))
            if sv != info["amount"]:
                res.fail(f"{canon} {y}年：series {fmt(sv)} ≠ CSV 重算 {fmt(info['amount'])}（原始 key {okey}）")
            if it.get("kind") != info["kind"] or it.get("level") != info["level"]:
                res.fail(f"{canon} {y}年：kind/level series=({it.get('kind')},{it.get('level')}) "
                         f"≠ 重算=({info['kind']},{info['level']})")
    # series 有值但 CSV 重算沒有（憑空的值）
    for k, it in items.items():
        for ys, v in it.get("amount_元", {}).items():
            if v is not None and (k, int(ys)) not in covered:
                res.fail(f"{k} {ys}年：series {fmt(v)}，但 CSV 重算沒有對應項目")
        kind, code = split_key(k)
        if it.get("code") != code:
            res.fail(f"{k}：code 欄 {it.get('code')!r} ≠ 由 key 推得 {code!r}")
    res.notes.append(f"逐項重算 {checked} 個（年度×項目）。")


# ---------------------------------------------------------------- D2 / D3

def load_compares(series):
    out = []
    for p in sorted((ROOT / "site" / "data").glob("compare_*_*.json")):
        m = re.match(r"compare_(\d+)_(\d+)\.json$", p.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), load_json(p)))
    return out


def check_d2_d3(series, compares, r2: Result, r3: Result):
    items, aliases = series["items"], series["aliases"]
    n2 = n3 = 0
    for a, b, cmpj in compares:
        entries = cmpj.get("entries", {})
        for k, e in sorted(entries.items()):
            canon = resolve(aliases, a, k)
            it = items.get(canon)
            status = e.get("status")
            tag = f"compare_{a}_{b} {k}→{canon}"
            if it is None:
                r2.fail(f"{tag}：series 沒有此 key")
                r3.fail(f"{tag}：series 沒有此 key，無法比對有無資料")
                continue
            sa = it["amount_元"].get(str(a))
            sb = it["amount_元"].get(str(b))
            ca = (e.get("amount_元") or {}).get(str(a))
            cb = (e.get("amount_元") or {}).get(str(b))
            n2 += 1
            if status == "both":
                if sa != ca or sb != cb:
                    r2.fail(f"{tag}：金額 series {a}={fmt(sa)}／{b}={fmt(sb)} ≠ compare {a}={fmt(ca)}／{b}={fmt(cb)}")
                elif sa is not None and sb is not None:
                    d = sb - sa
                    if d != e.get("diff_元"):
                        r2.fail(f"{tag}：series 差額 {fmt(d)} ≠ compare diff_元 {fmt(e.get('diff_元'))}")
            # D3：有無資料與 status 一致（缺年份必為 null，不補 0）
            exp_a = status in ("both", f"only_{a}")
            exp_b = status in ("both", f"only_{b}")
            n3 += 1
            if status not in ("both", f"only_{a}", f"only_{b}"):
                r3.fail(f"{tag}：未知 status {status!r}")
            if (sa is not None) != exp_a:
                r3.fail(f"{tag}：{a}年 series={fmt(sa)}，compare status={status}（應{'有' if exp_a else '無'}資料）")
            if (sb is not None) != exp_b:
                r3.fail(f"{tag}：{b}年 series={fmt(sb)}，compare status={status}（應{'有' if exp_b else '無'}資料）")
    # 一般性：series 中任何金額為 0 的格子，不得是「該年沒有此項目」——以 page/name 缺席判斷
    for k, it in items.items():
        for ys, v in it["amount_元"].items():
            has_meta = ys in it.get("name", {})
            if v is None and has_meta:
                r3.fail(f"{k} {ys}年：有 name 但 amount_元 為 null")
            if v is not None and not has_meta:
                r3.fail(f"{k} {ys}年：amount_元={fmt(v)} 但沒有 name（疑似補值）")
    r2.notes.append(f"比對 {len(compares)} 份 compare 檔、{n2} 個 key。")
    r3.notes.append(f"檢查 {n3} 個 compare key 的有無資料；並檢查全部 series 項目 amount_元 與 name 的有無一致。")


# ---------------------------------------------------------------- D4

def selftest_algorithm(res: Result):
    """用契約 §6 的合成 codes 列，確認自己的 canonical 實作符合 §3 與 §6 的案例。"""
    rows = [
        {"from_year": "114", "from_code": "04-03", "to_year": "115", "to_code": "04-02"},
        {"from_year": "114", "from_code": "99-01", "to_year": "115", "to_code": "99-02"},
        {"from_year": "115", "from_code": "99-02", "to_year": "116", "to_code": "99-03"},
    ]
    steps = build_step_maps(rows)
    cases = [
        (114, "04-03", "revenue:04-02"), (114, "04-02", "revenue:04-02@114"),
        (115, "04-02", "revenue:04-02"), (116, "04-02", "revenue:04-02"),
        (114, "99-01", "revenue:99-03"), (115, "99-02", "revenue:99-03"), (116, "99-03", "revenue:99-03"),
        (114, "01", "revenue:01"),
    ]
    for y, c, exp in cases:
        got = canonical_of("revenue", c, y, 116, steps)
        if got != exp:
            res.fail(f"內建自測：{y}:{c} 應為 {exp}，實作得 {got}")
    # 115→116 不受 114 規則影響：116 的 04-02 與 115 的 04-02 都不被改碼
    if canonical_of("revenue", "04-02", 115, 116, steps) != "revenue:04-02":
        res.fail("內建自測：115→116 受到 114 規則影響")
    # plan 不套 crosswalk
    if canonical_of("plan", "04-02", 114, 116, steps) != "plan:04-02":
        res.fail("內建自測：plan 不應套 crosswalk")
    res.notes.append("內建自測：以契約 §6 的合成 codes 列驗證 canonical 演算法（改碼、被擠掉 `@114`、鏈式、115→116 不受影響）。")


def check_d4(series, recomputed, codes_rows, steps, last_year, res: Result):
    items, aliases, years = series["items"], series["aliases"], series["years"]
    selftest_algorithm(res)
    # 契約 §3.6／§3.7：codes.csv 本身合法性（build 應報錯的情況，這裡只當資料檢查）
    plan_codes = {info["code"] for y in years for k, info in recomputed[y].items() if info["kind"] == "plan"}
    for r in codes_rows:
        fy, ty = int(r["from_year"]), int(r["to_year"])
        if ty != fy + 1:
            res.fail(f"codes.csv 非相鄰年度列 {fy}→{ty}（{r['from_code']}→{r['to_code']}）：契約 §3.7 要求 build 報錯")
        for c in (r["from_code"], r["to_code"]):
            if c in plan_codes:
                res.fail(f"codes.csv 代碼 {c} 與計畫代碼相同：契約 §3.6 要求 build 報錯")
    # 期望的 aliases 與同年撞 key
    expected_aliases: dict[str, str] = {}
    for y in years:
        seen: dict[str, str] = {}
        for okey, info in recomputed[y].items():
            canon = canonical_of(info["kind"], info["code"], y, last_year, steps)
            if canon in seen and seen[canon] != okey:
                res.fail(f"同年撞 key：{y}年 {seen[canon]} 與 {okey} 都得到 {canon}")
            seen[canon] = okey
            if okey != canon:
                expected_aliases[f"{y}:{okey}"] = canon
    for ak, av in sorted(expected_aliases.items()):
        if ak not in aliases:
            res.fail(f"aliases 缺 {ak}（應為 {av}）")
        elif aliases[ak] != av:
            res.fail(f"aliases[{ak}] = {aliases[ak]}，應為 {av}")
    for ak, av in sorted(aliases.items()):
        if ak not in expected_aliases:
            res.fail(f"aliases 多出 {ak} → {av}（codes.csv 與 CSV 規則推不出）")
        y, _, okey = ak.partition(":")
        if okey == av:
            res.fail(f"aliases 收錄了原始 key = canonical key 的項目：{ak}")
        if av not in items:
            res.fail(f"aliases[{ak}] → {av} 不存在於 items")
    if list(aliases.keys()) != sorted(aliases.keys()):
        res.fail("aliases 沒有依字串遞增排序（契約 §3.5）")
    # items 順序（契約 §2）
    korder = {"revenue": 0, "plan": 1, "object": 2}
    lorder = {"款": 0, "項": 1, "子目": 2, "細目": 3}
    def sort_key(k):
        it = items[k]
        return (korder.get(it["kind"], 9), lorder.get(it["level"], 0) if it["kind"] == "revenue" else 0, k)
    if list(items.keys()) != sorted(items.keys(), key=sort_key):
        res.fail("items 順序不符契約 §2（kind → revenue level → key 遞增）")
    # 只有 codes.csv 登記的年度對被改碼：非 revenue 或非登記年度的項目不得出現在 aliases
    registered_years = {int(r["from_year"]) for r in codes_rows}
    for ak in aliases:
        y, _, okey = ak.partition(":")
        if not okey.startswith("revenue:"):
            res.fail(f"aliases 有非 revenue 的項目：{ak}（契約 §3.6 只對 revenue 套用）")
        elif not any(int(y) <= ry < last_year for ry in registered_years):
            res.fail(f"aliases {ak}：codes.csv 沒有登記涵蓋 {y}年 以後的年度對")
    # 被擠掉的項目：@<年> 後綴的 key 必須有 alias 指向，且後綴年度合理
    for k in items:
        m = re.search(r"@(\d+)$", k)
        if m:
            if int(m.group(1)) not in years:
                res.fail(f"{k}：@ 後綴年度不在 years")
            if not any(v == k for v in aliases.values()):
                res.fail(f"{k}：沒有任何 aliases 指向此 @ 後綴 key")
    res.notes.append(f"codes.csv 共 {len(codes_rows)} 列；期望 aliases {len(expected_aliases)} 筆，series 實有 {len(aliases)} 筆。")


# ---------------------------------------------------------------- D5

def check_d5(series, res: Result):
    items, years = series["items"], series["years"]
    known = load_known_diffs()
    exempt_notes = []

    def desc_known(k, ys, seen=None):
        tot = 0
        it = items.get(k)
        if not it:
            return 0
        kind, code = split_key(k)
        tot += known.get((int(ys), code), 0) if it.get("level") == "細目" else 0
        for c in it.get("children", {}).get(ys, []):
            tot += desc_known(c, ys)
        return tot

    unresolved_notes = []
    sum_checked = 0
    for y in years:
        ys = str(y)
        for k, it in sorted(items.items()):
            v = it["amount_元"].get(ys)
            if v is None:
                continue
            pk = it.get("parent_key", {}).get(ys)
            if ys in it.get("parent_key", {}) and pk is not None:
                p = items.get(pk)
                if p is None:
                    res.fail(f"{k} {y}年：parent_key {pk} 不存在於 items")
                elif p["amount_元"].get(ys) is None:
                    res.fail(f"{k} {y}年：parent_key {pk} 該年沒有值")
                elif k not in p.get("children", {}).get(ys, []):
                    res.fail(f"{k} {y}年：不在父項 {pk} 的 children[{y}] 內")
            kids = it.get("children", {}).get(ys, [])
            if it.get("unresolved", {}).get(ys):
                unresolved_notes.append(f"{k} {y}年 unresolved=true（已知差額，不隱藏）")
            if kids:
                tot = 0
                ok = True
                for c in kids:
                    ci = items.get(c)
                    if ci is None:
                        res.fail(f"{k} {y}年：children {c} 不存在於 items")
                        ok = False
                        continue
                    cv = ci["amount_元"].get(ys)
                    if cv is None:
                        res.fail(f"{k} {y}年：child {c} 該年沒有值")
                        ok = False
                        continue
                    if ci.get("parent_key", {}).get(ys) != k:
                        res.fail(f"{k} {y}年：child {c} 的 parent_key[{y}] = {ci.get('parent_key', {}).get(ys)}，不是 {k}")
                    tot += cv
                if ok:
                    sum_checked += 1
                    kd = desc_known(k, ys)
                    if tot != v and kd and abs(v - tot) == abs(kd):
                        exempt_notes.append(f"已知差額（`_known_diff` 登記，列出不隱藏）：{k} {y}年 父項 {fmt(v)}、子項加總 {fmt(tot)}、差 {fmt(v - tot)}")
                    elif tot != v:
                        res.fail(f"{k} {y}年：子項加總 {fmt(tot)} ≠ 父項 {fmt(v)}（差 {fmt(v - tot)}，{len(kids)} 個子項）")
        # children 反向：有 parent_key 的項目必須列在父項 children
    res.notes.extend(exempt_notes)
    res.notes.extend(unresolved_notes[:20])
    res.notes.append(f"逐年父子加總檢查 {sum_checked} 組（父項有子項者）。失敗列即「已知／未知差額」，一律列出；只有與 `_known_diff` 登記差額相符者才豁免（列於上方）；目前登記 0 筆。")


# ---------------------------------------------------------------- D6

def hash_tree(root: Path) -> dict[str, str]:
    out = {}
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def check_d6(res: Result):
    sd = ROOT / "site" / "data"
    before = hash_tree(sd)
    snaps = []
    for i in (1, 2):
        p = subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, capture_output=True, text=True)
        if p.returncode != 0:
            res.fail(f"build.py 第 {i} 次執行失敗（rc={p.returncode}）：{(p.stderr or p.stdout)[-300:].strip()}")
            return
        snaps.append(hash_tree(sd))
    diffs = sorted(k for k in set(snaps[0]) | set(snaps[1]) if snaps[0].get(k) != snaps[1].get(k))
    for k in diffs:
        res.fail(f"site/data/{k}：兩次 build 的內容不同")
    changed_vs_before = sorted(k for k in set(before) | set(snaps[1]) if before.get(k) != snaps[1].get(k))
    res.notes.append(f"兩次 build 之 site/data 雜湊 {'完全相同' if not diffs else '不同'}（{len(snaps[1])} 個檔案）。")
    if changed_vs_before:
        res.notes.append("與執行前相比有變動的檔案（可能因為執行前尚未 build 或 series.json 為新增）："
                         + ", ".join(changed_vs_before[:20]))


# ---------------------------------------------------------------- D7

def check_d7(series, recomputed, steps, res: Result):
    items, years = series["items"], series["years"]
    by_canon = {y: {canonical_of(i["kind"], i["code"], y, years[-1], steps): i for i in recomputed[y].values()}
                for y in years}
    rng = random.Random(SAMPLE_SEED)
    res.notes.append(f"固定 seed = {SAMPLE_SEED}；每年對 revenue／plan／object 各抽 {SAMPLE_PER_KIND} 項"
                     f"（共 {SAMPLE_PER_KIND * 3} 項）。「人工核對」欄留給人對照 raw／PDF 原件填寫，本腳本不判定。")
    for y in years:
        ys = str(y)
        rows = []
        for kind in ("revenue", "plan", "object"):
            pool = sorted(k for k, it in items.items() if it["kind"] == kind and it["amount_元"].get(ys) is not None)
            for k in rng.sample(pool, min(SAMPLE_PER_KIND, len(pool))):
                it = items[k]
                pg = it.get("page", {}).get(ys, {})
                pages = f"{pg.get('page_start')}–{pg.get('page_end')}" if pg else "—"
                info = by_canon[y].get(k)
                csv_amt = info["amount"] if info else None
                csv_page = info["page"] if info else None
                rows.append([f"`{k}`", it["level"], it["name"].get(ys, ""), fmt(it["amount_元"][ys]),
                             fmt(csv_amt), pages, fmt(csv_page), "☐"])
        res.tables.append((f"{y} 年抽樣清單", ["key", "層級", "名稱", "series 金額(元)", "CSV 重算(元)",
                                                "series 頁碼", "CSV 頁碼", "人工核對"], rows))


# ---------------------------------------------------------------- D8

def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def git_status():
    p = run(["git", "status", "--short"])
    return None if p.returncode != 0 else p.stdout


def snapshot_paths():
    snap = {}
    for sub in ("data", "reports", "site", "scripts", "tests"):
        for p in sorted((ROOT / sub).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and "node_modules" not in p.parts:
                snap[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return snap


VALIDATE_RE = {
    "plans": re.compile(r"歲出計畫通過 (\d+)/(\d+)"),
    "objects": re.compile(r"歲出用途別通過 (\d+)/(\d+)"),
    "dept": re.compile(r"機關別核對通過 (\d+)/(\d+)"),
    "conflicts": re.compile(r"跨表衝突 (\d+) 項"),
    "memos": re.compile(r"備註檢查通過 (\d+)/(\d+)"),
}


def check_d8(res: Result):
    status_before = git_status()
    snap_before = snapshot_paths()
    for year, base in VALIDATE_BASELINE.items():
        p = run([sys.executable, "scripts/validate.py", *base["args"]])
        out = p.stdout + p.stderr
        if p.returncode != 0:
            res.fail(f"validate.py {' '.join(base['args'])}：退出碼 {p.returncode}")
        got = {}
        for name, rx in VALIDATE_RE.items():
            m = rx.search(out)
            if not m:
                res.fail(f"validate.py {year}：輸出找不到「{name}」統計")
                continue
            got[name] = tuple(int(x) for x in m.groups()) if len(m.groups()) > 1 else int(m.group(1))
            if got[name] != base[name]:
                res.fail(f"validate.py {year} {name}：實際 {got[name]} ≠ CLAUDE.md 基準 {base[name]}")
        res.notes.append(f"validate {year}：{got}")
    p = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
    res.notes.append("unittest：rc=" + str(p.returncode) + "；" + " ".join(tail))
    if p.returncode != 0:
        res.fail(f"unittest discover 失敗（rc={p.returncode}）：{' / '.join(tail)}")
    status_after = git_status()
    snap_after = snapshot_paths()
    if status_before is None or status_after is None:
        res.notes.append("git status 無法執行（此環境 git 不可用），改以 data/reports/site/scripts/tests 檔案雜湊前後比對。")
    elif status_before != status_after:
        res.fail("git status --short 在 validate／unittest 前後不同：\n    前：" + status_before.strip().replace("\n", " | ")
                 + "\n    後：" + status_after.strip().replace("\n", " | "))
    else:
        res.notes.append("git status --short 前後相同。")
    changed = sorted(k for k in set(snap_before) | set(snap_after) if snap_before.get(k) != snap_after.get(k)
                     and k != "reports/check_series.md")
    for k in changed:
        res.fail(f"檔案內容在 validate／unittest 後改變：{k}")
    if not changed:
        res.notes.append("data/reports/site/scripts/tests 檔案雜湊前後相同。")


# ---------------------------------------------------------------- D9

def walk_nodes(nodes):
    for n in nodes:
        yield n
        yield from walk_nodes(n.get("children", []) or [])


def check_d9(series, compares, res: Result):
    items, aliases, years = series["items"], series["aliases"], series["years"]
    seen_by_year: dict[tuple[int, str], set] = defaultdict(set)  # (年, canonical) → 原始 key 集合
    total = 0

    def need(year: int, okey: str, where: str):
        nonlocal total
        total += 1
        canon = resolve(aliases, year, okey)
        seen_by_year[(year, canon)].add(okey)
        it = items.get(canon)
        if it is None:
            res.fail(f"{where}：{year}:{okey} → {canon} 不存在於 items")
        elif it["amount_元"].get(str(year)) is None:
            res.fail(f"{where}：{year}:{okey} → {canon} 存在但 {year}年 沒有資料（amount_元=null）")

    # (a) <年>.json drill
    for y in years:
        p = ROOT / "site" / "data" / f"{y}.json"
        if not p.exists():
            res.fail(f"缺少 site/data/{y}.json")
            continue
        j = load_json(p)
        for n in walk_nodes(j.get("revenue", {}).get("hierarchy", [])):
            if n.get("level") in ("款", "項", "子目", "細目") and n.get("code"):
                need(y, f"revenue:{n['code']}", f"{y}.json 歲入 drill")
        for n in walk_nodes(j.get("expenditure", {}).get("hierarchy", [])):
            lv = n.get("level")
            if lv == "工作計畫":
                need(y, f"plan:{n['code']}", f"{y}.json 歲出 drill")
            elif lv == "用途別":
                need(y, f"object:{n['plan_code']}|{n['用途別_code']}", f"{y}.json 歲出 drill")
    # (b) compare 檔
    for a, b, cj in compares:
        for k, e in cj.get("entries", {}).items():
            total += 1
            canon = resolve(aliases, a, k)
            seen_by_year[(a, canon)].add(k)
            it = items.get(canon)
            status = e.get("status")
            if it is None:
                res.fail(f"compare_{a}_{b}：{a}:{k} → {canon} 不存在於 items")
                continue
            for yy, want in ((a, status in ("both", f"only_{a}")), (b, status in ("both", f"only_{b}"))):
                if want and it["amount_元"].get(str(yy)) is None:
                    res.fail(f"compare_{a}_{b}：{a}:{k} → {canon} 於 {yy}年 應有資料但為 null")
    # (c) search.json
    sp = ROOT / "site" / "data" / "search.json"
    if sp.exists():
        for e in load_json(sp):
            kind, code, y = e.get("kind"), e.get("code"), e.get("year")
            if y not in years:
                continue
            okey = None
            if kind == "revenue":
                okey = f"revenue:{code}"          # 明細 → 細目
            elif kind in ("expenditure", "plan"):
                okey = f"plan:{code}"             # 明細與 plan → 工作計畫
            elif kind == "summary":
                if code and (e.get("text") or "").split(" ")[0] == REVENUE_SUMMARY_TABLE:
                    okey = f"revenue:{code}"      # 只限款／項
            if okey:
                need(y, okey, f"search.json {e.get('id')}")
    else:
        res.fail("缺少 site/data/search.json")
    # 恰好一個：同年兩個不同原始 key 不得解析到同一 canonical key
    for (y, canon), okeys in sorted(seen_by_year.items()):
        if len(okeys) > 1:
            res.fail(f"{y}年：原始 key {sorted(okeys)} 都解析到 {canon}（非唯一對應）")
    res.notes.append(f"共檢查 {total} 個入口 key（drill／compare／search）。解析規則：先查 aliases、再直接當 canonical key；"
                     "要求該 key 存在於 items 且該年有資料。")


# ---------------------------------------------------------------- 報告

def render(results: list[Result], series_path: Path, extra_notes: list[str]) -> str:
    lines = ["# series.json 獨立檢核報告（D1–D9）", "",
             f"- series 檔：`{series_path}`",
             "- 檢核腳本：`scripts/check_series.py`（不 import `build.py`，金額從 CSV 重算）",
             "- 不一致一律列出，不自動修正。", ""]
    lines += ["## 摘要", "", "| 項目 | 說明 | 結果 | 失敗筆數 |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.code} | {r.title} | {r.status} | {len(r.failures)} |")
    lines.append("")
    for r in results:
        lines += [f"## {r.code}　{r.title}　— {r.status}", ""]
        for n in r.notes:
            lines.append(f"- {n}")
        if r.failures:
            lines += ["", f"失敗明細（共 {len(r.failures)} 筆" + (f"，僅列前 {MAX_DETAIL_ROWS} 筆" if len(r.failures) > MAX_DETAIL_ROWS else "") + "）：", ""]
            for f in r.failures[:MAX_DETAIL_ROWS]:
                lines.append(f"- {f}")
        for title, head, rows in r.tables:
            lines += ["", f"### {title}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
            for row in rows:
                lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
        lines.append("")
    if extra_notes:
        lines += ["## 備註", ""] + [f"- {n}" for n in extra_notes] + [""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", default="site/data/series.json")
    ap.add_argument("--report", default="reports/check_series.md")
    ap.add_argument("--skip-build", action="store_true", help="跳過 D6（要跑兩次 build.py）")
    ap.add_argument("--skip-baseline", action="store_true", help="跳過 D8（要跑 validate.py 與 unittest）")
    args = ap.parse_args(argv)

    series_path = Path(args.series)
    if not series_path.is_absolute():
        series_path = ROOT / series_path
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    series = load_json(series_path)
    years = series["years"]
    last_year = years[-1]
    codes_rows = load_codes()
    steps = build_step_maps(codes_rows)
    recomputed = {y: recompute_year(y) for y in years}
    compares = load_compares(series)

    r1 = Result("D1", "金額從 CSV 重算並與 series 比對")
    r2 = Result("D2", "與 compare_*.json 交叉比對（金額、差額）")
    r3 = Result("D3", "沒有憑空補 0；有無資料與 compare status 一致")
    r4 = Result("D4", "crosswalk 行為與 aliases")
    r5 = Result("D5", "逐年階層一致與加總")
    r6 = Result("D6", "決定性：build.py 兩次輸出相同")
    r7 = Result("D7", "固定 seed 抽樣清單（供人工對照原件）")
    r8 = Result("D8", "既有基準不退步（validate／unittest）")
    r9 = Result("D9", "入口 key 可解析到恰好一個 canonical key")

    check_d1(series, recomputed, steps, last_year, r1)
    check_d2_d3(series, compares, r2, r3)
    check_d4(series, recomputed, codes_rows, steps, last_year, r4)
    check_d5(series, r5)
    if args.skip_build:
        r6.skip("以 --skip-build 略過（需執行兩次 build.py）。")
    else:
        check_d6(r6)
    check_d7(series, recomputed, steps, r7)
    if args.skip_baseline:
        r8.skip("以 --skip-baseline 略過（需執行 validate.py 與 unittest）。")
    else:
        check_d8(r8)
    check_d9(series, compares, r9)

    results = [r1, r2, r3, r4, r5, r6, r7, r8, r9]
    extra = []
    try:
        extra.append(f"series 檔案大小：{series_path.stat().st_size:,} bytes（上限 350KB = 358,400 bytes）。")
    except OSError:
        pass
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render(results, series_path, extra), encoding="utf-8")
    failed = [r.code for r in results if r.status == "失敗"]
    print(f"[check_series] 報告：{report_path}")
    for r in results:
        print(f"  {r.code} {r.status}（失敗 {len(r.failures)}）{r.title}")
    if failed:
        print("[check_series] 失敗：" + ", ".join(failed))
        return 1
    print("[check_series] 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
