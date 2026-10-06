"""Service lifecycle tests: registration, status tracking, replace, error paths."""
from __future__ import annotations

import pytest

from rat import db, service
from rat.ingest import IngestError


def _conn(tmp_path):
    conn = db.connect(tmp_path / "svc.db")
    db.init_db(conn)
    return conn


def _count(conn, name=None):
    if name is None:
        return conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM repos WHERE name=?", (name,)).fetchone()[0]


def test_init_db_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    db.init_db(conn)  # second run must not fail
    conn.close()


def test_register_marks_repo_ready(tiny_repo, tmp_path):
    conn = _conn(tmp_path)
    repo_id, ref_sha, n = service.register_and_ingest(
        conn, name="tiny", repo_dir=tiny_repo["dir"]
    )
    row = conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone()
    assert row["status"] == "ready"
    assert row["commit_count"] == n == 5
    assert row["ref_sha"] == ref_sha == tiny_repo["shas"][4]
    assert len(ref_sha) == 40
    assert row["error"] is None
    conn.close()


def test_missing_repo_raises_and_creates_no_row(tmp_path):
    conn = _conn(tmp_path)
    empty = tmp_path / "notgit"
    empty.mkdir()
    with pytest.raises(IngestError):
        service.register_and_ingest(conn, name="x", repo_dir=empty)
    assert _count(conn) == 0  # ref resolution fails before the row is inserted
    conn.close()


def test_bad_ref_raises_and_creates_no_row(tiny_repo, tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(IngestError):
        service.register_and_ingest(
            conn, name="x", repo_dir=tiny_repo["dir"], ref="0000000000000000000000000000000000000000"
        )
    assert _count(conn) == 0
    conn.close()


def test_replace_removes_previous_rows(tiny_repo, tmp_path):
    conn = _conn(tmp_path)
    for _ in range(2):
        service.register_and_ingest(conn, name="dup", repo_dir=tiny_repo["dir"])
    assert _count(conn, "dup") == 2
    service.register_and_ingest(
        conn, name="dup", repo_dir=tiny_repo["dir"], replace=True
    )
    assert _count(conn, "dup") == 1
    row = conn.execute("SELECT status FROM repos WHERE name='dup'").fetchone()
    assert row["status"] == "ready"
    conn.close()


def test_ingest_error_marks_status_error(tiny_repo, tmp_path, monkeypatch):
    """Any failure after the row exists leaves status='error' plus the message."""
    conn = _conn(tmp_path)

    def boom(*args, **kwargs):
        raise IngestError("synthetic failure")

    monkeypatch.setattr(service.ingest_mod, "ingest_repo", boom)
    with pytest.raises(IngestError):
        service.register_and_ingest(conn, name="bad", repo_dir=tiny_repo["dir"])
    row = conn.execute("SELECT status, error FROM repos WHERE name='bad'").fetchone()
    assert row["status"] == "error"
    assert "synthetic failure" in row["error"]
    conn.close()
