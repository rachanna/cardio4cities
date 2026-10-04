"""Access codes and signed session cookies (LLD-4 §3.1, §10).

The token is `<payload>.<signature>`: base64url JSON claims `{role, iat, exp}`
signed with HMAC-SHA256 under SESSION_SECRET. Codes are compared in constant time.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Literal

from fastapi import Request

from app.api.errors import ApiError

Role = Literal["viewer", "admin"]
COOKIE_NAME = "c4c_session"
MAX_AGE_S = 43_200  # 12 hours (LLD-4 §3.1)


@dataclass(frozen=True)
class AccessConfig:
    """Secrets: never in a repr or a log line (code review RV-074)."""

    access_code: str = field(repr=False)
    admin_code: str = field(repr=False)
    session_secret: str = field(repr=False)


@dataclass(frozen=True)
class Session:
    role: Role
    iat: int
    exp: int


def role_for_code(code: str, access: AccessConfig) -> Role | None:
    """Both comparisons always run, so timing does not reveal which code matched."""
    given = code.encode()
    is_admin = hmac.compare_digest(given, access.admin_code.encode())
    is_viewer = hmac.compare_digest(given, access.access_code.encode())
    if is_admin:
        return "admin"
    return "viewer" if is_viewer else None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def issue_token(role: Role, secret: str, now: float | None = None) -> str:
    iat = int(time.time() if now is None else now)
    payload = _b64(json.dumps({"role": role, "iat": iat, "exp": iat + MAX_AGE_S}).encode())
    return f"{payload}.{_sign(payload, secret)}"


def read_token(token: str, secret: str, now: float | None = None) -> Session | None:
    if not token.isascii():  # compare_digest refuses non-ASCII text with TypeError (RV-069)
        return None
    payload, _, signature = token.partition(".")
    if not payload or not hmac.compare_digest(signature, _sign(payload, secret)):
        return None
    try:
        claims = json.loads(_unb64(payload))
        session = Session(role=claims["role"], iat=int(claims["iat"]), exp=int(claims["exp"]))
    except (ValueError, KeyError, TypeError):
        return None
    if session.role not in ("viewer", "admin"):
        return None
    if (time.time() if now is None else now) >= session.exp:
        return None
    return session


def current_session(request: Request) -> Session:
    """Dependency for endpoints that need any role."""
    access: AccessConfig = request.app.state.access
    session = read_token(request.cookies.get(COOKIE_NAME, ""), access.session_secret)
    if session is None:
        raise ApiError(401, "unauthenticated", "Enter the access code to continue.")
    return session


def admin_session(request: Request) -> Session:
    """Dependency for admin-only endpoints."""
    session = current_session(request)
    if session.role != "admin":
        raise ApiError(403, "forbidden", "This option is for the presenter only.")
    return session
