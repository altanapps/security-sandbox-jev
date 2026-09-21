#!/usr/bin/env bash
# Start the Larkspur org API and the agent-factory control panel together.
#   ./run.sh            # org on :8000, panel on :8100
# Open http://localhost:8100
set -euo pipefail
cd "$(dirname "$0")"

ORG_PORT="${ORG_PORT:-8000}"
PANEL_PORT="${PANEL_PORT:-8100}"
export ORG_URL="http://localhost:${ORG_PORT}"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "note: ANTHROPIC_API_KEY is not set — dry-runs work, launches will fail." >&2
fi

echo "org   → http://localhost:${ORG_PORT}  (docs at /docs)"
echo "panel → http://localhost:${PANEL_PORT}"

uv run uvicorn org.main:app --port "${ORG_PORT}" --log-level warning &
ORG_PID=$!
uv run uvicorn factory.web:app --port "${PANEL_PORT}" --log-level warning &
PANEL_PID=$!

trap 'echo; echo "stopping…"; kill $ORG_PID $PANEL_PID 2>/dev/null || true' INT TERM
wait
