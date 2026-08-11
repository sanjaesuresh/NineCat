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

    # _env_file=None bypasses the repo-root .env fallback, same as the missing-var
    # test below — otherwise these deletes just uncover whatever .env sets, and the
    # assertions would only pass by coincidence with the real .env's values
    settings = Settings(_env_file=None)

    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.dev_auth_enabled is False


def test_missing_required_var_raises_validation_error(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    # _env_file=None bypasses the repo-root .env fallback so this test is
    # independent of whatever real secrets happen to be configured there
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
