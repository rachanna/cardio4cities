"""Smoke tests against a deployed URL (AT-29 partial): `uv run poe smoke https://…`.

Skipped unless a URL is given (--smoke-url or SMOKE_URL). They make no failed
access-code attempts, so repeated runs never trip the session rate limit.
"""

from collections.abc import Iterator

import httpx2
import pytest


@pytest.fixture(scope="module")
def http(smoke_url: str) -> Iterator[httpx2.Client]:
    with httpx2.Client(base_url=smoke_url, timeout=60, follow_redirects=True) as client:
        yield client


def test_root_serves_the_web_app(http: httpx2.Client) -> None:
    """AT-29: the deployed URL serves the web app at /."""
    response = http.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_health_is_ok_from_outside(http: httpx2.Client) -> None:
    """AT-29 (partial): /api/v1/health is ok for the stores and reference data."""
    response = http.get("/api/v1/health")
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "ok"
    for component in ("postgres", "qdrant", "neo4j", "reference_data"):
        assert body["components"][component]["status"] == "ok", component
    assert body["components"]["reference_data"]["slots"] == 16
    assert body["checker_independence"] == "different_family"


def test_health_reveals_no_hosts_or_keys(http: httpx2.Client) -> None:
    text = http.get("/api/v1/health").text.lower()

    for leak in ("onrender", "neo4j://", "bolt://", "postgresql://", "http://", "password", "key"):
        assert leak not in text


def test_api_errors_use_the_envelope(http: httpx2.Client) -> None:
    response = http.post("/api/v1/session", json={})  # malformed: not a failed attempt

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
