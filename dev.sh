#!/usr/bin/env bash
# run the full ninecat dev stack: postgres (docker), backend :8000, frontend :3000
# usage: ./dev.sh   (ctrl-c stops both servers; postgres keeps running)
set -euo pipefail
cd "$(dirname "$0")"

(cd backend && docker compose up -d)
(cd backend && uv run alembic upgrade head)

# kill both servers (and their children) on exit so ctrl-c cleans up fully
cleanup() { kill 0 2>/dev/null || true; }
trap cleanup INT TERM EXIT

(cd backend && uv run uvicorn ninecat.main:create_app --factory --reload --port 8000) &
(cd frontend && npm run dev) &

echo "ninecat dev: backend http://localhost:8000  frontend http://localhost:3000  (ctrl-c to stop)"
wait
