"""Command-line entry points: `python -m rat.cli <command> ...`."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import db, metrics, service


def _progress(done: int) -> None:
    print(f"  ... {done} commits", file=sys.stderr)


def cmd_ingest(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo).resolve()
    if not (repo_dir / ".git").exists():
        print(f"error: {repo_dir} is not a git repository", file=sys.stderr)
        return 2
    conn = db.connect(args.db)
    db.init_db(conn)
    name = args.name or repo_dir.name
    t0 = time.monotonic()
    repo_id, ref_sha, n = service.register_and_ingest(
        conn,
        name=name,
        repo_dir=repo_dir,
        ref=args.ref,
        source_type=args.source_type,
        source=args.source or str(repo_dir),
        progress=_progress,
        replace=args.replace,
    )
    dt = time.monotonic() - t0
    print(
        f"ingested {n} commits from {name} @ {ref_sha[:12]} in {dt:.1f}s (repo id {repo_id})"
    )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    db.init_db(conn)
    if args.repo_id is not None:
        repo_id = args.repo_id
        row = conn.execute("SELECT name FROM repos WHERE id = ?", (repo_id,)).fetchone()
        if row is None:
            print(f"error: no repo with id {repo_id}", file=sys.stderr)
            return 2
    else:
        row = conn.execute(
            "SELECT id FROM repos WHERE name = ? ORDER BY id DESC", (args.name,)
        ).fetchone()
        if row is None:
            print(f"error: no repo named {args.name!r}", file=sys.stderr)
            return 2
        repo_id = row[0]
    cs = metrics.parse_commit_set(args.set)
    rows = metrics.compute_rows(conn, repo_id, cs)
    text = metrics.rows_to_csv(rows)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {len(rows)} rows to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rat")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="ingest a local git repository into the database")
    p.add_argument("--repo", required=True, help="path to the git repository working tree")
    p.add_argument("--ref", default="HEAD", help="reference commit (default HEAD)")
    p.add_argument("--name", default=None, help="display name (default: directory name)")
    p.add_argument("--source-type", default="local")
    p.add_argument("--source", default=None)
    p.add_argument("--db", default=None, help="override the database path")
    p.add_argument(
        "--replace", action="store_true", help="replace an existing repo with the same name"
    )
    p.set_defaults(func=cmd_ingest)

    p2 = sub.add_parser("export", help="export metrics as a reference-format CSV")
    group = p2.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="repository name")
    group.add_argument("--repo-id", type=int, help="repository id")
    p2.add_argument(
        "--set", default="all", help="all | since:TS | range:A-B | list:SHA,..."
    )
    p2.add_argument("--out", default=None, help="output path (default: stdout)")
    p2.add_argument("--db", default=None, help="override the database path")
    p2.set_defaults(func=cmd_export)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
