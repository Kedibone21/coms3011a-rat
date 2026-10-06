"""End-to-end check of the running RAT server (default http://127.0.0.1:8000).

Verifies, over HTTP against a live uvicorn instance:
  1. zip-with-.git ingestion completes (status -> ready)
  2. its CSV export is byte-identical to tests/golden/tiny_all.csv (the repo is uploaded
     under the name "tiny", matching how the golden was generated)
  3. a manual author merge changes the export, and unmerging restores it byte-exactly
  4. (optional, --clone URL) clone ingestion completes and reports the expected commits

Note: each run leaves its repositories in the database (a ready-made multi-repo demo);
delete them from the UI if you want a clean slate.

Usage:
    .venv/bin/python scripts/e2e_check.py [--base http://127.0.0.1:8000]
                                         [--clone https://github.com/owner/repo.git]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import tinyrepo  # noqa: E402

GOLDEN = ROOT / "tests" / "golden" / "tiny_all.csv"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def wait_ready(client: httpx.Client, repo_id: int, timeout: float = 300.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        repo = client.get(f"/api/repos/{repo_id}").json()
        if repo["status"] == "ready":
            return repo
        if repo["status"] == "error":
            fail(f"repo {repo_id} ingest error: {repo['error']}")
        time.sleep(0.4)
    fail(f"repo {repo_id} did not become ready within {timeout:.0f}s")


def make_tiny_zip(dest: Path) -> Path:
    src = Path(tempfile.mkdtemp(prefix="rat_e2e_")) / "tinyrepo"
    tinyrepo.build(src)
    zip_path = dest / "tiny_e2e.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--clone", default=None, help="public clone URL for step 4")
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base, timeout=60.0)
    golden = GOLDEN.read_bytes()
    print(f"[e2e] server: {args.base}")

    # 1. zip ingestion -----------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        zip_path = make_tiny_zip(Path(td))
        with open(zip_path, "rb") as fh:
            resp = client.post(
                "/api/repos/zip", files={"file": ("tiny_e2e.zip", fh, "application/zip")},
                data={"name": "tiny", "ref": "HEAD"},
            )
    if resp.status_code != 202:
        fail(f"zip upload -> {resp.status_code}: {resp.text}")
    zip_id = resp.json()["id"]
    repo = wait_ready(client, zip_id)
    print(f"[e2e] 1. zip ingest ready: id={zip_id} commits={repo['commit_count']}")

    # 2. byte-exact export -------------------------------------------------------
    export = client.get(f"/api/repos/{zip_id}/export.csv").content
    if export != golden:
        fail(f"zip export differs from golden ({len(export)} vs {len(golden)} bytes)")
    print(f"[e2e] 2. zip export byte-identical to golden ({len(golden)} bytes)")

    # 3. merge -> export changes; unmerge -> restored ----------------------------
    authors = client.get(f"/api/repos/{zip_id}/authors").json()
    by_name = {a["name"]: a for a in authors}
    alice, bob = by_name.get("Alice"), by_name.get("Bob")
    if not alice or not bob:
        fail(f"expected Alice and Bob, got {[a['name'] for a in authors]}")
    r = client.post(
        f"/api/repos/{zip_id}/merges",
        json={"source_author_id": bob["id"], "target_author_id": alice["id"]},
    )
    if r.status_code not in (200, 201):
        fail(f"merge -> {r.status_code}: {r.text}")
    merged = client.get(f"/api/repos/{zip_id}/export.csv").content
    if merged == golden:
        fail("merge did not change the export")
    if b",Bob," in merged:
        fail("merged export still contains Bob rows")
    r = client.delete(f"/api/repos/{zip_id}/merges/{bob['id']}")
    if r.status_code not in (200, 204):
        fail(f"unmerge -> {r.status_code}: {r.text}")
    restored = client.get(f"/api/repos/{zip_id}/export.csv").content
    if restored != golden:
        fail("unmerge did not restore the byte-exact export")
    print("[e2e] 3. merge relabels authors, unmerge restores golden bytes")

    # 4. optional clone ingestion ------------------------------------------------
    if args.clone:
        resp = client.post(
            "/api/repos/url", json={"url": args.clone, "name": "e2e-clone", "ref": "HEAD"}
        )
        if resp.status_code != 202:
            fail(f"clone upload -> {resp.status_code}: {resp.text}")
        clone_id = resp.json()["id"]
        repo = wait_ready(client, clone_id)
        metrics = client.get(
            f"/api/repos/{clone_id}/metrics", params={"set": "all"}
        ).json()
        if metrics["commit_count"] != repo["commit_count"]:
            fail(
                f"metrics commit_count {metrics['commit_count']} != repo "
                f"{repo['commit_count']}"
            )
        if not metrics["rows"]:
            fail("clone metrics returned no rows")
        print(
            f"[e2e] 4. clone ingest ready: id={clone_id} "
            f"commits={repo['commit_count']} rows={len(metrics['rows'])}"
        )

    repos = client.get("/api/repos").json()
    print(f"[e2e] repositories now: {', '.join(r['name'] for r in repos)}")
    print("[e2e] ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
