#!/usr/bin/env python3
"""跨年度預算明細項目配對工具 (match_items.py)。

功能說明：
1. 讀取兩個年度的歲入明細 (`data/<year>/revenue_items.csv`) 與歲出明細 (`data/<year>/expenditure_items.csv`)。
2. 透過 `data/crosswalk/codes.csv` 將舊年度 (`from_year`) 的科目/計畫編號對應至新年度 (`to_year`) 的編號，
   以此界定配對的 `scope_key`：
   - 歲入 (`revenue`)：`scope_key` 為細目 `code`（經 crosswalk 對應至新年度編號）。
   - 歲出 (`expenditure`)：`scope_key` 為 `{plan_code}+{用途別_code}`（其中 `plan_code` 經 crosswalk 對應至新年度編號）。
3. 說明文字組合規則與設計理由：
   - 歲入：取 `name` 與 `note` 以空白串接（若 `note` 為空則僅取 `name`）。
     理由：歲入明細的 `note` 常僅記載通用法源或簡短依據（例如多個細目皆為「依據前三年度決算預估數。」），
     單靠 `note` 容易與性質相異的項目混淆，而補助款等細目的具體項目則記載於 `note`；結合 `name` 與 `note`
     能完整保留細目名稱與明細內容，提升跨年度比對的精確度。
   - 歲出：僅取 `說明` 欄位文字。
     理由：歲出明細的 `用途別` 屬於費用分類且已納入 `scope_key`（`{plan_code}+{用途別_code}`），而每筆明細的
     具體施政內容、工程或補助項目皆完整記載於 `說明` 欄位，直接取 `說明` 即可精確比對，避免用途別名稱造成相似度膨脹。
4. 說明文字正規化規則 (`normalize_text`)：
   - 移除括號內含發文字號之完整備註（如 `(依據...字第...號函...)`），以及獨立出現的公文日期與字號（如 `115.9.29屏府...字第...號函辦理`）。
   - 將年度字樣（如 `114學年度`、`115年度`、`116年`）統一替換為 `<年>`。
   - 移除所有中英文標點符號與空白字元。
5. 配對與輸出規則：
   - 僅在相同 `(kind, scope_key)` 範圍內進行一對一配對。
   - 正規化後文字完全相同（且非空）者：狀態為 `exact`（相似度 `1.0000`），自動寫入 `data/crosswalk/items.csv` 並共用穩定 `item_id`。
   - 其餘未配對項目計算 `difflib.SequenceMatcher` 相似度，由高至低（同分時依 `from_item_seq`、`to_item_seq` 升冪）貪婪配對：
     相似度 `>= 0.75` 者狀態為 `candidate`，寫入 `data/crosswalk/items_candidates.csv`，**不會**自動併入 `items.csv`。
   - 相似度 `< 0.75` 或無法配對者：舊年度項目列為 `deleted`，新年度項目列為 `added`，均寫入 `items_candidates.csv`。
"""

from __future__ import annotations

import argparse
import csv
import difflib
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple


CANDIDATE_THRESHOLD = 0.75

CANDIDATES_FIELDNAMES = [
    "kind",
    "scope_key",
    "from_year",
    "from_item_seq",
    "to_year",
    "to_item_seq",
    "status",
    "similarity",
    "from_text",
    "to_text",
]

ITEMS_FIELDNAMES = [
    "item_id",
    "kind",
    "year",
    "scope_key",
    "item_seq",
]

# 1. 括號內含「字第...號函」的整個括號區塊（支援全形與半形括號）
_PAREN_DOC_NO_RE = re.compile(
    r"[（(][^（）()]*?字第\s*[0-9A-Za-z\-一二三四五六七八九十]+\s*號函[^（）()]*?[）)]"
)

# 2. 非括號內的公文依據與字號，分為三種子型態以免誤吃前方說明本文：
#    (a) 以「依據」或「依」為前導（如「依屏府環衛字第1159019686號函核定」）
#    (b) 帶有公文日期（如「115.9.29屏府財稅財字第1150571040號函」）
#    (c) 直接接「發文機關簡稱+字軌+字第+文號+號函」（如「屏府財字第12號函」，機關簡稱以府/部/局/處/署/會/所/院結尾）
_AGENCY_PREFIX = (
    r"(?:(?:屏東縣|萬巒鄉)?(?:(?:縣|市|鄉|鎮|區|中央|省)?(?:政府|公所)"
    r"|(?:財政|教育|內政|交通|農業|文化|經濟|勞動|衛福|衛生福利|環境保護|環保|國民及學前教育|國教|公路|水利|農糧|稅務|財稅|客家|原住民族|客委|原民)(?:部|局|處|署|委員會|會)"
    r"|[\u4e00-\u9fff](?:府|部|局|處|署|會|所|院))"
    r"|[臺台](?:財|教|內|農|交|經|衛|環|文|勞|客|原)"
    r"|屏環)"
)
_DOC_DATE = r"(?:\d{2,3}\s*(?:[\./]\s*\d{1,2}\s*[\./]\s*\d{1,2}|年\s*\d{1,2}\s*月\s*\d{1,2}\s*日))"
_DOC_NO_TAIL = (
    r"字第\s*[0-9A-Za-z\-一二三四五六七八九十]+\s*號函"
    r"(?:核定補助|同意補助|辦理|補助|預估|核定)?"
)
_INLINE_DOC_NO_RE = re.compile(
    r"(?:依據|依)(?:[\u4e00-\u9fff]{0,12}?" + _DOC_DATE + r"\s*)?[^\s,，。；;（）()依]{1,8}" + _DOC_NO_TAIL
    + r"|"
    + r"(?:" + _AGENCY_PREFIX + r"\s*)?" + _DOC_DATE + r"\s*[\u4e00-\u9fff]{1,8}" + _DOC_NO_TAIL
    + r"|"
    + _AGENCY_PREFIX + r"[\u4e00-\u9fff]{0,4}" + _DOC_NO_TAIL
)

# 3. 民國年度字樣（2~3位數 + 學年度/年度/年，避免誤傷「1年」等數量詞，限定 2~3 位數民國年如 80~199）
_YEAR_TOKEN_RE = re.compile(r"(?<!\d)(?:[89]\d|1\d{2})\s*(?:學年度|年度|年)")

# 4. 標點符號與空白字元（保留中文、英數及 `<年>` 標記）
_PUNCT_WS_RE = re.compile(
    r"[\s\u3000,，.。、;；:：!！?？'\"‘’“”「」『』（）()\[\]【】《》〈〉\-—_~～/\\|+*&^%$#@=`]+"
)


def normalize_text(text: str) -> str:
    """正規化說明文字：移除函文字號、將民國年度替換為 `<年>`、移除標點與空白。"""
    if not text:
        return ""
    cleaned = _PAREN_DOC_NO_RE.sub(" ", text)
    cleaned = _INLINE_DOC_NO_RE.sub(" ", cleaned)
    cleaned = _YEAR_TOKEN_RE.sub("<年>", cleaned)
    cleaned = _PUNCT_WS_RE.sub("", cleaned)
    return cleaned


def load_code_crosswalk(
    crosswalk_dir: Path, from_year: str, to_year: str
) -> Dict[str, str]:
    """讀取 `data/crosswalk/codes.csv`，回傳 `from_code -> to_code` 對照字典。"""
    codes_path = crosswalk_dir / "codes.csv"
    mapping: Dict[str, str] = {}
    if not codes_path.exists():
        return mapping

    with codes_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fy = (row.get("from_year") or "").strip()
            ty = (row.get("to_year") or "").strip()
            fc = (row.get("from_code") or "").strip()
            tc = (row.get("to_code") or "").strip()
            if fy == str(from_year) and ty == str(to_year) and fc and tc:
                mapping[fc] = tc
    return mapping


def _extract_revenue_text(row: Dict[str, str]) -> str:
    name = (row.get("name") or "").strip()
    note = (row.get("note") or "").strip()
    if name and note:
        return f"{name} {note}"
    return name or note


def _extract_expenditure_text(row: Dict[str, str]) -> str:
    return (row.get("說明") or "").strip()


class BudgetItem:
    """代表單一年度的一筆明細項目。"""

    def __init__(
        self,
        kind: str,
        year: str,
        raw_scope_key: str,
        match_scope_key: str,
        item_seq: int,
        text: str,
        norm_text: str,
    ) -> None:
        self.kind = kind
        self.year = year
        self.raw_scope_key = raw_scope_key
        self.match_scope_key = match_scope_key
        self.item_seq = item_seq
        self.text = text
        self.norm_text = norm_text


def _load_year_items(
    data_dir: Path,
    year: str,
    code_map: Optional[Dict[str, str]] = None,
) -> List[BudgetItem]:
    """讀取指定年度的歲入與歲出明細。若提供 `code_map`，會將 `match_scope_key` 中的編號轉換為新年度編號。"""
    year_dir = data_dir / str(year)
    items: List[BudgetItem] = []
    code_map = code_map or {}

    rev_path = year_dir / "revenue_items.csv"
    if rev_path.exists():
        with rev_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_code = (row.get("code") or "").strip()
                mapped_code = code_map.get(raw_code, raw_code)
                seq_str = (row.get("item_seq") or "0").strip()
                item_seq = int(seq_str)
                text = _extract_revenue_text(row)
                items.append(
                    BudgetItem(
                        kind="revenue",
                        year=str(year),
                        raw_scope_key=raw_code,
                        match_scope_key=mapped_code,
                        item_seq=item_seq,
                        text=text,
                        norm_text=normalize_text(text),
                    )
                )

    exp_path = year_dir / "expenditure_items.csv"
    if exp_path.exists():
        with exp_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_plan = (row.get("plan_code") or "").strip()
                mapped_plan = code_map.get(raw_plan, raw_plan)
                purpose_code = (row.get("用途別_code") or "").strip()
                raw_scope = f"{raw_plan}+{purpose_code}"
                match_scope = f"{mapped_plan}+{purpose_code}"
                seq_str = (row.get("item_seq") or "0").strip()
                item_seq = int(seq_str)
                text = _extract_expenditure_text(row)
                items.append(
                    BudgetItem(
                        kind="expenditure",
                        year=str(year),
                        raw_scope_key=raw_scope,
                        match_scope_key=match_scope,
                        item_seq=item_seq,
                        text=text,
                        norm_text=normalize_text(text),
                    )
                )

    return items


def _match_scope_group(
    kind: str,
    scope_key: str,
    from_year: str,
    to_year: str,
    from_items: List[BudgetItem],
    to_items: List[BudgetItem],
) -> Tuple[List[Dict[str, str]], List[Tuple[BudgetItem, BudgetItem]]]:
    """在單一 `(kind, scope_key)` 內進行配對。

    回傳：
      - candidate_rows: 寫入 `items_candidates.csv` 的列資料清單
      - exact_pairs: `(from_item, to_item)` 的 exact 配對清單（供寫入 `items.csv`）
    """
    from_sorted = sorted(from_items, key=lambda x: x.item_seq)
    to_sorted = sorted(to_items, key=lambda x: x.item_seq)

    used_from = set()
    used_to = set()
    records: List[ Tuple[Tuple[int, int, int], Dict[str, str]] ] = []
    exact_pairs: List[Tuple[BudgetItem, BudgetItem]] = []

    # Step 1: 正規化文字完全相同 -> exact match (依 item_seq 順序一對一配對)
    for i, f_item in enumerate(from_sorted):
        if not f_item.norm_text:
            continue
        for j, t_item in enumerate(to_sorted):
            if j in used_to:
                continue
            if f_item.norm_text == t_item.norm_text:
                used_from.add(i)
                used_to.add(j)
                exact_pairs.append((f_item, t_item))
                records.append(
                    (
                        (0, f_item.item_seq, t_item.item_seq),
                        {
                            "kind": kind,
                            "scope_key": scope_key,
                            "from_year": str(from_year),
                            "from_item_seq": str(f_item.item_seq),
                            "to_year": str(to_year),
                            "to_item_seq": str(t_item.item_seq),
                            "status": "exact",
                            "similarity": "1.0000",
                            "from_text": f_item.text,
                            "to_text": t_item.text,
                        },
                    )
                )
                break

    # Step 2: 剩餘項目計算 difflib 相似度，篩選 >= 0.75 的候選配對
    scored_pairs: List[Tuple[float, int, int, int, int]] = []
    for i, f_item in enumerate(from_sorted):
        if i in used_from or not f_item.norm_text:
            continue
        for j, t_item in enumerate(to_sorted):
            if j in used_to or not t_item.norm_text:
                continue
            sim = difflib.SequenceMatcher(
                None, f_item.norm_text, t_item.norm_text
            ).ratio()
            if sim >= CANDIDATE_THRESHOLD:
                # 排序鍵：相似度由高到低，若同分則依 from_item_seq, to_item_seq 升冪
                scored_pairs.append((-round(sim, 8), f_item.item_seq, t_item.item_seq, i, j))

    scored_pairs.sort()
    for neg_sim, _, _, i, j in scored_pairs:
        if i in used_from or j in used_to:
            continue
        used_from.add(i)
        used_to.add(j)
        f_item = from_sorted[i]
        t_item = to_sorted[j]
        sim = difflib.SequenceMatcher(
            None, f_item.norm_text, t_item.norm_text
        ).ratio()
        records.append(
            (
                (1, f_item.item_seq, t_item.item_seq),
                {
                    "kind": kind,
                    "scope_key": scope_key,
                    "from_year": str(from_year),
                    "from_item_seq": str(f_item.item_seq),
                    "to_year": str(to_year),
                    "to_item_seq": str(t_item.item_seq),
                    "status": "candidate",
                    "similarity": f"{sim:.4f}",
                    "from_text": f_item.text,
                    "to_text": t_item.text,
                },
            )
        )

    # Step 3: 未配對的舊年度項目 -> deleted
    for i, f_item in enumerate(from_sorted):
        if i not in used_from:
            records.append(
                (
                    (2, f_item.item_seq, 0),
                    {
                        "kind": kind,
                        "scope_key": scope_key,
                        "from_year": str(from_year),
                        "from_item_seq": str(f_item.item_seq),
                        "to_year": str(to_year),
                        "to_item_seq": "",
                        "status": "deleted",
                        "similarity": "0.0000",
                        "from_text": f_item.text,
                        "to_text": "",
                    },
                )
            )

    # Step 4: 未配對的新年度項目 -> added
    for j, t_item in enumerate(to_sorted):
        if j not in used_to:
            records.append(
                (
                    (3, 0, t_item.item_seq),
                    {
                        "kind": kind,
                        "scope_key": scope_key,
                        "from_year": str(from_year),
                        "from_item_seq": "",
                        "to_year": str(to_year),
                        "to_item_seq": str(t_item.item_seq),
                        "status": "added",
                        "similarity": "0.0000",
                        "from_text": "",
                        "to_text": t_item.text,
                    },
                )
            )

    records.sort(key=lambda x: x[0])
    return [r[1] for r in records], exact_pairs


def _update_items_csv(
    crosswalk_dir: Path, exact_pairs: List[Tuple[BudgetItem, BudgetItem]]
) -> None:
    """將 `exact` 配對寫入 `data/crosswalk/items.csv`，共用穩定的 `item_id`。

    注意：僅寫入 `exact` 配對；`candidate`、`deleted`、`added` 均不寫入。
    若 `items.csv` 已存在，會保留既有紀錄並沿用已存在的 `item_id`，確保重跑結果一致（deterministic）。
    """
    items_path = crosswalk_dir / "items.csv"
    existing_rows: List[Dict[str, str]] = []
    # key: (kind, year, scope_key, item_seq) -> item_id
    lookup_id: Dict[Tuple[str, str, str, str], str] = {}
    used_ids = set()

    if items_path.exists():
        with items_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_id = (row.get("item_id") or "").strip()
                kind = (row.get("kind") or "").strip()
                year = (row.get("year") or "").strip()
                scope_key = (row.get("scope_key") or "").strip()
                item_seq = (row.get("item_seq") or "").strip()
                if not (item_id and kind and year and scope_key and item_seq):
                    continue
                key = (kind, year, scope_key, item_seq)
                if key not in lookup_id:
                    lookup_id[key] = item_id
                    used_ids.add(item_id)
                    existing_rows.append(
                        {
                            "item_id": item_id,
                            "kind": kind,
                            "year": year,
                            "scope_key": scope_key,
                            "item_seq": item_seq,
                        }
                    )

    for f_item, t_item in exact_pairs:
        f_key = (
            f_item.kind,
            str(f_item.year),
            f_item.raw_scope_key,
            str(f_item.item_seq),
        )
        t_key = (
            t_item.kind,
            str(t_item.year),
            t_item.raw_scope_key,
            str(t_item.item_seq),
        )

        item_id = lookup_id.get(f_key) or lookup_id.get(t_key)
        if not item_id:
            prefix = "REV" if f_item.kind == "revenue" else "EXP"
            base_id = f"{prefix}-{t_item.match_scope_key}-{f_item.year}-{f_item.item_seq:03d}"
            item_id = base_id
            counter = 2
            while item_id in used_ids:
                item_id = f"{base_id}-{counter}"
                counter += 1
            used_ids.add(item_id)

        if f_key not in lookup_id:
            lookup_id[f_key] = item_id
            existing_rows.append(
                {
                    "item_id": item_id,
                    "kind": f_item.kind,
                    "year": str(f_item.year),
                    "scope_key": f_item.raw_scope_key,
                    "item_seq": str(f_item.item_seq),
                }
            )
        if t_key not in lookup_id:
            lookup_id[t_key] = item_id
            existing_rows.append(
                {
                    "item_id": item_id,
                    "kind": t_item.kind,
                    "year": str(t_item.year),
                    "scope_key": t_item.raw_scope_key,
                    "item_seq": str(t_item.item_seq),
                }
            )

    # 依固定順序排序，確保每次執行輸出完全一致
    kind_order = {"revenue": 0, "expenditure": 1}
    existing_rows.sort(
        key=lambda r: (
            kind_order.get(r["kind"], 99),
            r["item_id"],
            int(r["year"]) if r["year"].isdigit() else r["year"],
            r["scope_key"],
            int(r["item_seq"]) if r["item_seq"].isdigit() else 0,
        )
    )

    crosswalk_dir.mkdir(parents=True, exist_ok=True)
    with items_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ITEMS_FIELDNAMES)
        writer.writeheader()
        writer.writerows(existing_rows)


def match_items(from_year: str, to_year: str, data_dir: Path | str = Path("data")) -> List[Dict[str, str]]:
    """執行兩個年度的明細項目配對，並輸出 `items_candidates.csv` 與更新 `items.csv`。"""
    data_path = Path(data_dir)
    crosswalk_dir = data_path / "crosswalk"
    code_map = load_code_crosswalk(crosswalk_dir, str(from_year), str(to_year))

    from_items = _load_year_items(data_path, str(from_year), code_map=code_map)
    to_items = _load_year_items(data_path, str(to_year), code_map=None)

    # 依 (kind, match_scope_key) 分組
    groups: Dict[Tuple[str, str], Tuple[List[BudgetItem], List[BudgetItem]]] = {}
    for item in from_items:
        key = (item.kind, item.match_scope_key)
        if key not in groups:
            groups[key] = ([], [])
        groups[key][0].append(item)
    for item in to_items:
        key = (item.kind, item.match_scope_key)
        if key not in groups:
            groups[key] = ([], [])
        groups[key][1].append(item)

    kind_order = {"revenue": 0, "expenditure": 1}
    sorted_keys = sorted(groups.keys(), key=lambda k: (kind_order.get(k[0], 99), k[1]))

    all_candidate_rows: List[Dict[str, str]] = []
    all_exact_pairs: List[Tuple[BudgetItem, BudgetItem]] = []

    for kind, scope_key in sorted_keys:
        f_list, t_list = groups[(kind, scope_key)]
        rows, exact_pairs = _match_scope_group(
            kind=kind,
            scope_key=scope_key,
            from_year=str(from_year),
            to_year=str(to_year),
            from_items=f_list,
            to_items=t_list,
        )
        all_candidate_rows.extend(rows)
        all_exact_pairs.extend(exact_pairs)

    crosswalk_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = crosswalk_dir / "items_candidates.csv"
    with candidates_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATES_FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_candidate_rows)

    _update_items_csv(crosswalk_dir, all_exact_pairs)
    return all_candidate_rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="跨年度預算明細項目配對工具 (產生 items_candidates.csv 並將 exact 配對寫入 items.csv)"
    )
    parser.add_argument("from_year", help="舊年度（例如 115）")
    parser.add_argument("to_year", help="新年度（例如 116）")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="資料根目錄路徑（預設為 data，測試時可指定暫存目錄）",
    )
    args = parser.parse_args(argv)
    match_items(args.from_year, args.to_year, data_dir=Path(args.data_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
