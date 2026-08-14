# NineCat

NineCat is a fantasy basketball analytics web app for Yahoo Fantasy head-to-head 9-category leagues. It signs users in with their Yahoo account, syncs their league (settings, teams, standings, rosters), and builds a deterministic per-category "build profile" (strong / average / punt) across the nine scoring categories — FG%, FT%, 3PM, PTS, REB, AST, ST, BLK, TO — backed by an NBA schedule and player-stats warehouse. Draft, matchup, waiver, and trade tools layer on top of this foundation. All Yahoo access is read-only: NineCat recommends, it never acts on your team.

Every recommendation you see is arithmetic. An optional Claude advisor can add written reasoning on top of it — see [Claude advisor](#claude-advisor) — but the engine decides what is on the list, and the advisor only ever reorders within that list and explains it. Without an API key configured, every feature works exactly as it always did and says plainly that explanations are off.

## Layout

- `backend/` — FastAPI app (Python 3.12+, managed with [uv](https://docs.astral.sh/uv/)): Yahoo OAuth, API gateway with caching/refresh, league sync, NBA data warehouse, z-score engine, the optional Claude advisor (`src/ninecat/advisor/`), Postgres via SQLAlchemy/Alembic.
- `frontend/` — Next.js (App Router, TypeScript, Tailwind): landing page and dashboard. Proxies `/api/*` and `/auth/*` to the backend so session cookies stay first-party.

## Setup

1. Copy `.env.example` to `.env` at the repo root and fill in your Yahoo app credentials (`YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`) plus fresh `TOKEN_ENCRYPTION_KEY` / `SESSION_SECRET` values. The defaults for everything else work for local dev.
2. Start Postgres: `cd backend && docker compose up -d` (Postgres 16 on port 54329).
3. Apply migrations: `cd backend && uv run alembic upgrade head`.
4. Run the backend: `cd backend && uv run uvicorn ninecat.main:create_app --factory --reload` → http://localhost:8000 (health check at `/api/health`).
5. Run the frontend: `cd frontend && npm install && npm run dev` → http://localhost:3000.

Note: live Yahoo login requires HTTPS on the callback (`https://localhost:8000/auth/yahoo/callback` must match the redirect URI registered on your Yahoo app), so end-to-end OAuth needs a local TLS cert (e.g. [mkcert](https://github.com/FiloSottile/mkcert)) — everything else runs over plain HTTP.

## Claude advisor

Optional. Set `ANTHROPIC_API_KEY` (and optionally `ANTHROPIC_MODEL`, default `claude-opus-5`) in `.env` and the Draft, Matchup, Adds and Trades endpoints add a `explanations` block: the engine's own shortlist, reordered by the model, with a short written reason per entry and the model name shown alongside it.

What it will and won't do:

- **The engine leads.** The model only ever sees a shortlist the engine produced. It may reorder within that shortlist and explain it. It cannot add a player, drop one, or contradict a punt you chose. This is enforced in code (`backend/src/ninecat/advisor/validation.py`), not just asked for in the prompt — a response that adds or drops an entry is rejected outright and the page falls back to the engine's ordering with a note saying so.
- **No key is a supported mode, not a broken one.** Leave `ANTHROPIC_API_KEY` unset and every feature returns its deterministic result plus an honest note. This is the path the entire test suite and every CI run take; no test makes a network call to Anthropic.
- **Answers are cached** in an `advisor_cache` table keyed by a hash of the normalized input. The table is deliberately not user-scoped: prompts contain no user identifiers, so the same question from two users is the same question and the answer is shared.
- **What goes in a prompt:** player names, stat-derived numbers, category context, and your own build/punt choices. Never Yahoo tokens, user ids, email, or other people's team names. There are pinned tests asserting this for both the prompt builder and each endpoint that calls it.
- **Cost** is bounded by the cache plus a per-feature cap on how many rows are sent (4–6 depending on the feature). Token usage is logged per call; prompt contents are not.

Prompt quality has not been evaluated against real output — see `docs/claude-advisor-build-plan.md` for the current status and open questions.

## Tests

- Backend: `cd backend && uv run pytest` (needs the docker Postgres up; DB-backed tests roll back per test and skip cleanly if Postgres is down). No live Yahoo, NBA, or Anthropic calls — everything runs against recorded fixtures and injected fakes.
- Frontend: `cd frontend && npx vitest run`, plus `npm run lint` and `npm run build`.

## E2E smoke test

Playwright drives the real stack end to end (landing page → dev-login → dashboard → settings, plus the draft board / punt / mock-draft flow and the advisor's no-key path), using a gated `POST /api/auth/dev-login` route (backend only, 404s unless `DEV_AUTH_ENABLED=true`) to skip live Yahoo OAuth.

`e2e/advisor.spec.ts` covers the Claude advisor's degraded path specifically: the backend command below sets no `ANTHROPIC_API_KEY`, so those tests prove the pages still render their rankings and say why explanations are off. The explanations-present path is deliberately not covered end to end — it needs a real key and a real API call.

1. `cd backend && docker compose up -d && uv run alembic upgrade head`
2. `cd backend && DEV_AUTH_ENABLED=true uv run uvicorn ninecat.main:create_app --factory` → http://localhost:8000
3. `cd frontend && npm run dev` → http://localhost:3000
4. `cd frontend && npx playwright test` (or `npm run test:e2e`)

Dev-login seeds a fixed dataset (idempotent — safe to re-run) directly into the docker Postgres instance: a demo user/league, a 3-player roster (`nba_person_id` 900001-900003) and a 72-player draftable pool with projections (900101-900199). The seed also grew to include a full demo NBA schedule (all 30 real `nba_teams` rows plus a week of `nba_games`, both keyed by real NBA.com ids) so weekly projections are demo-able. Unlike the pytest fixtures, these are real commits, and most backend tests now scope their row-count assertions to their own fixture's natural keys so they survive an unrelated commit — but if you still see spurious failures after running e2e or dev-login against a shared instance, delete the seeded rows before running the backend suite again:

The seeded **players** are the ones that actually poison later test runs: they land in the draftable pool, so a fixture that expects its own free agent to top a streaming plan or a draft board silently gets a dev-seeded one instead, and the failure points at the assertion rather than at the pollution. Delete them along with everything else — the `nba_players` line below is the one that matters most and the one easiest to forget.

```sh
docker exec $(docker ps -q --filter publish=54329) psql -U postgres -d postgres \
  -c "delete from leagues where yahoo_league_key='nba.l.999999';" \
  -c "delete from users where yahoo_guid='DEVUSER';" \
  -c "delete from nba_games where nba_game_id like 'dev-%';" \
  -c "delete from nba_players where nba_person_id between 900001 and 900199;" \
  -c "delete from nba_teams where nba_team_id in (1610612737,1610612738,1610612751,1610612766,1610612741,1610612739,1610612742,1610612743,1610612765,1610612744,1610612745,1610612754,1610612746,1610612747,1610612763,1610612748,1610612749,1610612750,1610612740,1610612752,1610612760,1610612753,1610612755,1610612756,1610612757,1610612758,1610612759,1610612761,1610612762,1610612764);"
```

## Data notes

- Yahoo fixtures under `backend/tests/fixtures/yahoo/` are hand-built and must be re-recorded via the gateway's `record_fixture` helper once live API access is verified (see the fixtures README).
- The NBA schedule and player-stat warehouse syncs from NBA.com via `nba_api`; projections import from CSV (header contract documented in `backend/src/ninecat/warehouse/projections.py`'s module docstring). Full import steps: `docs/projections-import-runbook.md`.
- Moving to a new NBA season: `docs/season-rollover-checklist.md`.

Fantasy data provided by Yahoo Fantasy. NineCat is not affiliated with or endorsed by Yahoo or the NBA.
