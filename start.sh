#!/usr/bin/env bash
# RAT — Repository Analysis Tool
# Sets up and starts the full stack on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

echo "[rat] preparing Python environment..."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r backend/requirements.txt

if [ -f frontend/package.json ]; then
  echo "[rat] building frontend (falls back to committed frontend/dist)..."
  if command -v npm >/dev/null 2>&1; then
    if [ ! -d frontend/node_modules ]; then
      (cd frontend && npm ci --no-audit --no-fund) || echo "[rat] npm ci failed; using committed dist if available"
    fi
    (cd frontend && npm run build) || echo "[rat] npm build failed; using committed dist if available"
  else
    echo "[rat] npm not found; using committed frontend/dist if available"
  fi
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "[rat] WARNING: frontend/dist/index.html is missing and could not be built." >&2
fi

echo "[rat] starting server on http://127.0.0.1:${PORT}"
exec .venv/bin/uvicorn rat.api:app --app-dir backend --host 127.0.0.1 --port "${PORT}"
