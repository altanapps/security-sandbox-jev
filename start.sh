#!/bin/sh
# Boot org + gateway on fixed internal ports, then the public panel on $PORT.
# Railway injects $PORT (often 8080), so internal ports must not collide with it.
set -e
PORT="${PORT:-8100}"
ORG_PORT=9001
GW_PORT=9002
export ORG_URL="http://127.0.0.1:${ORG_PORT}"
export GATEWAY_URL="http://127.0.0.1:${GW_PORT}"
export JUDGE="${JUDGE:-jev}"

echo "starting org:${ORG_PORT} gateway:${GW_PORT} panel:${PORT} (judge=${JUDGE})"
uv run uvicorn org.main:app --host 127.0.0.1 --port "${ORG_PORT}" --log-level warning &
sleep 3
uv run uvicorn gateway.proxy:app --host 127.0.0.1 --port "${GW_PORT}" --log-level warning &
sleep 2
exec uv run uvicorn factory.web:app --host 0.0.0.0 --port "${PORT}" --log-level warning
