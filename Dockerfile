# Single container running all three services (org, gateway, panel) behind
# Railway's $PORT. The public site is the panel/bench/incidents; org and gateway
# stay on localhost inside the container.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    ORG_URL=http://127.0.0.1:8000 \
    GATEWAY_URL=http://127.0.0.1:8080 \
    JUDGE=jev

# deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY . .

# $PORT is provided by Railway at runtime
CMD ["sh", "start.sh"]
