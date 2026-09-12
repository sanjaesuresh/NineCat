# Deploying NineCat

Production topology (per `docs/2026-08-11-9cat-foundation.md`, Task 19):

- **Supabase** — production Postgres. Only the connection string is consumed; no
  Supabase client libraries are used.
- **Railway** — the FastAPI backend, built from `backend/Dockerfile`.
  `backend/railway.json` runs `alembic upgrade head` as the pre-deploy command on
  every release, then starts uvicorn on Railway's injected `PORT`. TLS terminates at
  Railway's edge (the container serves plain HTTP — unlike local dev, where `dev.sh`
  serves HTTPS because Yahoo's registered dev redirect URI is `https://localhost`).
- **Vercel** — the Next.js frontend. `frontend/next.config.ts` rewrites `/api/*` AND
  `/auth/*` to `BACKEND_URL`, so the browser only ever talks to the frontend origin
  and the session cookie stays first-party. The Yahoo OAuth callback
  (`/auth/yahoo/callback`) rides the same rewrite — this is why the production
  redirect URI uses the frontend domain, not the Railway URL.

## Environment variables

Values are secrets — set them in each platform's dashboard, never in git.

Backend (Railway service variables; names match `backend/src/ninecat/config.py`):

| Variable | What it is |
| --- | --- |
| `DATABASE_URL` | Supabase Postgres connection string, `postgresql+psycopg://` scheme |
| `YAHOO_CLIENT_ID` / `YAHOO_CLIENT_SECRET` | the approved Yahoo app's credentials |
| `YAHOO_REDIRECT_URI` | `https://<your-domain>/auth/yahoo/callback` — must byte-match the Yahoo developer console entry |
| `TOKEN_ENCRYPTION_KEY` | Fernet key encrypting stored Yahoo refresh tokens — generate fresh for prod, losing it invalidates stored logins |
| `SESSION_SECRET` | signs session cookies — generate fresh for prod |
| `FRONTEND_ORIGIN` | `https://<your-domain>` (CORS + post-OAuth redirect target) |
| `SCHEDULER_ENABLED` | `true` in production — runs the nightly warehouse sync (schedule, averages, player index, positions) |
| `ANTHROPIC_API_KEY` | optional; absent means every feature degrades to deterministic engine output and says so |
| `CURRENT_SEASON` / `FANTASY_SEASON_START` | optional overrides; defaults live in config.py and move at season rollover (`docs/season-rollover-checklist.md`) |
| `DEV_AUTH_ENABLED` | NEVER set in production — it gates the dev-login seed route (defaults to false) |

Frontend (Vercel project env):

| Variable | What it is |
| --- | --- |
| `BACKEND_URL` | the Railway service's public URL, e.g. `https://ninecat-backend.up.railway.app` |

## Health-check story

`GET /api/health` returns `{"status": "ok"}` with no database access — a pure
liveness probe, wired as Railway's `healthcheckPath` so a container that can't serve
requests never receives traffic. Database readiness is proven separately, at release
time: the pre-deploy `alembic upgrade head` must succeed against `DATABASE_URL`
before the new version starts, so "the app is up" implies "the schema matched the
code at boot". Job health after deploy is visible in the jobs observability page
(dashboard) and Railway logs — the nightly sync logs per-step row counts at INFO,
and a 0-row schedule sync is expected only before NBA.com publishes a season.

## Manual provisioning steps (need your accounts — not automatable)

1. Create a Supabase project; copy the Postgres connection string (URI form), and
   convert the scheme to `postgresql+psycopg://` for `DATABASE_URL`.
2. Create a Railway service from this repo with root directory `backend/`; Railway
   picks up `railway.json` and the Dockerfile automatically. Set the backend env
   vars from the table above. First deploy runs migrations against the empty
   Supabase database.
3. Create a Vercel project from this repo with root directory `frontend/`; set
   `BACKEND_URL` to the Railway URL. Deploy.
4. Point your domain at Vercel; set `FRONTEND_ORIGIN` on Railway to the final
   `https://` domain.
5. In the Yahoo developer console, change the app's redirect URI to
   `https://<your-domain>/auth/yahoo/callback`, and set the same value as
   `YAHOO_REDIRECT_URI` on Railway. Note: this replaces the localhost dev URI —
   local OAuth stops working while it points at production unless Yahoo lets the
   app keep both (check the console; if only one URI is allowed, switch it back
   for dev sessions).
6. Verify (in order): landing page over HTTPS on your domain; `GET /api/health`
   through the rewrite returns ok; privacy/terms pages reachable (Yahoo's
   application requirement); then the full Yahoo login flow end to end.
7. Seed production data: run the warehouse sync once (or wait for the nightly), then
   import projections per `docs/projections-import-runbook.md`.

UNVERIFIABLE until the pieces exist: everything in steps 4–6 needs the live domain
and the Yahoo console change; the full login flow additionally needs Yahoo's fantasy
allowlist binding to be active for the client id (see the phase-3 ledger — approval
alone has not been sufficient). Docker image and migration-on-release behavior are
verifiable locally with `docker build backend/`.
