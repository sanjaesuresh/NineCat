from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ninecat.config import get_settings


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

    return app
