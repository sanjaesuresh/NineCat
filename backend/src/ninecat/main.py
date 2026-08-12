from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ninecat.api.routes import router as api_router
from ninecat.auth.routes import router as auth_router
from ninecat.config import get_settings
from ninecat.jobs.scheduler import register_jobs


def create_app() -> FastAPI:
    app = FastAPI(title="NineCat API")

    # frontend origin is env-driven so the same build works across local dev and
    # deployed environments without a code change; default matches Next.js dev.
    frontend_origin = get_settings().frontend_origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # callback path is intentionally not under /api -- see ninecat.auth.routes docstring
    app.include_router(auth_router)
    app.include_router(api_router)

    # BackgroundScheduler (thread-based), not AsyncIOScheduler: the registered
    # jobs call synchronous SQLAlchemy, so a plain thread is the right fit and
    # keeps the scheduler off the app's event loop entirely.
    # Gated behind scheduler_enabled so tests/dev never start a background
    # thread by default -- production sets SCHEDULER_ENABLED=true.
    if get_settings().scheduler_enabled:
        scheduler = BackgroundScheduler()
        register_jobs(scheduler)

        @app.on_event("startup")
        def _start_scheduler() -> None:
            scheduler.start()

        @app.on_event("shutdown")
        def _stop_scheduler() -> None:
            # wait=False: default wait=True blocks app shutdown on a running
            # multi-minute sync job; let it finish in the background instead
            scheduler.shutdown(wait=False)

    return app
