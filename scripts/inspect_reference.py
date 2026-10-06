#!/usr/bin/env python3
"""Inspect the provided reference metric CSVs to pin down exact output semantics.

Answers, for each reference file:
  - row structure per object_type (ALL rows vs per-author rows)
  - whether zero-metric rows exist (i.e. snapshot semantics vs touched-only)
  - exact path formats for files/directories/root
  - which columns are filled on which row kind
  - additive consistency between ALL rows and per-author rows

Run:  python3 scripts/inspect_reference.py
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

REF_DIR = Path(__file__).resolve().parent.parent / "reference"

VALUE_COLS = (
    "added",
    "removed",
    "growth",
    "churn",
    "modifications",
    "modification_frequency",
    "churn_rate",
    "ownership",
)


def inspect(path: Path) -> None:
    print("=" * 100)
    print("FILE:", path.name)
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    print("total rows:", len(rows))
    print("commit_set:", dict(Counter(r["commit_set"] for r in rows)))
    print("commit_count:", dict(Counter(r["commit_count"] for r in rows)))

    for ot in ("repository", "directory", "file"):
        sub = [r for r in rows if r["object_type"] == ot]
        if not sub:
            continue
        paths = sorted({r["path"] for r in sub})
        all_rows = [r for r in sub if r["author"] == "ALL"]
        auth_rows = [r for r in sub if r["author"] != "ALL"]
        zeros = [r for r in sub if r["added"] == "0" and r["removed"] == "0"]
        zero_all = [r for r in zeros if r["author"] == "ALL"]
        print(
            f"\n--- object_type={ot}: rows={len(sub)} distinct_paths={len(paths)} "
            f"ALL_rows={len(all_rows)} author_rows={len(auth_rows)}"
        )
        print(f"    zero rows (added==removed==0): {len(zeros)} (ALL: {len(zero_all)})")
        print(f"    sample paths: {paths[:12]}")
        dup = len(sub) - len({(r["path"], r["author"]) for r in sub})
        print(f"    duplicate (path,author) pairs: {dup}")
        if zero_all:
            print(f"    zero-path sample: {[r['path'] for r in zero_all[:10]]}")

        by_path: dict[str, list] = defaultdict(list)
        for r in sub:
            by_path[r["path"]].append(r)
        for p in paths[:2]:
            print(f"    rows for path {p!r}:")
            for r in by_path[p][:10]:
                filled = {k: r[k] for k in VALUE_COLS if r[k] != ""}
                print(f"        author={r['author']!r} {filled}")

        if auth_rows:
            empty_own = sum(1 for r in auth_rows if r["ownership"] == "")
            print(f"    author rows with empty ownership: {empty_own}")
            print(
                "    author rows with non-empty modifications: "
                f"{sum(1 for r in auth_rows if r['modifications'] != '')}"
            )
        print(
            "    ALL rows with non-empty ownership: "
            f"{sum(1 for r in all_rows if r['ownership'] != '')}"
        )

        checked = mism = 0
        for _p, rs in by_path.items():
            ar = [r for r in rs if r["author"] == "ALL"]
            au = [r for r in rs if r["author"] != "ALL"]
            if len(ar) == 1 and au:
                checked += 1
                if sum(int(r["added"]) for r in au) != int(ar[0]["added"]):
                    mism += 1
        print(f"    paths checked for sum(author added)==ALL added: {checked}, mismatches: {mism}")

    freqs = [r["modification_frequency"] for r in rows if r["modification_frequency"]][:4]
    owns = [r["ownership"] for r in rows if r["ownership"]][:4]
    print("\nsample float strings: modification_frequency=", freqs, "ownership=", owns)


def main() -> None:
    files = sorted(REF_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(f"no CSVs found in {REF_DIR}")
    for f in files:
        inspect(f)


if __name__ == "__main__":
    main()
