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

# tls when certs exist: yahoo's registered redirect uri is https://localhost:8000,
# so live oauth needs the backend serving https (mkcert certs in certs/)
if [[ -f certs/localhost.pem ]]; then
  BACKEND_SCHEME=https
  # next's server-side rewrite proxy must trust the mkcert ca (node ignores the system keychain)
  export BACKEND_URL="https://localhost:8000"
  export NODE_EXTRA_CA_CERTS="$(mkcert -CAROOT)/rootCA.pem"
  (cd backend && uv run uvicorn ninecat.main:create_app --factory --reload --port 8000 \
    --ssl-certfile ../certs/localhost.pem --ssl-keyfile ../certs/localhost-key.pem) &
else
  BACKEND_SCHEME=http
  (cd backend && uv run uvicorn ninecat.main:create_app --factory --reload --port 8000) &
fi
(cd frontend && npm run dev) &

echo "ninecat dev: backend ${BACKEND_SCHEME}://localhost:8000  frontend http://localhost:3000  (ctrl-c to stop)"
wait
