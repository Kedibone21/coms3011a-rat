"""Deterministic tiny git repository used by the engine tests.

History (all timestamps are fixed so commit SHAs are reproducible):

    c1 (ts=100, Alice): add a.txt (3 lines), add dir/b.txt (1 line)
    c2 (ts=200, Alice): grow a.txt to 4 lines, add dir/c.txt (1 line)
    c3 (ts=300, Bob):   grow dir/b.txt to 2 lines
    c4 (ts=400, Bob):   pure rename dir/c.txt -> dir/c2.txt
    c5 (ts=500, Alice): empty commit

Hand-computed expectations for the full set (|H| = 5):
    repository: added 7, churn 7, modifications 3
    dir:        added 3, churn 3, modifications 3
    a.txt:      added 4, churn 4, modifications 2
    dir/b.txt:  added 2, churn 2, modifications 2
    dir/c.txt:  added 1, churn 1, modifications 1  (old path of the rename)
    dir/c2.txt: all zero                           (new path of the rename)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ALICE = ("Alice", "alice@example.com")
BOB = ("Bob", "bob@example.com")


def _run(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout.strip()


def _commit(repo: Path, ts: int, author: tuple[str, str], message: str) -> str:
    name, email = author
    date = f"@{ts} +0000"
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    }
    proc = subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", f"user.name={name}",
            "-c", f"user.email={email}",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "--allow-empty", "-m", message,
        ],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, f"commit failed: {proc.stderr}"
    return _run(repo, "rev-parse", "HEAD")


def build(repo_dir: Path) -> dict:
    """Create the repository; returns {'dir', 'shas', 'alice', 'bob'}."""
    repo_dir = Path(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    _run(repo_dir, "init", "-q", "-b", "main")

    (repo_dir / "a.txt").write_text("1\n2\n3\n")
    (repo_dir / "dir").mkdir()
    (repo_dir / "dir" / "b.txt").write_text("1\n")
    _run(repo_dir, "add", "-A")
    sha1 = _commit(repo_dir, 100, ALICE, "c1")

    (repo_dir / "a.txt").write_text("1\n2\n3\n4\n")
    (repo_dir / "dir" / "c.txt").write_text("x\n")
    _run(repo_dir, "add", "-A")
    sha2 = _commit(repo_dir, 200, ALICE, "c2")

    (repo_dir / "dir" / "b.txt").write_text("1\n2\n")
    _run(repo_dir, "add", "-A")
    sha3 = _commit(repo_dir, 300, BOB, "c3")

    _run(repo_dir, "mv", "dir/c.txt", "dir/c2.txt")
    sha4 = _commit(repo_dir, 400, BOB, "c4")

    sha5 = _commit(repo_dir, 500, ALICE, "c5")

    return {
        "dir": repo_dir,
        "shas": [sha1, sha2, sha3, sha4, sha5],
        "alice": ALICE,
        "bob": BOB,
    }
