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

## E2E smoke test

Playwright drives the real stack end to end (landing page → dev-login → dashboard → settings, plus the draft board / punt / mock-draft flow), using a gated `POST /api/auth/dev-login` route (backend only, 404s unless `DEV_AUTH_ENABLED=true`) to skip live Yahoo OAuth.

1. `cd backend && docker compose up -d && uv run alembic upgrade head`
2. `cd backend && DEV_AUTH_ENABLED=true uv run uvicorn ninecat.main:create_app --factory` → http://localhost:8000
3. `cd frontend && npm run dev` → http://localhost:3000
4. `cd frontend && npx playwright test` (or `npm run test:e2e`)

Dev-login seeds a fixed dataset (idempotent — safe to re-run) directly into the docker Postgres instance: a demo user/league, a 3-player roster (`nba_person_id` 900001-900003) and a 72-player draftable pool with projections (900101-900199). The seed also grew to include a full demo NBA schedule (all 30 real `nba_teams` rows plus a week of `nba_games`, both keyed by real NBA.com ids) so weekly projections are demo-able. Unlike the pytest fixtures, these are real commits, and most backend tests now scope their row-count assertions to their own fixture's natural keys so they survive an unrelated commit — but if you still see spurious failures after running e2e or dev-login against a shared instance, delete the seeded rows before running the backend suite again:

```sh
docker exec $(docker ps -q --filter publish=54329) psql -U postgres -d postgres \
  -c "delete from leagues where yahoo_league_key='nba.l.999999';" \
  -c "delete from users where yahoo_guid='DEVUSER';" \
  -c "delete from nba_games where nba_game_id like 'dev-%';" \
  -c "delete from nba_teams where nba_team_id in (1610612737,1610612738,1610612751,1610612766,1610612741,1610612739,1610612742,1610612743,1610612765,1610612744,1610612745,1610612754,1610612746,1610612747,1610612763,1610612748,1610612749,1610612750,1610612740,1610612752,1610612760,1610612753,1610612755,1610612756,1610612757,1610612758,1610612759,1610612761,1610612762,1610612764);"
```

## Data notes

- Yahoo fixtures under `backend/tests/fixtures/yahoo/` are hand-built and must be re-recorded via the gateway's `record_fixture` helper once live API access is verified (see the fixtures README).
- The NBA schedule and player-stat warehouse syncs from NBA.com via `nba_api`; projections import from CSV (header contract documented in `backend/src/ninecat/warehouse/projections.py`'s module docstring). Full import steps: `docs/projections-import-runbook.md`.
- Moving to a new NBA season: `docs/season-rollover-checklist.md`.

Fantasy data provided by Yahoo Fantasy. NineCat is not affiliated with or endorsed by Yahoo or the NBA.
