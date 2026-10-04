"""POST and DELETE /api/v1/session (LLD-4 §3.1)."""

from fastapi import APIRouter, Request, Response

from app.api.auth import COOKIE_NAME, MAX_AGE_S, AccessConfig, issue_token, role_for_code
from app.api.errors import ApiError
from app.api.limits import FailureLimiter
from app.api.schemas import SessionRequest

router = APIRouter(tags=["session"])


def _client_ip(request: Request, header: str | None) -> str:
    """The caller's address for rate limiting (BD-04, BD-36).

    The deployed profile names CF-Connecting-IP: Render is fronted by Cloudflare, which
    sets it to the real client and overwrites any value a client sends. Elsewhere no
    header is trusted, since a client could rotate it to dodge the limit (code review
    RV-068). X-Forwarded-For is never used: Render passes client-supplied entries through.
    """
    if header:
        forwarded = request.headers.get(header, "").strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


@router.post("/session", status_code=204, response_class=Response)
async def start_session(body: SessionRequest, request: Request) -> Response:
    access: AccessConfig = request.app.state.access
    limiter: FailureLimiter = request.app.state.session_limiter
    ip = _client_ip(request, access.client_ip_header)
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
