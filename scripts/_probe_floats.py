#!/usr/bin/env python3
"""Compare engine export vs reference numerically (value-level, ignoring formatting)."""
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOATS = ("modification_frequency", "churn_rate", "ownership")
INTS = ("added", "removed", "growth", "churn", "modifications")


def load(p):
    rows = {}
    with open(p, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows[(r["object_type"], r["path"], r["author"])] = r
    return rows


eng = load("/tmp/git_engine.csv")
ref = load(ROOT / "reference" / "git_5a7d1e8045ce.csv")

bad = Counter()
examples = {}
for k, rr in ref.items():
    er = eng.get(k)
    if er is None:
        bad["MISSING"] += 1
        continue
    for c in INTS:
        if int(er[c]) != int(rr[c]):
            bad[c] += 1
            examples.setdefault(c, (k, er[c], rr[c]))
    for c in FLOATS:
        e, r = er[c], rr[c]
        ee, ren = e == "", r == ""
        if ee != ren:
            bad[c + "(empty)"] += 1
            examples.setdefault(c + "(empty)", (k, e, r))
            continue
        if ee:
            continue
        if float(e) != float(r):
            bad[c] += 1
            examples.setdefault(c, (k, e, r))

print("value-level differences (exact float equality):")
for c, n in bad.most_common():
    print(f"  {c}: {n}   e.g. {examples.get(c, '')}")
if not bad:
    print("  none - all values identical")

print()
print("formula probe (bin-wrappers ALL churn_rate, ref=0.0008837825894829871):")
refv = 0.0008837825894829871
print("  54/61101           ==", repr(54 / 61101), 54 / 61101 == refv)
print("  46/61101 + 8/61101 ==", repr(46 / 61101 + 8 / 61101), 46 / 61101 + 8 / 61101 == refv)
print("  (46+8)/61101       ==", repr((46 + 8) / 61101), (46 + 8) / 61101 == refv)
