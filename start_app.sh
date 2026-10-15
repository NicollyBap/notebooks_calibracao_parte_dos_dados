#!/usr/bin/env bash
# Start Tumor Fit Tool on macOS or Linux:  ./start_app.sh
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/"
  exit 1
fi

[ -d .venv ] || { echo "Creating the virtual environment..."; "$PY" -m venv .venv; }
# shellcheck disable=SC1091
. .venv/bin/activate

if ! python -c "import fastapi, uvicorn, pandas, scipy, matplotlib, openpyxl" 2>/dev/null; then
  echo "Installing dependencies (first run only, needs internet)..."
  pip install -r requirements.txt
fi

URL="http://127.0.0.1:8000"
echo "Tumor Fit Tool is running at $URL  (press Ctrl+C to stop)"
(
  sleep 2
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  elif command -v open >/dev/null 2>&1; then open "$URL"
  fi
) >/dev/null 2>&1 &
exec python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
