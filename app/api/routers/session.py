"""POST and DELETE /api/v1/session (LLD-4 §3.1)."""

from fastapi import APIRouter, Request, Response

from app.api.auth import COOKIE_NAME, MAX_AGE_S, AccessConfig, issue_token, role_for_code
from app.api.errors import ApiError
from app.api.limits import FailureLimiter
from app.api.schemas import SessionRequest

router = APIRouter(tags=["session"])


def _client_ip(request: Request) -> str:
    """The caller's address for rate limiting (BD-04).

    Render is fronted by Cloudflare, which sets CF-Connecting-IP to the real client
    and overwrites any value a client sends. X-Forwarded-For is not used: Render
    passes client-supplied entries through, so it can be forged to dodge the limit.
    Without the header (local runs), the direct peer address is used.
    """
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


@router.post("/session", status_code=204, response_class=Response)
async def start_session(body: SessionRequest, request: Request) -> Response:
    access: AccessConfig = request.app.state.access
    limiter: FailureLimiter = request.app.state.session_limiter
    ip = _client_ip(request)
    if limiter.blocked(ip):
        raise ApiError(429, "rate_limited", "Too many attempts. Wait ten minutes, then try again.")
    role = role_for_code(body.access_code, access)
    if role is None:
        limiter.record_failure(ip)
        raise ApiError(401, "unauthenticated", "That access code is not right.")
    response = Response(status_code=204)
    response.set_cookie(
        COOKIE_NAME,
        issue_token(role, access.session_secret),
        max_age=MAX_AGE_S,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@router.delete("/session", status_code=204, response_class=Response)
async def end_session() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    return response
