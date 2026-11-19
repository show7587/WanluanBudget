"""Independent verification tests for memos.json output (A1) and build-time validation (A2)."""

from __future__ import annotations

import copy
import csv
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.build import build
from scripts.memos import MEMO_COLUMNS

_REV_SEARCH_ID_RE = re.compile(r"^(\d+)-revenue-([^-]+)-(\d+)$")
_EXP_SEARCH_ID_RE = re.compile(r"^(\d+)-expenditure-([^-]+)-([^-]+)-(\d+)$")
_INT_FIELDS = ("year", "page", "pdf_page")


def _read_csv_exact(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def verify_memos_targets(
    memos_data: dict[str, Any],
    data_dir: Path,
    search_docs: list[dict[str, Any]],
    reference_by_year: dict[int, dict[str, Any]],
) -> list[str]:
    """Independently verify every memo target in memos_data against CSVs, search.json, and reference JSONs.

    Does NOT reuse any target-resolution helpers from scripts/build.py.
    Returns a list of error messages (empty list means all checks passed).
    """
    errors: list[str] = []
    search_by_id = {doc["id"]: doc for doc in search_docs}

    csv_cache: dict[tuple[int, str], list[dict[str, str]]] = {}

    def get_csv(year: int, filename: str) -> list[dict[str, str]]:
        key = (year, filename)
        if key not in csv_cache:
            p = data_dir / str(year) / filename
            csv_cache[key] = _read_csv_exact(p) if p.is_file() else []
        return csv_cache[key]

    ref_cells_cache: dict[int, set[tuple[int, int, int]]] = {}
    for y, ref_obj in reference_by_year.items():
        ref_cells_cache[y] = {
            (t["page"], c["r"], c["c"])
            for t in ref_obj.get("tables", [])
            for c in t.get("cells", [])
        }

    for y_str, items in memos_data.get("years", {}).items():
        for m in items:
            mid = m.get("memo_id", "<missing>")
            year = m.get("year")
            page = m.get("page")
            scope = m.get("scope")
            locator = m.get("locator", "")
            target = m.get("target") or {}

            if str(year) != y_str:
                errors.append(f"{mid}: year={year} does not match group key {y_str!r}")
                continue

            if scope == "revenue_item":
                if target.get("kind") != "revenue":
                    errors.append(f"{mid}: expected target.kind='revenue', got {target.get('kind')!r}")
                    continue
                sid = target.get("search_id", "")
                match = _REV_SEARCH_ID_RE.match(sid)
                if not match:
                    errors.append(f"{mid}: invalid revenue search_id format {sid!r}")
                    continue
                sid_year, sid_code, sid_seq = int(match.group(1)), match.group(2), int(match.group(3))
                loc_parts = locator.split(":")
                if len(loc_parts) != 2:
                    errors.append(f"{mid}: invalid revenue_item locator {locator!r}")
                    continue
                loc_code, loc_seq_str = loc_parts
                try:
                    loc_seq = int(loc_seq_str)
                except ValueError:
                    errors.append(f"{mid}: non-integer item_seq in locator {locator!r}")
                    continue

                if (sid_year, sid_code, sid_seq) != (year, loc_code, loc_seq):
                    errors.append(
                        f"{mid}: search_id parsed {(sid_year, sid_code, sid_seq)} != locator {(year, loc_code, loc_seq)}"
                    )

                doc = search_by_id.get(sid)
                if doc is None:
                    errors.append(f"{mid}: search_id {sid!r} not found in search.json")
                    continue
                if doc.get("kind") != "revenue":
                    errors.append(f"{mid}: search doc kind={doc.get('kind')!r} != 'revenue'")
                if doc.get("code") != loc_code:
                    errors.append(f"{mid}: search doc code={doc.get('code')!r} != {loc_code!r}")
                if doc.get("page") != page:
                    errors.append(f"{mid}: search doc page={doc.get('page')!r} != memo page={page!r}")

                rev_rows = [
                    r
                    for r in get_csv(year, "revenue_items.csv")
                    if r.get("code") == loc_code and r.get("item_seq") == str(loc_seq)
                ]
                if len(rev_rows) != 1:
                    errors.append(
                        f"{mid}: expected 1 row in revenue_items.csv for ({loc_code}, {loc_seq}), got {len(rev_rows)}"
                    )
                    continue
                row = rev_rows[0]
                if int(row["page"]) != page:
                    errors.append(f"{mid}: revenue CSV page={row['page']} != memo page={page}")
                if doc.get("text") != row["note"]:
                    errors.append(
                        f"{mid}: search doc text {doc.get('text')!r} != CSV note {row['note']!r}"
                    )

            elif scope == "expenditure_item":
                if target.get("kind") != "expenditure":
                    errors.append(f"{mid}: expected target.kind='expenditure', got {target.get('kind')!r}")
                    continue
                sid = target.get("search_id", "")
                match = _EXP_SEARCH_ID_RE.match(sid)
                if not match:
                    errors.append(f"{mid}: invalid expenditure search_id format {sid!r}")
                    continue
                sid_year = int(match.group(1))
                sid_plan = match.group(2)
                sid_use = match.group(3)
                sid_seq = int(match.group(4))

                loc_parts = locator.split(":")
                if len(loc_parts) != 3:
                    errors.append(f"{mid}: invalid expenditure_item locator {locator!r}")
                    continue
                loc_plan, loc_use, loc_seq_str = loc_parts
                try:
                    loc_seq = int(loc_seq_str)
                except ValueError:
                    errors.append(f"{mid}: non-integer item_seq in locator {locator!r}")
                    continue

                if (sid_year, sid_plan, sid_use, sid_seq) != (year, loc_plan, loc_use, loc_seq):
                    errors.append(
                        f"{mid}: search_id parsed {(sid_year, sid_plan, sid_use, sid_seq)} "
                        f"!= locator {(year, loc_plan, loc_use, loc_seq)}"
                    )

                exp_rows = [
                    r
                    for r in get_csv(year, "expenditure_items.csv")
                    if r.get("plan_code") == loc_plan
                    and r.get("用途別_code") == loc_use
                    and r.get("item_seq") == str(loc_seq)
                ]
                if len(exp_rows) != 1:
                    errors.append(
                        f"{mid}: expected 1 row in expenditure_items.csv for ({loc_plan}, {loc_use}, {loc_seq}), "
                        f"got {len(exp_rows)}"
                    )
                    continue
                row = exp_rows[0]
                if int(row["page"]) != page:
                    errors.append(f"{mid}: expenditure CSV page={row['page']} != memo page={page}")

                doc = search_by_id.get(sid)
                if doc is None:
                    errors.append(f"{mid}: search_id {sid!r} not found in search.json")
                    continue
                if doc.get("kind") != "expenditure":
                    errors.append(f"{mid}: search doc kind={doc.get('kind')!r} != 'expenditure'")
                if doc.get("code") != row["plan_code"]:
                    errors.append(f"{mid}: search doc code={doc.get('code')!r} != {row['plan_code']!r}")
                if doc.get("用途別_code") != row["用途別_code"]:
                    errors.append(
                        f"{mid}: search doc 用途別_code={doc.get('用途別_code')!r} != {row['用途別_code']!r}"
                    )
                if doc.get("page") != int(row["page"]):
                    errors.append(f"{mid}: search doc page={doc.get('page')!r} != CSV page={row['page']}")
                if doc.get("text") != row["說明"]:
                    errors.append(
                        f"{mid}: search doc text {doc.get('text')!r} != CSV 說明 {row['說明']!r}"
                    )

            elif scope == "plan":
                if target.get("kind") != "plan":
                    errors.append(f"{mid}: expected target.kind='plan', got {target.get('kind')!r}")
                    continue
                sid = target.get("search_id", "")
                doc = search_by_id.get(sid)
                if doc is None:
                    errors.append(f"{mid}: search_id {sid!r} not found in search.json")
                    continue
                if doc.get("kind") != "plan":
                    errors.append(f"{mid}: search doc kind={doc.get('kind')!r} != 'plan'")
                if doc.get("code") != locator:
                    errors.append(f"{mid}: search doc code={doc.get('code')!r} != locator {locator!r}")

            elif scope == "summary":
                if target.get("kind") != "summary":
                    errors.append(f"{mid}: expected target.kind='summary', got {target.get('kind')!r}")
                    continue
                sid = target.get("search_id", "")
                doc = search_by_id.get(sid)
                if doc is None:
                    errors.append(f"{mid}: search_id {sid!r} not found in search.json")
                    continue
                if doc.get("kind") != "summary":
                    errors.append(f"{mid}: search doc kind={doc.get('kind')!r} != 'summary'")
                if doc.get("name") != target.get("科目名稱"):
                    errors.append(
                        f"{mid}: search doc name={doc.get('name')!r} != target 科目名稱 {target.get('科目名稱')!r}"
                    )
                if doc.get("page") != page:
                    errors.append(f"{mid}: search doc page={doc.get('page')!r} != memo page={page!r}")

                src_table = target.get("source_table")
                subj = target.get("科目名稱")
                sum_rows = [
                    r
                    for r in get_csv(year, "summary.csv")
                    if r.get("source_table") == src_table
                    and r.get("科目名稱") == subj
                    and r.get("page") == str(page)
                ]
                if len(sum_rows) != 1:
                    errors.append(
                        f"{mid}: expected 1 row in summary.csv for ({src_table}, {subj}, p{page}), got {len(sum_rows)}"
                    )

            elif scope == "reference_cell":
                if target.get("kind") != "reference":
                    errors.append(f"{mid}: expected target.kind='reference', got {target.get('kind')!r}")
                    continue
                t_page = target.get("page")
                t_row = target.get("row")
                t_col = target.get("col")
                if t_page != page:
                    errors.append(f"{mid}: target.page={t_page} != memo page={page}")
                if (t_page, t_row, t_col) not in ref_cells_cache.get(year, set()):
                    errors.append(
                        f"{mid}: reference cell (page={t_page}, r={t_row}, c={t_col}) not found in reference_{year}.json"
                    )

            elif scope == "page":
                if target.get("kind") != "page":
                    errors.append(f"{mid}: expected target.kind='page', got {target.get('kind')!r}")
                if target.get("page") != page:
                    errors.append(f"{mid}: target.page={target.get('page')} != memo page={page}")

            else:
                errors.append(f"{mid}: unknown scope {scope!r}")

    return errors


def verify_memos_exact_fields(memos_data: dict[str, Any], csv_path: Path) -> list[str]:
    """Verify every field in memos_data matches data/memos.csv verbatim (no stripping/normalization)."""
    errors: list[str] = []
    csv_rows = _read_csv_exact(csv_path)
    csv_by_id = {r["memo_id"]: r for r in csv_rows}

    json_by_id: dict[str, dict[str, Any]] = {}
    for items in memos_data.get("years", {}).values():
        for m in items:
            json_by_id[m["memo_id"]] = m

    if set(json_by_id.keys()) != set(csv_by_id.keys()):
        errors.append(
            f"memo_id set mismatch: only_in_json={set(json_by_id) - set(csv_by_id)}, "
            f"only_in_csv={set(csv_by_id) - set(json_by_id)}"
        )
        return errors

    for mid, csv_row in csv_by_id.items():
        jm = json_by_id[mid]
        for col in MEMO_COLUMNS:
            if col in _INT_FIELDS:
                val = jm.get(col)
                if type(val) is not int:
                    errors.append(f"{mid}.{col}: expected int, got {type(val).__name__} ({val!r})")
                elif val != int(csv_row[col]):
                    errors.append(f"{mid}.{col}: {val} != CSV {csv_row[col]}")
            else:
                val = jm.get(col)
                if val != csv_row[col]:
                    errors.append(f"{mid}.{col}: {val!r} != CSV {csv_row[col]!r}")

    return errors


def _setup_temp_repo_116(tmp_dir: Path) -> Path:
    """Create an isolated temp repo with year 116 data, memos.csv, pdf_sources.csv, evidence."""
    (tmp_dir / "data").mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT_DIR / "data" / "116", tmp_dir / "data" / "116")
    shutil.copy2(ROOT_DIR / "data" / "pdf_sources.csv", tmp_dir / "data" / "pdf_sources.csv")
    shutil.copy2(ROOT_DIR / "data" / "corrections.csv", tmp_dir / "data" / "corrections.csv")
    if (ROOT_DIR / "docs" / "evidence" / "116").is_dir():
        shutil.copytree(ROOT_DIR / "docs" / "evidence" / "116", tmp_dir / "docs" / "evidence" / "116")

    # Keep only 116 memos in temp repo
    with (ROOT_DIR / "data" / "memos.csv").open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [r for r in reader if r["year"] == "116"]
    with (tmp_dir / "data" / "memos.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return tmp_dir


class TestMemosOutputVerification(unittest.TestCase):
    """A1: Independent target & verbatim field verification + mutation tests."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.memos_data = json.loads((ROOT_DIR / "site" / "data" / "memos.json").read_text(encoding="utf-8"))
        cls.search_docs = json.loads((ROOT_DIR / "site" / "data" / "search.json").read_text(encoding="utf-8"))
        cls.reference_by_year = {
            114: json.loads((ROOT_DIR / "site" / "data" / "reference_114.json").read_text(encoding="utf-8"))
        }
        cls.search_ids = {d["id"] for d in cls.search_docs}

    def _find_memo(self, data: dict[str, Any], memo_id: str) -> dict[str, Any]:
        for items in data["years"].values():
            for m in items:
                if m["memo_id"] == memo_id:
                    return m
        raise KeyError(memo_id)

    def test_real_memos_pass_independent_target_and_exact_field_checks(self) -> None:
        self.assertEqual(
            verify_memos_targets(
                self.memos_data, ROOT_DIR / "data", self.search_docs, self.reference_by_year
            ),
            [],
        )
        self.assertEqual(
            verify_memos_exact_fields(self.memos_data, ROOT_DIR / "data" / "memos.csv"),
            [],
        )

    def test_mutation_a_sibling_and_different_code_targets_caught(self) -> None:
        # (a1) Revenue sibling row: 114-revenue-12120010204-2
        rev_sibling = "114-revenue-12120010204-2"
        self.assertIn(rev_sibling, self.search_ids)
        mut1 = copy.deepcopy(self.memos_data)
        self._find_memo(mut1, "M114-0001")["target"]["search_id"] = rev_sibling
        errs1 = verify_memos_targets(mut1, ROOT_DIR / "data", self.search_docs, self.reference_by_year)
        self.assertTrue(errs1, "Revenue sibling search_id swap was not caught")

        # (a2) Expenditure sibling row: 114-expenditure-37120010201-2054-2
        exp_sibling = "114-expenditure-37120010201-2054-2"
        self.assertIn(exp_sibling, self.search_ids)
        mut2 = copy.deepcopy(self.memos_data)
        self._find_memo(mut2, "M114-0009")["target"]["search_id"] = exp_sibling
        errs2 = verify_memos_targets(mut2, ROOT_DIR / "data", self.search_docs, self.reference_by_year)
        self.assertTrue(errs2, "Expenditure sibling search_id swap was not caught")

        # (a3) Different revenue code existing id
        other_rev = next(
            d["id"]
            for d in self.search_docs
            if d["year"] == 114 and d["kind"] == "revenue" and d["code"] != "12120010204"
        )
        mut3 = copy.deepcopy(self.memos_data)
        self._find_memo(mut3, "M114-0001")["target"]["search_id"] = other_rev
        errs3 = verify_memos_targets(mut3, ROOT_DIR / "data", self.search_docs, self.reference_by_year)
        self.assertTrue(errs3, "Different-code revenue search_id swap was not caught")

    def test_mutation_b_truncated_printed_text_caught(self) -> None:
        mut = copy.deepcopy(self.memos_data)
        m = self._find_memo(mut, "M114-0001")
        m["printed_text"] = m["printed_text"][:-1]
        errs = verify_memos_exact_fields(mut, ROOT_DIR / "data" / "memos.csv")
        self.assertTrue(errs, "Truncated printed_text was not caught")

    def test_mutation_c_fullwidth_to_halfwidth_punctuation_caught(self) -> None:
        mut = copy.deepcopy(self.memos_data)
        m = self._find_memo(mut, "M114-0001")
        self.assertIn("，", m["printed_text"])
        m["printed_text"] = m["printed_text"].replace("，", ",", 1)
        errs = verify_memos_exact_fields(mut, ROOT_DIR / "data" / "memos.csv")
        self.assertTrue(errs, "Fullwidth-to-halfwidth punctuation change was not caught")

    def test_mutation_d_page_plus_one_caught(self) -> None:
        mut = copy.deepcopy(self.memos_data)
        m = self._find_memo(mut, "M114-0001")
        m["page"] = m["page"] + 1
        errs_target = verify_memos_targets(mut, ROOT_DIR / "data", self.search_docs, self.reference_by_year)
        errs_exact = verify_memos_exact_fields(mut, ROOT_DIR / "data" / "memos.csv")
        self.assertTrue(errs_target, "page+1 was not caught by target verification")
        self.assertTrue(errs_exact, "page+1 was not caught by exact field verification")


class TestBuildMemosValidationParity(unittest.TestCase):
    """A2: build() must enforce the same validation as validate.py and not write memos.json on failure."""

    def _mutate_116_memos(self, tmp_root: Path, mutator) -> None:
        memos_path = tmp_root / "data" / "memos.csv"
        with memos_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        mutator(rows)
        with memos_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_build_rejects_unknown_year_and_does_not_write_memos_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo_116(Path(td))

            def add_unknown_year(rows: list[dict[str, str]]) -> None:
                bad = dict(rows[0])
                bad["memo_id"] = "M199-0001"
                bad["year"] = "199"
                rows.append(bad)

            self._mutate_116_memos(tmp_root, add_unknown_year)
            site_dir = tmp_root / "site"
            with self.assertRaises(ValueError) as ctx:
                build(data_dir=tmp_root / "data", out_dir=tmp_root / "build", site_dir=site_dir)
            self.assertIn("M199-0001", str(ctx.exception))
            self.assertFalse((site_dir / "memos.json").exists())

    def test_build_rejects_mismatched_page_and_does_not_write_memos_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo_116(Path(td))

            def wrong_page(rows: list[dict[str, str]]) -> None:
                rows[0]["page"] = str(int(rows[0]["page"]) + 1)
                rows[0]["pdf_page"] = str(int(rows[0]["pdf_page"]) + 1)

            self._mutate_116_memos(tmp_root, wrong_page)
            site_dir = tmp_root / "site"
            with self.assertRaises(ValueError) as ctx:
                build(data_dir=tmp_root / "data", out_dir=tmp_root / "build", site_dir=site_dir)
            self.assertIn("M116-0001", str(ctx.exception))
            self.assertIn("V2", str(ctx.exception))
            self.assertFalse((site_dir / "memos.json").exists())

    def test_build_rejects_mismatched_data_text_and_does_not_write_memos_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo_116(Path(td))

            def wrong_data_text(rows: list[dict[str, str]]) -> None:
                rows[0]["data_text"] = rows[0]["data_text"] + "X"

            self._mutate_116_memos(tmp_root, wrong_data_text)
            site_dir = tmp_root / "site"
            with self.assertRaises(ValueError) as ctx:
                build(data_dir=tmp_root / "data", out_dir=tmp_root / "build", site_dir=site_dir)
            self.assertIn("M116-0001", str(ctx.exception))
            self.assertIn("V3", str(ctx.exception))
            self.assertFalse((site_dir / "memos.json").exists())

    def test_build_rejects_non_data_dir_with_memos_csv_unless_root_dir_given(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_root = _setup_temp_repo_116(Path(td))
            renamed = tmp_root / "custom_data"
            (tmp_root / "data").rename(renamed)
            site_dir = tmp_root / "site"
            with self.assertRaises(ValueError) as ctx:
                build(data_dir=renamed, out_dir=tmp_root / "build", site_dir=site_dir)
            self.assertIn("custom_data", str(ctx.exception))
            self.assertFalse((site_dir / "memos.json").exists())


if __name__ == "__main__":
    unittest.main()
