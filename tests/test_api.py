"""API tests: zip ingestion end-to-end, metrics/export, authors, merges, commits."""
from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import rat.api as api
from rat import config

GOLDEN = Path(__file__).parent / "golden" / "tiny_all.csv"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(config, "REPOS_DIR", tmp_path / "repos")
    (tmp_path / "repos").mkdir()
    return TestClient(api.app)


def _zip_repo(repo_dir: Path, out: Path) -> Path:
    """Zip the whole repository including its .git directory."""
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(repo_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(repo_dir))
    return out


def _upload_and_wait(client, tiny_repo, tmp_path, name="tiny"):
    zpath = _zip_repo(tiny_repo["dir"], tmp_path / f"{name}.zip")
    with zpath.open("rb") as fh:
        r = client.post(
            "/api/repos/zip",
            files={"file": (f"{name}.zip", fh, "application/zip")},
            data={"name": name},
        )
    assert r.status_code == 202, r.text
    repo_id = r.json()["id"]
    deadline = time.time() + 90
    while time.time() < deadline:
        detail = client.get(f"/api/repos/{repo_id}").json()
        if detail["status"] in ("ready", "error"):
            return repo_id, detail
        time.sleep(0.05)
    raise AssertionError("ingest did not finish in time")


# ---- basics ---------------------------------------------------------------------

def test_health_and_empty_list(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/repos").json() == []
    # "/" serves the built SPA when frontend/dist exists, else a JSON hint.
    root = client.get("/")
    assert root.status_code == 200
    ctype = root.headers["content-type"]
    if ctype.startswith("application/json"):
        assert root.json()["name"] == "Repo Analysis Tool API"
    else:
        assert ctype.startswith("text/html")


def test_unknown_repo_returns_404(client):
    assert client.get("/api/repos/999").status_code == 404
    assert client.get("/api/repos/999/metrics").status_code == 404
    assert client.get("/api/repos/999/export.csv").status_code == 404
    assert client.delete("/api/repos/999").status_code == 404


def test_url_validation_rejects_ssh(client):
    r = client.post("/api/repos/url", json={"url": "git@github.com:a/b.git"})
    assert r.status_code == 400


# ---- zip ingestion end to end ------------------------------------------------------

def test_zip_ingest_ready_and_matches_golden(client, tiny_repo, tmp_path):
    repo_id, detail = _upload_and_wait(client, tiny_repo, tmp_path)
    assert detail["status"] == "ready", detail
    assert detail["commit_count"] == 5
    assert detail["ref_sha"] == tiny_repo["shas"][4]

    r = client.get(f"/api/repos/{repo_id}/export.csv", params={"set": "all"})
    assert r.status_code == 200
    assert r.content == GOLDEN.read_bytes()
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('tiny_all.csv"')


def test_zip_without_git_marks_error(client, tmp_path):
    zpath = tmp_path / "plain.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("hello.txt", "no git here\n")
    with zpath.open("rb") as fh:
        r = client.post(
            "/api/repos/zip", files={"file": ("plain.zip", fh, "application/zip")}
        )
    repo_id = r.json()["id"]
    deadline = time.time() + 30
    detail = None
    while time.time() < deadline:
        detail = client.get(f"/api/repos/{repo_id}").json()
        if detail["status"] == "error":
            break
        time.sleep(0.05)
    assert detail is not None and detail["status"] == "error"
    assert ".git" in detail["error"]


def test_metrics_requires_ready_repo(client):
    import rat.api as api_module

    conn = api_module.get_conn()
    repo_id = api_module.service.create_repo(
        conn, name="pending", source_type="url", source="https://x/y.git", repo_dir="/tmp/x"
    )
    conn.close()
    r = client.get(f"/api/repos/{repo_id}/metrics")
    assert r.status_code == 409
    assert "ingesting" in r.json()["detail"]


# ---- metrics, filters, export -------------------------------------------------------

def test_metrics_rows_and_filters(client, tiny_repo, tmp_path):
    repo_id, _ = _upload_and_wait(client, tiny_repo, tmp_path)

    all_rows = client.get(f"/api/repos/{repo_id}/metrics").json()
    assert all_rows["commit_set"] == "all"
    assert all_rows["commit_count"] == 5
    root = next(r for r in all_rows["rows"] if r["object_type"] == "repository")
    assert root["added"] == 7 and root["modifications"] == 3

    ranged = client.get(
        f"/api/repos/{repo_id}/metrics", params={"set": "range:200-400"}
    ).json()
    assert ranged["commit_count"] == 2

    scoped = client.get(
        f"/api/repos/{repo_id}/metrics", params={"path": "dir"}
    ).json()
    assert ("file", "a.txt") not in {
        (r["object_type"], r["path"]) for r in scoped["rows"]
    }

    files_only = client.get(
        f"/api/repos/{repo_id}/metrics", params={"object_type": "file"}
    ).json()
    assert {r["object_type"] for r in files_only["rows"]} == {"file"}

    bad = client.get(f"/api/repos/{repo_id}/metrics", params={"set": "junk"})
    assert bad.status_code == 400


def test_authors_and_author_filter(client, tiny_repo, tmp_path):
    repo_id, _ = _upload_and_wait(client, tiny_repo, tmp_path)
    authors = client.get(f"/api/repos/{repo_id}/authors").json()
    assert [a["name"] for a in authors] == ["Alice", "Bob"]
    alice = next(a for a in authors if a["name"] == "Alice")
    assert alice["commit_count"] == 3 and alice["churn"] == 6
    assert alice["merged_into"] is None

    rows = client.get(
        f"/api/repos/{repo_id}/metrics", params={"authors": str(alice["id"])}
    ).json()["rows"]
    assert all(r["author"] in ("ALL", "Alice <alice@example.com>") for r in rows)


def test_author_merge_crud_changes_metrics(client, tiny_repo, tmp_path):
    repo_id, _ = _upload_and_wait(client, tiny_repo, tmp_path)
    authors = client.get(f"/api/repos/{repo_id}/authors").json()
    alice = next(a for a in authors if a["name"] == "Alice")
    bob = next(a for a in authors if a["name"] == "Bob")

    r = client.post(
        f"/api/repos/{repo_id}/merges",
        json={"source_author_id": bob["id"], "target_author_id": alice["id"]},
    )
    assert r.status_code == 201

    def b_author_rows():
        rows = client.get(f"/api/repos/{repo_id}/metrics").json()["rows"]
        return [
            row
            for row in rows
            if row["object_type"] == "file"
            and row["path"] == "dir/b.txt"
            and row["author"] != "ALL"
        ]

    merged = b_author_rows()
    assert len(merged) == 1
    assert merged[0]["author"] == "Alice <alice@example.com>"
    assert merged[0]["added"] == 2

    assert client.delete(f"/api/repos/{repo_id}/merges/{bob['id']}").status_code == 204
    assert len(b_author_rows()) == 2

    bad = client.post(
        f"/api/repos/{repo_id}/merges",
        json={"source_author_id": alice["id"], "target_author_id": alice["id"]},
    )
    assert bad.status_code == 400


def test_commits_endpoint_paging_and_search(client, tiny_repo, tmp_path):
    repo_id, _ = _upload_and_wait(client, tiny_repo, tmp_path)
    page = client.get(f"/api/repos/{repo_id}/commits").json()
    assert page["total"] == 5
    assert len(page["items"]) == 5
    assert page["items"][0]["ts"] == 500  # newest first
    assert "Alice" in page["items"][0]["author"]

    prefix = tiny_repo["shas"][0][:10]
    hit = client.get(f"/api/repos/{repo_id}/commits", params={"q": prefix}).json()
    assert hit["total"] == 1
    assert hit["items"][0]["sha"] == tiny_repo["shas"][0]

    one = client.get(
        f"/api/repos/{repo_id}/commits", params={"limit": 2, "offset": 1}
    ).json()
    assert [i["ts"] for i in one["items"]] == [400, 300]


def test_delete_repo_removes_data(client, tiny_repo, tmp_path):
    repo_id, _ = _upload_and_wait(client, tiny_repo, tmp_path)
    repo_dir = Path(config.REPOS_DIR) / str(repo_id)
    assert repo_dir.exists()
    assert client.delete(f"/api/repos/{repo_id}").status_code == 204
    assert client.get(f"/api/repos/{repo_id}").status_code == 404
    assert client.get("/api/repos").json() == []
    assert not repo_dir.exists()
