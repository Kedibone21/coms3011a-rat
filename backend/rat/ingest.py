"""Single-pass ingestion of a git repository's history into SQLite."""
from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .gitparse import CommitRecord, LogParser

LOG_FORMAT = "%x1e%H%x1f%ct%x1f%aN%x1f%aE%x1f%P"
READ_CHUNK = 1 << 20
STATS_BATCH = 5000


class IngestError(RuntimeError):
    pass


def _git(repo_dir: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise IngestError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def rev_parse(repo_dir: Path, ref: str) -> str:
    return _git(repo_dir, "rev-parse", "--verify", f"{ref}^{{commit}}")


def count_commits(repo_dir: Path, ref: str) -> int:
    return int(_git(repo_dir, "rev-list", "--no-merges", "--count", ref))


def log_command(repo_dir: Path, ref: str) -> list[str]:
    """The single command that drives the whole ingest."""
    return [
        "git", "-C", str(repo_dir),
        "-c", "core.quotepath=false",
        "-c", "diff.renameLimit=10000",
        "log", "--no-merges", "--root", "--numstat", "-z",
        "-M50%", "--use-mailmap",
        f"--pretty=format:{LOG_FORMAT}",
        ref, "--",
    ]


def ingest_repo(
    conn,
    repo_id: int,
    repo_dir: Path,
    ref: str,
    progress: Callable[[int], None] | None = None,
) -> int:
    """Parse history reachable from `ref` and store it; returns the commit count.

    Must be called inside a transaction owned by the caller.
    """
    parser = LogParser()
    author_ids: dict[tuple[str, str], int] = {}
    n_commits = 0
    pending_stats: list[tuple] = []

    def flush_stats() -> None:
        if pending_stats:
            conn.executemany(
                "INSERT INTO file_stats(repo_id, commit_id, path, added, removed)"
                " VALUES(?,?,?,?,?)",
                pending_stats,
            )
            pending_stats.clear()

    def store(rec: CommitRecord) -> None:
        nonlocal n_commits
        key = (rec.name, rec.email)
        author_id = author_ids.get(key)
        if author_id is None:
            cur = conn.execute(
                "INSERT OR IGNORE INTO authors(repo_id, name, email) VALUES(?,?,?)",
                (repo_id, rec.name, rec.email),
            )
            if cur.rowcount == 1:
                author_id = cur.lastrowid
            else:
                author_id = conn.execute(
                    "SELECT id FROM authors WHERE repo_id=? AND name=? AND email=?",
                    (repo_id, rec.name, rec.email),
                ).fetchone()[0]
            author_ids[key] = author_id
        cur = conn.execute(
            "INSERT INTO commits(repo_id, sha, ts, author_id, parent_sha) VALUES(?,?,?,?,?)",
            (repo_id, rec.sha, rec.ts, author_id, rec.parent_sha),
        )
        commit_id = cur.lastrowid
        for e in rec.entries:
            if e.is_binary:
                continue  # binary files are not measured
            pending_stats.append((repo_id, commit_id, e.path, e.added, e.removed))
            if e.old_path and e.old_path != e.path:
                # A rename's old path stays a member of the commit set (all-zero row);
                # deltas themselves land only on the new path.
                pending_stats.append((repo_id, commit_id, e.old_path, 0, 0))
        n_commits += 1
        if len(pending_stats) >= STATS_BATCH:
            flush_stats()
        if progress is not None and n_commits % 2000 == 0:
            progress(n_commits)

    err_file = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        log_command(repo_dir, ref), stdout=subprocess.PIPE, stderr=err_file
    )
    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read(READ_CHUNK)
            if not chunk:
                break
            for rec in parser.feed(chunk):
                store(rec)
        for rec in parser.finish():
            store(rec)
    finally:
        err_file.seek(0)
        stderr = err_file.read()
        err_file.close()
        code = proc.wait()
    if code != 0:
        raise IngestError(stderr.decode(errors="replace").strip() or "git log failed")

    flush_stats()
    # Resolve parent ids (parents may appear later in the log than their children).
    conn.execute(
        """
        UPDATE commits SET parent_id = (
            SELECT p.id FROM commits p
            WHERE p.repo_id = commits.repo_id AND p.sha = commits.parent_sha
        )
        WHERE repo_id = ? AND parent_sha IS NOT NULL
        """,
        (repo_id,),
    )
    return n_commits
