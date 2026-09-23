#!/bin/sh
# Boot org + gateway on localhost, then the public panel on $PORT.
set -e
PORT="${PORT:-8100}"
export ORG_URL="http://127.0.0.1:8000"
export GATEWAY_URL="http://127.0.0.1:8080"
export JUDGE="${JUDGE:-jev}"

echo "starting org, gateway, panel (judge=$JUDGE, public port=$PORT)"
uv run uvicorn org.main:app --host 127.0.0.1 --port 8000 --log-level warning &
sleep 3
uv run uvicorn gateway.proxy:app --host 127.0.0.1 --port 8080 --log-level warning &
sleep 2
exec uv run uvicorn factory.web:app --host 0.0.0.0 --port "$PORT" --log-level warning
