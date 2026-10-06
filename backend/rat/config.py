"""Runtime configuration: data directory, database path, repository storage."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(
    os.environ.get("RAT_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))
)
DB_PATH = BASE_DIR / "rat.db"
REPOS_DIR = BASE_DIR / "repos"


def ensure_dirs() -> None:
    """Create the data directories if they do not exist yet."""
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
