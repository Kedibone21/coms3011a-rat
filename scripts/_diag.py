#!/usr/bin/env python3
"""Diagnose reference paths that have no file_stats rows in the ingested DB."""
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
conn = sqlite3.connect(ROOT / "data" / "verify" / "rat_verify.db")
(rid,) = conn.execute("SELECT id FROM repos WHERE name = 'git'").fetchone()

ref = {}
with open(ROOT / "reference" / "git_5a7d1e8045ce.csv", newline="", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        ref[(r["object_type"], r["path"], r["author"])] = r

missing = []
for (ot, path, author) in ref:
    if ot != "file" or author != "ALL":
        continue
    n = conn.execute(
        "SELECT COUNT(*) FROM file_stats WHERE repo_id=? AND path=?", (rid, path)
    ).fetchone()[0]
    if n == 0:
        missing.append(path)

print(f"reference file paths with ZERO rows in my DB: {len(missing)}")
for p in missing[:50]:
    print("  MISS", p)

print("\nsample counterpart checks:")
for p in (
    "Documentation/RelNotes-1.5.5.6.txt",
    "Documentation/RelNotes/1.5.5.6.txt",
    "Documentation/RelNotes-1.5.0.1.txt",
    "Documentation/RelNotes/1.5.0.1.txt",
):
    n = conn.execute(
        "SELECT COUNT(*) FROM file_stats WHERE repo_id=? AND path=?", (rid, p)
    ).fetchone()[0]
    print(f"  rows={n:5d}  {p}")
sys.exit(0)
