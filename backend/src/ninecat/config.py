from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root is three levels up from this file (ninecat/ -> src/ -> backend/ -> repo root);
# resolving it here lets Settings find the real .env regardless of the process cwd
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """App configuration: loaded from process env, falling back to the repo-root .env."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    yahoo_client_id: str
    yahoo_client_secret: str
    yahoo_redirect_uri: str
    token_encryption_key: str
    session_secret: str
    database_url: str
    frontend_origin: str = "http://localhost:3000"
    dev_auth_enabled: bool = False
    # which PlayerSeasonAverage.season row the dashboard (roster averages, build
    # profile population) reads; bump this once a season when the new season's
    # averages are worth showing instead of last year's
    current_season: str = "2025-26"
    # off by default so tests/dev never spin up a background scheduler thread;
    # production sets SCHEDULER_ENABLED=true to run the nightly warehouse sync
    scheduler_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    # cached so Settings (and its .env read) only happens once per process
    return Settings()
