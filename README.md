# RAT — Repository Analysis Tool

A web dashboard that ingests git repositories (zip upload or clone URL) and computes
per-file, per-directory, per-repository, per-commit-set and per-author metrics
(added/removed lines, growth, churn, modifications, modification frequency, churn rate
and author ownership).

Built for COMS3011A. Metric semantics follow the test specification exactly — see
`AGENTS.md` for a condensed reference of the metric rules.

## Quick start

No credentials or configuration are needed — the repository is public.

```bash
git clone https://github.com/Kedibone21/coms3011a-rat.git
cd coms3011a-rat
./start.sh
```

Then open http://127.0.0.1:8000

`start.sh` will:

1. create a Python virtualenv and install backend dependencies,
2. build the frontend (falls back to the committed `frontend/dist` if npm is unavailable),
3. serve the app on port 8000 (override with `PORT=9000 ./start.sh`).

Manual equivalent:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
.venv/bin/uvicorn rat.api:app --app-dir backend --port 8000
```

## Features

- Repository ingestion: zip archive (containing `.git`) or remote URL (full clone)
- Multiple repositories, each with its own reference commit
- Metrics for files, directories, the repository root, arbitrary commit sets, and authors
- Filtering: repository, author(s), file/directory subtree, commit set
  (all / since timestamp / half-open time range / manually selected commit list)
- Author merging: automatic through `.mailmap`, plus manual merge/unmerge in the UI
- CSV export in the provided reference format

## Verification

`reference/` contains the sample metric CSVs provided with the test.
`scripts/verify.py` clones each reference repo at the recorded `ref_sha`, ingests it with
the engine, and diffs the computed metrics against the CSV
(exact integers, floats compared within 1e-6).

```bash
.venv/bin/python scripts/verify.py
```

## Layout

- `backend/` — FastAPI app and metric engine (`backend/rat/`)
- `frontend/` — React + TypeScript + ECharts dashboard
- `scripts/` — verification and tooling
- `tests/` — engine unit tests and calibration fixtures
- `reference/` — provided reference metric CSVs

