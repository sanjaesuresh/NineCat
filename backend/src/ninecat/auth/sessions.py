from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from ninecat.config import get_settings
from ninecat.db import get_session
from ninecat.models import User

SESSION_COOKIE_NAME = "ninecat_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days

# fixed, non-secret salt namespaces this serializer's signatures away from any other
# itsdangerous use of the same session_secret elsewhere in the app
_SESSION_SALT = "ninecat-session"


def _serializer() -> URLSafeTimedSerializer:
    # built fresh per call (not module-cached) so tests that monkeypatch the secret
    # + clear get_settings' cache take effect immediately
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SESSION_SALT)


def create_session_cookie(user_id: int) -> str:
    """Sign a user id into a tamper-evident, time-stamped cookie value."""
    return _serializer().dumps(user_id)


def verify_session_cookie(value: str) -> int | None:
    """Return the user id from a valid, unexpired cookie, or None if invalid/expired/garbage."""
    try:
        loaded = _serializer().loads(value, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    # defensive: loads() can return arbitrary JSON-decoded data for a well-signed but
    # unexpected payload shape, so only trust it if it actually deserialized to an int
    return loaded if isinstance(loaded, int) else None


def set_session_on_response(response: Response, user_id: int) -> None:
    """Attach the signed session cookie to a response after successful login."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_cookie(user_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def current_user(request: Request, db: Session = Depends(get_session)) -> User:
    """FastAPI dependency resolving the session cookie to a live User, or 401."""
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_cookie(cookie_value) if cookie_value is not None else None
    user = db.get(User, user_id) if user_id is not None else None
    # soft-deleted accounts must be rejected even with a validly-signed, unexpired
    # cookie: deletion should revoke access immediately, not wait out the 30-day cookie
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
