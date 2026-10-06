"""Repository acquisition: public HTTPS clones and zip-with-.git uploads."""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from .ingest import IngestError

CLONE_TIMEOUT = 3600           # seconds; large repos on slow links
MAX_EXTRACT_BYTES = 4 * 1024**3  # guard against zip bombs


def clone_repo(url: str, dest: Path, *, timeout: int = CLONE_TIMEOUT) -> Path:
    """Clone a public repository over http(s) into `dest` (fresh, full clone)."""
    if not url.startswith(("https://", "http://")):
        raise IngestError(
            "only public http(s) clone URLs are supported (no ssh, no tokens)"
        )
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["git", "clone", "--quiet", url, str(dest)],
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise IngestError(f"git clone timed out after {timeout}s") from None
    if proc.returncode != 0:
        raise IngestError(f"git clone failed: {proc.stderr.strip()[:500]}")
    return dest


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """Extract an uploaded archive into `dest`.

    Returns the directory that actually contains `.git` — zips commonly wrap
    everything in one top-level folder. Rejects entries that would escape
    `dest` (zip-slip) and archives without any `.git` directory.
    """
    zip_path, dest = Path(zip_path), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as zf:
        total = sum(info.file_size for info in zf.infolist())
        if total > MAX_EXTRACT_BYTES:
            raise IngestError(
                f"archive too large: {total} bytes extracted (limit {MAX_EXTRACT_BYTES})"
            )
        root = dest.resolve()
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if target != root and root not in target.parents:
                raise IngestError(f"archive entry escapes extraction dir: {info.filename!r}")
        zf.extractall(dest)

    if (dest / ".git").exists():
        return dest
    for child in sorted(dest.iterdir()):
        if child.is_dir() and (child / ".git").exists():
            return child
    raise IngestError(
        "archive contains no .git directory — upload a zip of the repository "
        "including its .git folder"
    )
