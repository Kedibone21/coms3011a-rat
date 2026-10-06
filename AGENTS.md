# AGENTS.md — working notes for AI agents (Qoder)

RAT (Repo Analysis Tool, COMS3011A). Keep this file current; it is the single place an
agent should re-orient from.

## Architecture

- `backend/rat/ingest.py` — parses git history into SQLite in one pass (no per-commit subprocesses).
- `backend/rat/metrics.py` — all metric aggregation (SQL + light Python rollups).
- `backend/rat/api.py` — FastAPI endpoints; also serves the built SPA from `frontend/dist`.
- `frontend/` — React 18 + TypeScript + Vite 5 + ECharts SPA (no UI frameworks; CSS custom
  properties). Built to `frontend/dist`, which is committed so `api.py` serves it even where
  npm is unavailable.
- SQLite file at `data/rat.db`; cloned/extracted repositories under `data/repos/<id>/`.

## Metric semantics (must match the spec exactly)

- H̄ = non-merge commits reachable from the reference commit (default HEAD).
  Merge commits are excluded everywhere.
- Commit sets: `all`, `since t` (t ≤ committer time), `[i, j)` half-open, manual sha list.
  Membership uses the committer timestamp (`%ct`), not author time.
- Membership of a commit set: a path is present when its stats row's commit is in H,
  or when that commit's parent is in H (H plus its direct children). Zero-delta members
  still appear as all-zero rows (rename pairs; files first touched just after H).
- Per commit h vs its parent (root commit diffs against the empty tree — `git log --root`):
  added = l+ , removed = l− , growth δ = l+ − l− , churn λ = l+ + l−.
- Directory metrics are recursive sums of their descendants; repository metrics are the
  directory metrics of the root.
- Commit-set metrics sum over commits. Modifications n = number of commits with λ > 0 on
  the object. Modification frequency = n / |H| ; churn rate = λ / |H| (0 when |H| = 0).
- Author metrics: modifications and churn restricted to the author's commits;
  ownership ω = λ(author) / λ(all), 0 when λ = 0.
- Binary files are not measured. Renames detected at 50% similarity (`-M50%`); a file's
  history follows its new path after a rename.
- Deleted files record their removed lines at the deletion commit; the object remains
  addressable for commit sets that include its deletion.
- Author identity = mailmap-applied `%aN <%aE>` (`--use-mailmap`). Manual merges are
  query-time only (`author_merges` table) — never rewrite ingested data.
- Reference CSV format:
  `repo,ref_sha,commit_set,commit_count,object_type,path,author,added,removed,growth,churn,modifications,modification_frequency,churn_rate,ownership`.
  Aggregate rows use `author=ALL` and carry modifications (n_H,o), modification frequency
  and churn rate; per-author rows carry their own modifications (n_H,o,a) and ownership.
  Author rows exist at every object_type, only for authors with churn > 0 on the object.
- Attribution model (verified against reference CSVs): each commit's diff deltas land on the
  path as named in that commit (for renames: the new path). Nothing is moved retroactively:
  a pure rename contributes 0/0, and both old and new paths remain members of H[F] with a
  zero row when they have no other deltas (rates print as `0.0`). Rename entries record BOTH
  paths: the new path carries the deltas, the old path is stored as a 0/0 membership row in
  that same commit (the only trace for files that stayed empty their whole life). Directory
  rows are the ancestors of member files (root excluded - it is the repository row); paths
  carry no leading/trailing slash.
- Binaries: numstat `-` entries are skipped entirely (no stats, no membership).
- CSV export is byte-identical to the reference CSVs: `\n` line endings; rates are computed
  as `n * (1/|H|)` (reciprocal multiplication, not `n / |H|`); floats render as shortest
  round-trip digits - plain decimal for |v| >= 1e-5, scientific with unpadded exponent
  (e.g. `3.7986055319092363e-6`) below; row order is repository -> directories -> files
  (each path-sorted), author rows sorted by churn desc (ties by name).

## Conventions

- Backend: stdlib `sqlite3` (no ORM), no per-commit git subprocesses, batched inserts.
- Frontend: function components + hooks; charts via ECharts; shareable state (repo, commit
  set, path scope, author ids) lives in the URL hash. Metrics are fetched once per filter
  change and dir/file navigation is client-side; the path scope is only sent to the export
  and scoped-query APIs. Views: Overview (cards + charts), Metrics (drill-down table with
  per-author expansion), Authors (merge/unmerge panel).
- Tests in `tests/` (pytest); `scripts/verify.py` diffs engine output against `reference/*.csv`.
  `tests/golden/tiny_all.csv` is the byte-exact regression lock for the tiny fixture
  (regenerate only via `scripts/make_golden.py` after re-running verify.py).

## Common commands

- `./start.sh` — set up + serve on :8000 (builds the frontend when npm exists, else uses
  committed `frontend/dist`)
- `cd frontend && npm run dev` — Vite dev server on :5173 (proxies /api to :8000)
- `cd frontend && npm run build` — rebuild `frontend/dist` (commit it whenever the UI changes)
- `.venv/bin/python -m pytest tests -q`
- `.venv/bin/python scripts/verify.py` (clones cJSON/redis/git — slow the first time)
- `.venv/bin/python scripts/e2e_check.py --clone https://github.com/DaveGamble/cJSON.git` —
  live HTTP end-to-end check against a running server (zip ingest, byte-exact export, merge
  reversibility, clone ingest); leaves the created repos in the DB as a multi-repo demo
