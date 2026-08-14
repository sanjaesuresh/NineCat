from datetime import date
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
    # averages are worth showing instead of last year's. This is the single
    # source of truth for "what season is it" -- every warehouse sync
    # (nba_schedule, player_stats, player_positions) and every API route that
    # reads warehouse tables takes/derives its season from this setting, never
    # from a separately hardcoded or independently-computed string.
    #
    # wrinkle (documented here, not re-derived elsewhere): the warehouse uses
    # this hyphenated season string ("2025-26") as the season key on NbaGame,
    # PlayerSeasonAverage and PlayerProjection, but League.season (populated
    # from Yahoo, see sync/league_sync.py) is stored as a plain integer season-
    # start year (2025). The two representations meet at exactly two
    # conversion points in the codebase: sync/league_sync.py does
    # `int(info.season)` when writing League.season from Yahoo's response, and
    # api/routes.py does `str(league.season)` when shaping the League payload
    # for the frontend. If a third conversion is ever needed, it should derive
    # from current_season's leading 4 digits rather than reintroducing its own
    # int(season[:4])-style parsing.
    current_season: str = "2025-26"
    # off by default so tests/dev never spin up a background scheduler thread;
    # production sets SCHEDULER_ENABLED=true to run the nightly warehouse sync
    scheduler_enabled: bool = False
    # anchor for deriving fantasy-week date ranges when yahoo doesn't supply
    # week_start/week_end on the scoreboard: week 1 is the monday of the week
    # containing this date, monday-to-sunday from there. 2025-10-20 is the
    # monday of 2025-26 NBA opening week; bump alongside current_season.
    fantasy_season_start: date = date(2025, 10, 20)
    # Claude advisor (docs/claude-advisor-plan.md A2/A7). Declared -- not just
    # read from the environment -- because model_config sets extra="ignore",
    # which silently drops any undeclared key. Absent key is a first-class mode:
    # every feature degrades to its deterministic engine output and says so.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"

    @property
    def explanations_available(self) -> bool:
        """The single predicate for "can this deployment produce model-written
        explanations". Every caller asks this rather than testing the key
        directly, so the no-key path has exactly one definition."""
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    # cached so Settings (and its .env read) only happens once per process
    return Settings()
