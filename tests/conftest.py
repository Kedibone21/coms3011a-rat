"""Shared fixtures: a session-scoped tiny repo and a function-scoped ingested DB."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import tinyrepo
from rat import db, service


@pytest.fixture(scope="session")
def tiny_repo(tmp_path_factory):
    """Build the deterministic tiny repository once per test session."""
    info = tinyrepo.build(tmp_path_factory.mktemp("tinyrepo") / "repo")
    return info


@pytest.fixture()
def tiny(tiny_repo, tmp_path):
    """Fresh database with the tiny repo ingested; per test (author merges etc.)."""
    db_path = tmp_path / "tiny.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    repo_id, ref_sha, n = service.register_and_ingest(
        conn, name="tiny", repo_dir=tiny_repo["dir"]
    )
    yield SimpleNamespace(
        conn=conn,
        db_path=db_path,
        repo_id=repo_id,
        ref_sha=ref_sha,
        n=n,
        shas=tiny_repo["shas"],
    )
    conn.close()
