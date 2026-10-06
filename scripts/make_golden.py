"""Regenerate tests/golden/tiny_all.csv from the deterministic tiny repository.

Only run this after re-verifying semantics via scripts/verify.py (the three
reference repos) — the golden file is the regression lock for the small fixture.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "backend"))

import tinyrepo  # noqa: E402
from rat import db, metrics, service  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        info = tinyrepo.build(Path(td) / "repo")
        conn = db.connect(Path(td) / "golden.db")
        db.init_db(conn)
        repo_id, ref_sha, n = service.register_and_ingest(
            conn, name="tiny", repo_dir=info["dir"]
        )
        rows = metrics.compute_rows(conn, repo_id, ("all",))
        out = ROOT / "tests" / "golden" / "tiny_all.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(metrics.rows_to_csv(rows).encode())
        print(f"wrote {len(rows)} rows (|H|={n}, sha={ref_sha[:12]}) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
