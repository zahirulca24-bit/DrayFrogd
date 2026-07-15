import base64
import hashlib
import hmac
import math
import secrets
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings


@dataclass
class _LoginAttemptState:
    failures: list[float] = field(default_factory=list)
    blocked_until: float = 0.0


_login_attempts: dict[str, _LoginAttemptState] = {}
_login_attempt_lock = RLock()


def is_auth_configured() -> bool:
    return bool(settings.admin_username and settings.admin_password_hash and settings.session_secret)


def _serializer() -> URLSafeTimedSerializer:
    if not settings.session_secret:
        raise RuntimeError("SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(settings.session_secret, salt="session-token")


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Supported format:
    pbkdf2_sha256$<iterations>$<salt>$<base64_digest>
    """
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        iteration_count = int(iterations)
    except (TypeError, ValueError):
        return False

    if algorithm != "pbkdf2_sha256" or iteration_count <= 0:
        return False

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iteration_count,
    )
    actual = base64.b64encode(derived).decode("utf-8")
    return hmac.compare_digest(actual, expected)


def authenticate_admin(username: str, password: str) -> bool:
    if not is_auth_configured():
        return False
    if not hmac.compare_digest(username, settings.admin_username):
        return False
    return verify_password(password, settings.admin_password_hash)


def create_session_token(username: str) -> tuple[str, str]:
    if not settings.session_secret:
        raise ValueError("SESSION_SECRET is not configured")
    token_id = secrets.token_urlsafe(16)
    issued_at = int(time.time())
    ttl = max(int(settings.session_ttl_seconds), 1)
    payload: dict[str, Any] = {
        "sub": username,
        "tid": token_id,
        "iat": issued_at,
        "exp": issued_at + ttl,
    }
    token = _serializer().dumps(payload)
    return token, token_id


def verify_session_token(token: str) -> dict[str, Any]:
    ttl = max(int(settings.session_ttl_seconds), 1)
    try:
        payload = _serializer().loads(token, max_age=ttl)
    except SignatureExpired as exc:
        raise ValueError("Token expired") from exc
    except BadSignature as exc:
        raise ValueError("Invalid token") from exc

    if not isinstance(payload, dict) or "sub" not in payload or "tid" not in payload:
        raise ValueError("Invalid token payload")

    now = int(time.time())
    try:
        expires_at = int(payload.get("exp"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid token expiry") from exc
    if expires_at <= now:
        raise ValueError("Token expired")

    return payload


def check_login_rate_limit(username: str, client_id: str) -> int:
    """Return retry-after seconds, or zero when another attempt is allowed."""
    now = time.monotonic()
    retry_after = 0
    with _login_attempt_lock:
        _prune_login_attempts(now)
        for key in _login_attempt_keys(username, client_id):
            state = _login_attempts.get(key)
            if state is None:
                continue
            if state.blocked_until > now:
                retry_after = max(retry_after, math.ceil(state.blocked_until - now))
    return retry_after


def record_login_failure(username: str, client_id: str) -> int:
    """Record a failed login and return the active retry-after period, if blocked."""
    now = time.monotonic()
    max_attempts = max(int(settings.login_max_attempts), 1)
    block_seconds = max(int(settings.login_block_seconds), 1)
    window_seconds = max(int(settings.login_window_seconds), 1)
    retry_after = 0

    with _login_attempt_lock:
        _prune_login_attempts(now)
        for key in _login_attempt_keys(username, client_id):
            state = _login_attempts.setdefault(key, _LoginAttemptState())
            state.failures = [
                timestamp
                for timestamp in state.failures
                if now - timestamp <= window_seconds
            ]
            state.failures.append(now)
            if len(state.failures) >= max_attempts:
                state.blocked_until = max(state.blocked_until, now + block_seconds)
            if state.blocked_until > now:
                retry_after = max(retry_after, math.ceil(state.blocked_until - now))

    return retry_after


def clear_login_failures(username: str, client_id: str) -> None:
    with _login_attempt_lock:
        for key in _login_attempt_keys(username, client_id):
            _login_attempts.pop(key, None)


def reset_login_rate_limiter() -> None:
    """Test/support hook; production callers normally never need this."""
    with _login_attempt_lock:
        _login_attempts.clear()


def _login_attempt_keys(username: str, client_id: str) -> tuple[str, str]:
    normalized_username = str(username or "").strip().lower() or "<empty>"
    normalized_client = str(client_id or "").strip().lower() or "<unknown>"
    # A username bucket prevents spoofed X-Forwarded-For values from bypassing
    # throttling; a client bucket also slows broad credential spraying.
    return (f"username:{normalized_username}", f"client:{normalized_client}")


def _prune_login_attempts(now: float) -> None:
    window_seconds = max(int(settings.login_window_seconds), 1)
    stale_keys: list[str] = []
    for key, state in _login_attempts.items():
        state.failures = [
            timestamp
            for timestamp in state.failures
            if now - timestamp <= window_seconds
        ]
        if not state.failures and state.blocked_until <= now:
            stale_keys.append(key)
    for key in stale_keys:
        _login_attempts.pop(key, None)
