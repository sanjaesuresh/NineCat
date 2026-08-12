# NineCat

NineCat is a fantasy basketball analytics web app for Yahoo Fantasy head-to-head 9-category leagues. It signs users in with their Yahoo account, syncs their league (settings, teams, standings, rosters), and builds a deterministic per-category "build profile" (strong / average / punt) across the nine scoring categories — FG%, FT%, 3PM, PTS, REB, AST, ST, BLK, TO — backed by an NBA schedule and player-stats warehouse. Draft, matchup, waiver, and trade tools layer on top of this foundation. All Yahoo access is read-only: NineCat recommends, it never acts on your team.

## Layout

- `backend/` — FastAPI app (Python 3.12+, managed with [uv](https://docs.astral.sh/uv/)): Yahoo OAuth, API gateway with caching/refresh, league sync, NBA data warehouse, z-score engine, Postgres via SQLAlchemy/Alembic.
- `frontend/` — Next.js (App Router, TypeScript, Tailwind): landing page and dashboard. Proxies `/api/*` and `/auth/*` to the backend so session cookies stay first-party.

## Setup

1. Copy `.env.example` to `.env` at the repo root and fill in your Yahoo app credentials (`YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`) plus fresh `TOKEN_ENCRYPTION_KEY` / `SESSION_SECRET` values. The defaults for everything else work for local dev.
2. Start Postgres: `cd backend && docker compose up -d` (Postgres 16 on port 54329).
3. Apply migrations: `cd backend && uv run alembic upgrade head`.
4. Run the backend: `cd backend && uv run uvicorn ninecat.main:create_app --factory --reload` → http://localhost:8000 (health check at `/api/health`).
5. Run the frontend: `cd frontend && npm install && npm run dev` → http://localhost:3000.

Note: live Yahoo login requires HTTPS on the callback (`https://localhost:8000/auth/yahoo/callback` must match the redirect URI registered on your Yahoo app), so end-to-end OAuth needs a local TLS cert (e.g. [mkcert](https://github.com/FiloSottile/mkcert)) — everything else runs over plain HTTP.

## Tests

- Backend: `cd backend && uv run pytest` (needs the docker Postgres up; DB-backed tests roll back per test and skip cleanly if Postgres is down). No live Yahoo or NBA calls — everything runs against recorded fixtures.
- Frontend: `cd frontend && npx vitest run`, plus `npm run lint` and `npm run build`.

## Data notes

- Yahoo fixtures under `backend/tests/fixtures/yahoo/` are hand-built and must be re-recorded via the gateway's `record_fixture` helper once live API access is verified (see the fixtures README).
- The NBA schedule and player-stat warehouse syncs from NBA.com via `nba_api`; projections import from CSV (header contract documented in `backend/src/ninecat/warehouse/projections.py`'s module docstring).

Fantasy data provided by Yahoo Fantasy. NineCat is not affiliated with or endorsed by Yahoo or the NBA.
