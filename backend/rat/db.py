"""SQLite connection management and schema definition."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- 'zip' | 'url' | 'local'
    source TEXT,                        -- url / original filename / local path
    ref_sha TEXT NOT NULL,              -- resolved reference commit (h_r)
    commit_count INTEGER NOT NULL DEFAULT 0,  -- |H|: non-merge commits reachable from h_r
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ingesting',  -- ingesting | ready | error
    error TEXT,
    repo_dir TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    UNIQUE(repo_id, name, email)
);

CREATE TABLE IF NOT EXISTS author_merges (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    source_author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    target_author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    PRIMARY KEY (repo_id, source_author_id)
);

CREATE TABLE IF NOT EXISTS commits (
    id INTEGER PRIMARY KEY,
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    ts INTEGER NOT NULL,                -- committer timestamp (unix seconds)
    author_id INTEGER NOT NULL REFERENCES authors(id),
    parent_sha TEXT,                    -- first parent (merge commits are not ingested)
    parent_id INTEGER REFERENCES commits(id),
    UNIQUE(repo_id, sha)
);

CREATE TABLE IF NOT EXISTS file_stats (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    commit_id INTEGER NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
    path TEXT NOT NULL,                 -- attributed path (new path for renames)
    added INTEGER NOT NULL,
    removed INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commits_repo_ts ON commits(repo_id, ts);
CREATE INDEX IF NOT EXISTS idx_commits_repo_id ON commits(repo_id, id);
CREATE INDEX IF NOT EXISTS idx_fs_commit ON file_stats(commit_id);
CREATE INDEX IF NOT EXISTS idx_fs_repo_path ON file_stats(repo_id, path);
"""


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas used everywhere."""
    config.ensure_dirs()
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")  # wait out background ingests
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-65536")  # 64 MiB
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
