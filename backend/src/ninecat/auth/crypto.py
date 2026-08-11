from cryptography.fernet import Fernet

from ninecat.config import get_settings


def _fernet() -> Fernet:
    # built fresh per call (not module-cached) so tests that monkeypatch the key
    # + clear get_settings' cache take effect immediately, with no stale Fernet instance
    return Fernet(get_settings().token_encryption_key.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext Yahoo OAuth token for storage."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored token.

    Tampered or garbage input raises cryptography.fernet.InvalidToken — left to
    propagate rather than wrapped, since Fernet's error already distinguishes
    invalid-signature/expired from other failures and callers can catch it directly.
    """
    return _fernet().decrypt(ciphertext.encode()).decode()
