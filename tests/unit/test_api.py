"""Session (LLD-4 §3.1), health (LLD-4 §7), error envelope (§6) and the web root, over HTTP."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.auth import COOKIE_NAME, MAX_AGE_S, issue_token, read_token
from app.api.limits import FailureLimiter
from app.main import create_app
from tests.unit.fake_adapters import probes as fake_probes
from tests.unit.fake_adapters import relational as fake_relational

REGISTRY = {
    "relational": {"postgres": "tests.unit.fake_adapters.relational:make"},
    "probe:vector": {"qdrant": "tests.unit.fake_adapters.probes:make_qdrant"},
    "probe:graph": {"graphiti_neo4j": "tests.unit.fake_adapters.probes:make_neo4j"},
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> Iterator[TestClient]:
    for name, value in valid_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(fake_probes, "DOWN", set())
    with TestClient(
        create_app(env_file=None, registry=REGISTRY), base_url="https://testserver"
    ) as c:
        yield c


# --- session ------------------------------------------------------------------


def test_access_code_starts_viewer_session_with_secure_cookie(
    client: TestClient, valid_env: dict[str, str]
) -> None:
    response = client.post("/api/v1/session", json={"access_code": valid_env["ACCESS_CODE"]})

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", f"Max-Age={MAX_AGE_S}"):
        assert flag.lower() in cookie.lower()
    session = read_token(client.cookies[COOKIE_NAME], valid_env["SESSION_SECRET"])
    assert session is not None
    assert session.role == "viewer"


def test_admin_code_starts_admin_session(client: TestClient, valid_env: dict[str, str]) -> None:
    client.post("/api/v1/session", json={"access_code": valid_env["ADMIN_CODE"]})

    session = read_token(client.cookies[COOKIE_NAME], valid_env["SESSION_SECRET"])
    assert session is not None
    assert session.role == "admin"


def test_wrong_code_is_401_in_the_error_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/session", json={"access_code": "not-the-code"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert COOKIE_NAME not in client.cookies


def test_five_failures_then_429_even_for_the_right_code(
    client: TestClient, valid_env: dict[str, str]
) -> None:
    for _ in range(5):
        assert client.post("/api/v1/session", json={"access_code": "wrong"}).status_code == 401

    response = client.post("/api/v1/session", json={"access_code": valid_env["ACCESS_CODE"]})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


def test_rate_limit_keys_on_cloudflare_client_ip_not_forwarded_for(
    client: TestClient, valid_env: dict[str, str]
) -> None:
    for n in range(5):  # forged X-Forwarded-For values do not spread the failures
        client.post(
            "/api/v1/session",
            json={"access_code": "wrong"},
            headers={"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": f"198.51.100.{n}"},
        )

    blocked = client.post(
        "/api/v1/session",
        json={"access_code": valid_env["ACCESS_CODE"]},
        headers={"cf-connecting-ip": "203.0.113.7"},
    )
    other_client = client.post(
        "/api/v1/session",
        json={"access_code": valid_env["ACCESS_CODE"]},
        headers={"cf-connecting-ip": "203.0.113.8"},
    )

    assert blocked.status_code == 429
    assert other_client.status_code == 204


def test_malformed_body_is_400_invalid_request(client: TestClient) -> None:
    response = client.post("/api/v1/session", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_delete_session_clears_cookie(client: TestClient, valid_env: dict[str, str]) -> None:
    client.post("/api/v1/session", json={"access_code": valid_env["ACCESS_CODE"]})

    response = client.delete("/api/v1/session")

    assert response.status_code == 204
    assert COOKIE_NAME not in client.cookies


def test_tampered_or_expired_tokens_are_rejected() -> None:
    token = issue_token("viewer", "secret", now=1_000)
    payload, _, signature = token.partition(".")

    assert read_token(token, "secret", now=1_001) is not None
    assert read_token(token, "other-secret", now=1_001) is None
    assert read_token(f"{payload}x.{signature}", "secret", now=1_001) is None
    assert read_token(token, "secret", now=1_000 + MAX_AGE_S) is None
    assert read_token("", "secret") is None


def test_failure_window_slides() -> None:
    now = [0.0]
    limiter = FailureLimiter(max_failures=2, window_s=10, clock=lambda: now[0])
    limiter.record_failure("ip")
    limiter.record_failure("ip")
    assert limiter.blocked("ip")

    now[0] = 11.0

    assert not limiter.blocked("ip")


# --- health ---------------------------------------------------------------------


def test_health_ok_needs_no_session_and_reports_each_component(client: TestClient) -> None:
    """AT-29 (partial): stores and reference data reachable; no secrets in the body."""
    response = client.get("/api/v1/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert set(body["components"]) == {"postgres", "qdrant", "neo4j", "reference_data"}
    assert body["components"]["reference_data"] == {"status": "ok", "slots": 16}
    assert body["checker_independence"] == "different_family"
    assert "latency_ms" in body["components"]["postgres"]


def test_health_degraded_503_when_a_store_is_down_without_leaking_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_probes, "DOWN", {"neo4j"})

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["neo4j"] == {"status": "down"}
    assert "secret-host" not in response.text


def test_health_reports_reference_data_not_loaded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_relational, "SLOT_IDS", ["S01"])

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["components"]["reference_data"] == {"status": "not_loaded", "slots": 1}


# --- web root -------------------------------------------------------------------


def test_root_serves_the_web_page(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "CARDIO4Cities" in response.text
