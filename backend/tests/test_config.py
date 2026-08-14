from datetime import date

import pytest
from pydantic import ValidationError

from ninecat.config import Settings, get_settings

# distinct dummy values so assertions can't accidentally pass against the real .env
REQUIRED_ENV = {
    "YAHOO_CLIENT_ID": "test-yahoo-client-id",
    "YAHOO_CLIENT_SECRET": "test-yahoo-client-secret",
    "YAHOO_REDIRECT_URI": "https://example.test/oauth/callback",
    "TOKEN_ENCRYPTION_KEY": "test-token-encryption-key",
    "SESSION_SECRET": "test-session-secret",
    "DATABASE_URL": "postgresql+psycopg://postgres:postgres@localhost:54329/postgres_test",
}


def test_get_settings_reads_values_from_env(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.test")
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("FANTASY_SEASON_START", "2026-10-19")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.yahoo_client_id == "test-yahoo-client-id"
    assert settings.yahoo_client_secret == "test-yahoo-client-secret"
    assert settings.yahoo_redirect_uri == "https://example.test/oauth/callback"
    assert settings.token_encryption_key == "test-token-encryption-key"
    assert settings.session_secret == "test-session-secret"
    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:54329/postgres_test"
    assert settings.frontend_origin == "https://app.example.test"
    assert settings.dev_auth_enabled is True
    # proves the field is actually declared and read, not silently dropped by
    # the model's extra="ignore" (which would otherwise fall back to the default)
    assert settings.fantasy_season_start == date(2026, 10, 19)

    get_settings.cache_clear()


def test_get_settings_caches_the_instance(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second

    get_settings.cache_clear()


def test_frontend_origin_and_dev_auth_enabled_have_defaults(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("DEV_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("FANTASY_SEASON_START", raising=False)

    # _env_file=None bypasses the repo-root .env fallback, same as the missing-var
    # test below — otherwise these deletes just uncover whatever .env sets, and the
    # assertions would only pass by coincidence with the real .env's values
    settings = Settings(_env_file=None)

    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.dev_auth_enabled is False
    assert settings.fantasy_season_start == date(2025, 10, 20)


def test_current_season_string_pins_the_league_year_mapping():
    """Pins the wrinkle documented on Settings.current_season: the warehouse's
    hyphenated "YYYY-YY" season string (NbaGame.season, PlayerSeasonAverage.season,
    PlayerProjection.season) and League.season's plain starting-year int must
    always agree on the leading year. The only two conversion points in the
    codebase are sync/league_sync.py's `int(info.season)` and api/routes.py's
    `str(league.season)` -- both read/produce the string's leading 4 digits as
    the year, so that contract is pinned here rather than re-derived (and
    possibly re-derived differently) in either of those files.
    """
    settings = Settings(_env_file=None, **REQUIRED_ENV)
    season_str = settings.current_season

    start_year, end_suffix = season_str.split("-")
    assert len(start_year) == 4 and start_year.isdigit()
    # end_suffix is the next year's last two digits, e.g. "26" for 2025->2026
    assert len(end_suffix) == 2 and end_suffix.isdigit()
    assert int(end_suffix) == (int(start_year) + 1) % 100

    # the League.season int a sync would write for a league on this season
    # (sync/league_sync.py: int(info.season)), and what api/routes.py's
    # str(league.season) would hand back to the frontend for it
    league_year = int(start_year)
    assert league_year == 2025
    assert str(league_year) == start_year


def test_missing_required_var_raises_validation_error(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    # _env_file=None bypasses the repo-root .env fallback so this test is
    # independent of whatever real secrets happen to be configured there
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
