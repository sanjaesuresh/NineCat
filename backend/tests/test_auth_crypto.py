import pytest
from cryptography.fernet import Fernet, InvalidToken

from ninecat.auth.crypto import decrypt_token, encrypt_token
from ninecat.config import get_settings


@pytest.fixture(autouse=True)
def _real_fernet_key(monkeypatch: pytest.MonkeyPatch):
    # conftest's dummy TOKEN_ENCRYPTION_KEY isn't a valid Fernet key (not base64/32 bytes);
    # crypto tests need a real one, so generate and clear the settings cache to pick it up
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_encrypt_decrypt_round_trip():
    plaintext = "yahoo-refresh-token-abc123"
    ciphertext = encrypt_token(plaintext)
    assert ciphertext != plaintext
    assert decrypt_token(ciphertext) == plaintext


def test_encrypt_produces_different_ciphertext_each_time():
    # Fernet includes a random IV, so encrypting the same plaintext twice must not
    # produce identical ciphertext (would leak equality of stored tokens)
    plaintext = "yahoo-refresh-token-abc123"
    assert encrypt_token(plaintext) != encrypt_token(plaintext)


def test_decrypt_tampered_ciphertext_raises():
    ciphertext = encrypt_token("some-token")
    tampered = ciphertext[:-4] + ("aaaa" if ciphertext[-4:] != "aaaa" else "bbbb")
    with pytest.raises(InvalidToken):
        decrypt_token(tampered)


def test_decrypt_garbage_raises():
    with pytest.raises(InvalidToken):
        decrypt_token("not-a-valid-fernet-token")
