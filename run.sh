#!/usr/bin/env bash
# Start the whole stack: org API, Jev gateway, and the control panel + bench.
#   ./run.sh
# Then open:
#   http://localhost:8100         control panel (inspect + launch agents)
#   http://localhost:8100/bench   gateway bench (fast allow/block feedback)
set -euo pipefail
cd "$(dirname "$0")"

ORG_PORT="${ORG_PORT:-8000}"
GATEWAY_PORT="${GATEWAY_PORT:-8080}"
PANEL_PORT="${PANEL_PORT:-8100}"
export ORG_URL="http://localhost:${ORG_PORT}"
export GATEWAY_URL="http://localhost:${GATEWAY_PORT}"
export JUDGE="${JUDGE:-jev}"

# Load TYPESAFE_API_KEY (and any others) from .env if present.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

if [ "${JUDGE}" = "jev" ] && [ -z "${TYPESAFE_API_KEY:-}" ]; then
  echo "warning: JUDGE=jev but TYPESAFE_API_KEY is unset — set it in .env, or run JUDGE=mock ./run.sh" >&2
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "note: ANTHROPIC_API_KEY unset — the bench works (no LLM), but agent launches will fail." >&2
fi

echo "org     → ${ORG_URL}  (docs at /docs)"
echo "gateway → ${GATEWAY_URL}  (judge=${JUDGE})"
echo "panel   → http://localhost:${PANEL_PORT}"
echo "bench   → http://localhost:${PANEL_PORT}/bench"

uv run uvicorn org.main:app --port "${ORG_PORT}" --log-level warning & P1=$!
sleep 1
uv run uvicorn gateway.proxy:app --port "${GATEWAY_PORT}" --log-level warning & P2=$!
uv run uvicorn factory.web:app --port "${PANEL_PORT}" --log-level warning & P3=$!

trap 'echo; echo "stopping…"; kill $P1 $P2 $P3 2>/dev/null || true' INT TERM
wait
