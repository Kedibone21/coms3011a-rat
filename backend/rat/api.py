"""FastAPI application: JSON API, CSV export, and SPA hosting.

Thin layer over rat.service / rat.metrics so the CLI, tests and web UI all
exercise the same code paths. Run with:  uvicorn rat.api:app  (from backend/).
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, metrics, service, sources

app = FastAPI(title="Repo Analysis Tool", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

INGEST_LOCK = threading.Lock()  # one acquire+ingest at a time


# ---- plumbing ------------------------------------------------------------------

def get_conn():
    conn = db.connect()
    db.init_db(conn)
    return conn


def repo_or_404(conn, repo_id: int):
    row = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no repo with id {repo_id}")
    return row


def _name_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return (tail[:-4] if tail.endswith(".git") else tail) or "repo"


def _run_ingest(repo_id: int, repo_dir: Path, ref: str, prepare) -> None:
    """Background worker: acquire (optional), ingest, track status."""
    conn = get_conn()
    try:
        with INGEST_LOCK:
            final_dir = prepare() if prepare else repo_dir
            service.complete_ingest(conn, repo_id, final_dir, ref=ref)
    except Exception as exc:  # status may already be 'error'; this is idempotent
        service.mark_error(conn, repo_id, exc)
    finally:
        conn.close()


def _spawn(repo_id: int, repo_dir: Path, ref: str, prepare) -> None:
    threading.Thread(
        target=_run_ingest, args=(repo_id, repo_dir, ref, prepare), daemon=True
    ).start()


class RepoFromUrl(BaseModel):
    url: str
    name: str | None = None
    ref: str = "HEAD"


class MergeIn(BaseModel):
    source_author_id: int
    target_author_id: int


# ---- repositories ----------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/repos")
def list_repos():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, source_type, source, ref_sha, commit_count,"
            " created_at, status, error FROM repos ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/repos/{repo_id}")
def repo_detail(repo_id: int):
    conn = get_conn()
    try:
        row = repo_or_404(conn, repo_id)
        d = dict(row)
        d.pop("repo_dir", None)
        return d
    finally:
        conn.close()


@app.post("/api/repos/url", status_code=202)
def add_repo_from_url(body: RepoFromUrl):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "only public http(s) clone URLs are supported")
    name = (body.name or "").strip() or _name_from_url(url)
    conn = get_conn()
    try:
        repo_id = service.create_repo(
            conn, name=name, source_type="url", source=url, repo_dir=""
        )
        repo_dir = Path(config.REPOS_DIR) / str(repo_id)
        with conn:
            conn.execute(
                "UPDATE repos SET repo_dir = ? WHERE id = ?", (str(repo_dir), repo_id)
            )
    finally:
        conn.close()
    _spawn(repo_id, repo_dir, body.ref, lambda: sources.clone_repo(url, repo_dir))
    return {"id": repo_id, "name": name, "status": "ingesting"}


@app.post("/api/repos/zip", status_code=202)
async def add_repo_from_zip(
    file: UploadFile = File(...),
    name: str | None = Form(None),
    ref: str = Form("HEAD"),
):
    filename = file.filename or "upload.zip"
    repo_name = (name or "").strip() or (Path(filename).stem or "uploaded")
    conn = get_conn()
    try:
        repo_id = service.create_repo(
            conn, name=repo_name, source_type="zip", source=filename, repo_dir=""
        )
        repo_dir = Path(config.REPOS_DIR) / str(repo_id)
        with conn:
            conn.execute(
                "UPDATE repos SET repo_dir = ? WHERE id = ?", (str(repo_dir), repo_id)
            )
    finally:
        conn.close()
    tmp_zip = Path(config.REPOS_DIR) / f"{repo_id}.upload.zip"
    tmp_zip.parent.mkdir(parents=True, exist_ok=True)
    tmp_zip.write_bytes(await file.read())

    def prepare() -> Path:
        try:
            return sources.extract_zip(tmp_zip, repo_dir)
        finally:
            tmp_zip.unlink(missing_ok=True)

    _spawn(repo_id, repo_dir, ref, prepare)
    return {"id": repo_id, "name": repo_name, "status": "ingesting"}


@app.delete("/api/repos/{repo_id}", status_code=204)
def delete_repo(repo_id: int):
    conn = get_conn()
    try:
        row = repo_or_404(conn, repo_id)
        with conn:
            conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
        d = Path(row["repo_dir"])
        try:
            d.resolve().relative_to(config.REPOS_DIR.resolve())
        except ValueError:
            pass  # local repos outside our data dir are never deleted
        else:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
    finally:
        conn.close()


# ---- commits, authors, merges ----------------------------------------------------

@app.get("/api/repos/{repo_id}/commits")
def commits(
    repo_id: int,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conn = get_conn()
    try:
        repo_or_404(conn, repo_id)
        params: dict = {"repo": repo_id}
        where = "c.repo_id = :repo"
        if q:
            esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where += " AND c.sha LIKE :q ESCAPE '\\'"
            params["q"] = esc + "%"
        total = conn.execute(
            f"SELECT COUNT(*) FROM commits c WHERE {where}", params
        ).fetchone()[0]
        items = [
            {"sha": r["sha"], "ts": r["ts"], "author": f"{r['name']} <{r['email']}>"}
            for r in conn.execute(
                f"SELECT c.sha, c.ts, a.name, a.email FROM commits c"
                f" JOIN authors a ON a.id = c.author_id"
                f" WHERE {where} ORDER BY c.ts DESC, c.id DESC LIMIT :lim OFFSET :off",
                {**params, "lim": limit, "off": offset},
            )
        ]
        return {"total": total, "items": items}
    finally:
        conn.close()


@app.get("/api/repos/{repo_id}/authors")
def authors(repo_id: int):
    conn = get_conn()
    try:
        repo_or_404(conn, repo_id)
        rows = conn.execute(
            """
            SELECT a.id, a.name, a.email,
                   (SELECT COUNT(*) FROM commits c WHERE c.author_id = a.id)
                       AS commit_count,
                   COALESCE((SELECT SUM(fs.added + fs.removed)
                             FROM file_stats fs
                             JOIN commits c2 ON c2.id = fs.commit_id
                             WHERE c2.author_id = a.id), 0) AS churn
            FROM authors a
            WHERE a.repo_id = ?
            ORDER BY churn DESC, a.name
            """,
            (repo_id,),
        ).fetchall()
        merges = {
            r["source_author_id"]: r["target_author_id"]
            for r in conn.execute(
                "SELECT source_author_id, target_author_id FROM author_merges"
                " WHERE repo_id = ?",
                (repo_id,),
            )
        }
        return [{**dict(r), "merged_into": merges.get(r["id"])} for r in rows]
    finally:
        conn.close()


@app.get("/api/repos/{repo_id}/merges")
def list_merges(repo_id: int):
    conn = get_conn()
    try:
        repo_or_404(conn, repo_id)
        rows = conn.execute(
            "SELECT source_author_id, target_author_id FROM author_merges"
            " WHERE repo_id = ? ORDER BY source_author_id",
            (repo_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/repos/{repo_id}/merges", status_code=201)
def add_merge(repo_id: int, body: MergeIn):
    if body.source_author_id == body.target_author_id:
        raise HTTPException(400, "source and target must differ")
    conn = get_conn()
    try:
        repo_or_404(conn, repo_id)
        ids = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM authors WHERE repo_id = ? AND id IN (?, ?)",
                (repo_id, body.source_author_id, body.target_author_id),
            )
        }
        missing = {body.source_author_id, body.target_author_id} - ids
        if missing:
            raise HTTPException(400, f"authors not in repo {repo_id}: {sorted(missing)}")
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO author_merges(repo_id, source_author_id, target_author_id)"
                " VALUES(?,?,?)",
                (repo_id, body.source_author_id, body.target_author_id),
            )
        return {
            "source_author_id": body.source_author_id,
            "target_author_id": body.target_author_id,
        }
    finally:
        conn.close()


@app.delete("/api/repos/{repo_id}/merges/{source_id}", status_code=204)
def remove_merge(repo_id: int, source_id: int):
    conn = get_conn()
    try:
        repo_or_404(conn, repo_id)
        with conn:
            conn.execute(
                "DELETE FROM author_merges WHERE repo_id = ? AND source_author_id = ?",
                (repo_id, source_id),
            )
    finally:
        conn.close()


# ---- metrics + export --------------------------------------------------------------

def _compute(repo_id: int, set_spec: str, path: str | None, authors_csv: str | None):
    conn = get_conn()
    try:
        repo = repo_or_404(conn, repo_id)
        if repo["status"] != "ready":
            raise HTTPException(409, f"repo is '{repo['status']}'; metrics unavailable")
        try:
            cs = metrics.parse_commit_set(set_spec)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        author_ids = None
        if authors_csv:
            try:
                author_ids = [int(x) for x in authors_csv.split(",") if x.strip()]
            except ValueError:
                raise HTTPException(400, "authors must be comma-separated integer ids")
        rows = metrics.compute_rows(
            conn, repo_id, cs, path=path or None, authors=author_ids
        )
        return repo, cs, rows
    finally:
        conn.close()


@app.get("/api/repos/{repo_id}/metrics")
def metrics_endpoint(
    repo_id: int,
    set_spec: str = Query("all", alias="set"),
    path: str | None = None,
    authors: str | None = None,
    object_type: str | None = None,
):
    repo, cs, rows = _compute(repo_id, set_spec, path, authors)
    if object_type:
        rows = [r for r in rows if r["object_type"] == object_type]
    return {
        "repo_id": repo_id,
        "repo": repo["name"],
        "ref_sha": repo["ref_sha"],
        "commit_set": metrics.set_label(cs),
        "commit_count": rows[0]["commit_count"] if rows else 0,
        "rows": rows,
    }


@app.get("/api/repos/{repo_id}/export.csv")
def export_csv(
    repo_id: int,
    set_spec: str = Query("all", alias="set"),
    path: str | None = None,
    authors: str | None = None,
):
    repo, cs, rows = _compute(repo_id, set_spec, path, authors)
    label = metrics.set_label(cs).replace(":", "-").replace(",", "-")
    filename = f"{repo['name']}_{label}.csv"
    return Response(
        metrics.rows_to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---- SPA hosting --------------------------------------------------------------------

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="spa")
else:

    @app.get("/")
    def index_hint():
        return {
            "name": "Repo Analysis Tool API",
            "docs": "/docs",
            "hint": "build frontend/dist to serve the web UI",
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
