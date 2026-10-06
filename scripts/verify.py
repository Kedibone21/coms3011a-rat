#!/usr/bin/env python3
"""Verify engine metrics against the reference CSVs provided with the test.

For each reference repo: clone (once, cached under data/verify/), ingest at the
recorded ref_sha into data/verify/rat_verify.db, compute metrics for the 'all'
commit set, and diff against reference/<name>_<sha12>.csv:
  - integer columns (added, removed, growth, churn, modifications) must match exactly
  - float columns (modification_frequency, churn_rate, ownership) must match
    within 1e-6 relative tolerance
  - presence of every row must match (missing / extra rows are failures)

Usage:
    .venv/bin/python scripts/verify.py [--only cJSON,redis,git]

Exit code 0 iff every selected repo matches completely.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from rat import db, metrics, service  # noqa: E402

REPOS = {
    "cJSON": (
        "https://github.com/DaveGamble/cJSON.git",
        "6d9f2443ab071f86e5d9b43025a40929ec41c46c",
    ),
    "redis": (
        "https://github.com/redis/redis.git",
        "b540ca49cba815f3fbe634363c3df68d4f4f127a",
    ),
    "git": (
        "https://github.com/git/git.git",
        "5a7d1e8045ce66c908f62598e26cbb8df7b39a90",
    ),
}

VERIFY_DIR = ROOT / "data" / "verify"
DB_PATH = VERIFY_DIR / "rat_verify.db"
REF_DIR = ROOT / "reference"

INT_COLS = ("added", "removed", "growth", "churn", "modifications")
FLOAT_COLS = ("modification_frequency", "churn_rate", "ownership")
TOL = 1e-6

Key = tuple[str, str, str]


def ensure_clone(name: str, url: str) -> Path:
    dest = VERIFY_DIR / name
    if dest.exists():
        return dest
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  cloning {url} -> {dest} (first time only)")
    subprocess.run(["git", "clone", "--quiet", url, str(dest)], check=True)
    return dest


def load_reference(name: str, sha: str) -> dict[Key, dict]:
    path = REF_DIR / f"{name}_{sha[:12]}.csv"
    out: dict[Key, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["object_type"], row["path"], row["author"])] = row
    return out


def _float_cmp(eng_val, ref_val) -> bool:
    e_empty = eng_val is None or eng_val == ""
    r_empty = ref_val is None or ref_val == ""
    if e_empty and r_empty:
        return True
    if e_empty != r_empty:
        return False
    return abs(float(eng_val) - float(ref_val)) <= TOL * max(1.0, abs(float(ref_val)))


def compare(engine_rows: list[dict], ref_rows: dict[Key, dict]) -> dict:
    eng = {(r["object_type"], r["path"], r["author"]): r for r in engine_rows}
    report: dict = {
        "matched": 0,
        "mismatched": [],
        "missing": [],
        "extra": [],
        "commit_count_ref": None,
    }
    for key, ref in ref_rows.items():
        if report["commit_count_ref"] is None:
            report["commit_count_ref"] = int(ref["commit_count"])
        er = eng.pop(key, None)
        if er is None:
            report["missing"].append(key)
            continue
        bad = []
        for col in INT_COLS:
            if int(er[col]) != int(ref[col] or 0):
                bad.append(col)
        for col in FLOAT_COLS:
            if not _float_cmp(er[col], ref[col]):
                bad.append(col)
        if bad:
            report["mismatched"].append((key, bad, er, ref))
        else:
            report["matched"] += 1
    report["extra"] = list(eng.keys())
    return report


def run_repo(conn, name: str, url: str, ref: str, verbose: bool) -> bool:
    print(f"\n=== {name} @ {ref[:12]} ===", flush=True)
    repo_dir = ensure_clone(name, url)
    t0 = time.monotonic()
    repo_id, ref_sha, n = service.register_and_ingest(
        conn,
        name=name,
        repo_dir=repo_dir,
        ref=ref,
        source_type="url",
        source=url,
        progress=(lambda done: print(f"    ... {done} commits", flush=True)) if verbose else None,
        replace=True,
    )
    dt_ing = time.monotonic() - t0
    if ref_sha != ref:
        print(f"  note: {ref[:12]} resolved to {ref_sha[:12]}")

    t1 = time.monotonic()
    engine_rows = metrics.compute_rows(conn, repo_id, ("all",))
    dt_cmp = time.monotonic() - t1

    ref_rows = load_reference(name, ref)
    report = compare(engine_rows, ref_rows)
    ok = (
        not report["mismatched"]
        and not report["missing"]
        and not report["extra"]
        and report["commit_count_ref"] == n
    )
    print(
        f"  ingested {n} commits in {dt_ing:.1f}s; computed {len(engine_rows)} rows in {dt_cmp:.1f}s"
    )
    print(
        f"  reference: {len(ref_rows)} rows (commit_count {report['commit_count_ref']}); "
        f"engine: {len(engine_rows)} rows (commit_count {n})"
    )
    if ok:
        print("  OK — all rows match (ints exact, floats <= 1e-6)", flush=True)
        return True
    print(
        f"  matched {report['matched']}  mismatched {len(report['mismatched'])}  "
        f"missing {len(report['missing'])}  extra {len(report['extra'])}",
        flush=True,
    )
    for key, cols, er, ref in report["mismatched"][:10]:
        diffs = ", ".join(f"{c}: engine={er[c]!r} ref={ref[c]!r}" for c in cols)
        print(f"    MISMATCH {key}  [{diffs}]")
    for key in report["missing"][:10]:
        print(f"    MISSING {key}")
    for key in report["extra"][:10]:
        print(f"    EXTRA {key}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="comma list of repos (default: all)")
    ap.add_argument("--verbose", action="store_true", help="print commit-count progress")
    args = ap.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(REPOS)
    conn = db.connect(DB_PATH)
    db.init_db(conn)

    all_ok = True
    for name in names:
        url, ref = REPOS[name]
        ok = run_repo(conn, name, url, ref, args.verbose)
        all_ok = all_ok and ok

    print("\nRESULT:", "ALL MATCH" if all_ok else "MISMATCHES FOUND", flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
