# backend image for railway: uv-managed python, locked deps, no dev extras.
# migrations are NOT run here -- railway.json's preDeployCommand runs
# `alembic upgrade head` on each release so the schema moves with the code
# (same ordering dev.sh uses locally).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# system CA certs for outbound https (yahoo, nba.com, anthropic)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# layer-cache the dependency install: lockfile first, source later
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

# railway injects PORT; default matches local dev for parity
ENV PORT=8000
# invoke the baked venv directly -- `uv run` would re-sync (pulling dev deps
# back in) on every container start. no --ssl-* flags in production: tls
# terminates at railway's edge, unlike local dev where dev.sh serves https
# for yahoo's localhost redirect uri
CMD ["sh", "-c", ".venv/bin/uvicorn ninecat.main:create_app --factory --host 0.0.0.0 --port ${PORT}"]
