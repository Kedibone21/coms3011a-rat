"""Repository lifecycle: registration, ingestion, status tracking.

Used by the CLI and (later) the web API — one code path for both.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from . import ingest as ingest_mod


def register_and_ingest(
    conn,
    *,
    name: str,
    repo_dir: Path | str,
    ref: str = "HEAD",
    source_type: str = "local",
    source: str | None = None,
    progress: Callable[[int], None] | None = None,
    replace: bool = False,
) -> tuple[int, str, int]:
    """Insert the repo row, ingest history, mark ready.

    Returns (repo_id, resolved ref_sha, commit count). On failure the repo row
    is kept with status='error' and the error message, then the error re-raised.
    """
    repo_dir = Path(repo_dir).resolve()
    ref_sha = ingest_mod.rev_parse(repo_dir, ref)
    if replace:
        with conn:
            conn.execute("DELETE FROM repos WHERE name = ?", (name,))
    with conn:
        cur = conn.execute(
            "INSERT INTO repos(name, source_type, source, ref_sha, created_at, status, repo_dir)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                name,
                source_type,
                source or str(repo_dir),
                ref_sha,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ingesting",
                str(repo_dir),
            ),
        )
        repo_id = cur.lastrowid
    try:
        with conn:
            n = ingest_mod.ingest_repo(conn, repo_id, repo_dir, ref_sha, progress=progress)
            conn.execute(
                "UPDATE repos SET status = 'ready', commit_count = ? WHERE id = ?",
                (n, repo_id),
            )
    except Exception as exc:  # keep the failure visible to the UI
        with conn:
            conn.execute(
                "UPDATE repos SET status = 'error', error = ? WHERE id = ?",
                (str(exc)[:2000], repo_id),
            )
        raise
    return repo_id, ref_sha, n


def create_repo(
    conn,
    *,
    name: str,
    source_type: str,
    source: str,
    repo_dir: Path | str,
) -> int:
    """Insert a repo row in 'ingesting' status and return its id (API flow).

    Unlike register_and_ingest, the repository is acquired *after* the row
    exists (background clone/extract), so ref_sha starts empty.
    """
    with conn:
        cur = conn.execute(
            "INSERT INTO repos(name, source_type, source, ref_sha, created_at, status, repo_dir)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                name,
                source_type,
                source,
                "",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ingesting",
                str(repo_dir),
            ),
        )
        return cur.lastrowid


def complete_ingest(
    conn,
    repo_id: int,
    repo_dir: Path | str,
    ref: str = "HEAD",
    progress: Callable[[int], None] | None = None,
) -> tuple[str, int]:
    """Resolve the ref, ingest history, mark ready; failures mark 'error'.

    Returns (resolved ref sha, commit count)."""
    repo_dir = Path(repo_dir).resolve()
    try:
        ref_sha = ingest_mod.rev_parse(repo_dir, ref)
        with conn:
            n = ingest_mod.ingest_repo(conn, repo_id, repo_dir, ref_sha, progress=progress)
            conn.execute(
                "UPDATE repos SET ref_sha = ?, status = 'ready', commit_count = ?,"
                " repo_dir = ?, error = NULL WHERE id = ?",
                (ref_sha, n, str(repo_dir), repo_id),
            )
    except Exception as exc:  # keep the failure visible to the UI
        mark_error(conn, repo_id, exc)
        raise
    return ref_sha, n


def mark_error(conn, repo_id: int, exc: BaseException) -> None:
    """Record a failure on the repo row (idempotent, safe to call twice)."""
    with conn:
        conn.execute(
            "UPDATE repos SET status = 'error', error = ? WHERE id = ?",
            (str(exc)[:2000], repo_id),
        )
