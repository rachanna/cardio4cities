"""GET /api/v1/health (LLD-4 §7, R-77, AT-29). No auth; no hostnames, URLs or errors.

Stores are checked on every call. Providers (models, embeddings, search) are checked at
most once per `health.provider_ttl_s`, so neither the keep-alive job nor anyone calling
this public endpoint can turn it into spend (BD-42).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.schemas import ComponentHealth, HealthResponse
from app.ports.health import HealthProbe
from app.ports.repos import RelationalPort
from app.prompts.loader import CURRENT, load_prompt
from app.settings import check_reference_slots

router = APIRouter(tags=["operations"])
CHECK_TIMEOUT_S = 3.0  # each store gets one trivial round trip


@dataclass
class HealthService:
    relational: RelationalPort | None
    probes: list[HealthProbe]
    same_family_checker: bool
    app_version: str
    checkpoints: bool | None = None  # False: runs cannot resume here (BD-25)
    providers: list[HealthProbe] = field(default_factory=list)
    provider_components: list[str] = field(default_factory=list)  # expected, probe or not
    provider_ttl_s: float = 600.0
    provider_timeout_s: float = 5.0
    clock: Callable[[], float] = time.monotonic
    _cached: dict[str, "CachedCheck"] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        for probe in self.providers:
            check = _timed(probe.check, self.provider_timeout_s)
            self._cached[probe.component] = CachedCheck(check, self.provider_ttl_s, self.clock)

    async def report(self) -> HealthResponse:
        checks: dict[str, Callable[[], Awaitable[ComponentHealth]]] = {
            "postgres": self._postgres,
            "reference_data": self._reference_data,
        }
        for probe in self.probes:
            checks[probe.component] = _timed(probe.check)
        for name in ("qdrant", "neo4j"):
            checks.setdefault(name, _not_configured)
        for name in self.provider_components:
            checks[name] = self._cached.get(name, _not_configured)
        results = await asyncio.gather(*(check() for check in checks.values()))
        components = dict(zip(checks, results, strict=True))
        healthy = all(c.status == "ok" for c in components.values())
        return HealthResponse(
            status="ok" if healthy else "degraded",
            checked_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            components=components,
            checker_independence=(
                "same_family_allowed" if self.same_family_checker else "different_family"
            ),
            versions={"app": self.app_version, "prompts": prompt_versions()},
            resume=None if self.checkpoints is None else ("on" if self.checkpoints else "off"),
        )

    async def _postgres(self) -> ComponentHealth:
        if self.relational is None:
            return ComponentHealth(status="not_configured")
        return await _timed(self.relational.ping)()

    async def _reference_data(self) -> ComponentHealth:
        if self.relational is None:
            return ComponentHealth(status="not_configured")
        reference = self.relational.reference
        try:
            slots = await asyncio.wait_for(reference.slot_ids(), CHECK_TIMEOUT_S)
        except Exception:
            return ComponentHealth(status="down")
        status = "ok" if not check_reference_slots(slots) else "not_loaded"
        return ComponentHealth(status=status, slots=len(slots))


def prompt_versions() -> dict[str, str]:
    """The prompt each role runs now (RV-038): `<role>@v<n>+<hash>`."""
    return {role: load_prompt(role).prompt_version for role in CURRENT}


class CachedCheck:
    """One provider's last result, reused until it is `ttl_s` old. Concurrent callers
    wait for the one check in flight instead of starting their own."""

    def __init__(
        self,
        check: Callable[[], Awaitable[ComponentHealth]],
        ttl_s: float,
        clock: Callable[[], float],
    ) -> None:
        self._check, self._ttl_s, self._clock = check, ttl_s, clock
        self._lock = asyncio.Lock()
        self._last: ComponentHealth | None = None
        self._at = 0.0

    async def __call__(self) -> ComponentHealth:
        async with self._lock:
            if self._last is None or self._clock() - self._at >= self._ttl_s:
                self._last = await self._check()
                self._at = self._clock()
            return self._last


def _timed(
    check: Callable[[], Awaitable[None]], timeout_s: float = CHECK_TIMEOUT_S
) -> Callable[[], Awaitable[ComponentHealth]]:
    async def run() -> ComponentHealth:
        started = time.perf_counter()
        try:
            await asyncio.wait_for(check(), timeout_s)
        except Exception:
            return ComponentHealth(status="down")
        return ComponentHealth(
            status="ok", latency_ms=round((time.perf_counter() - started) * 1000)
        )

    return run


async def _not_configured() -> ComponentHealth:
    return ComponentHealth(status="not_configured")


@router.get("/live")
async def live(request: Request) -> JSONResponse:
    """Liveness for the platform (BD-25): the process answers and Postgres, the only
    store without which nothing works, is reachable. A Neo4j or Qdrant restart degrades
    /health but must not make the platform restart the app and kill a run."""
    relational: RelationalPort | None = request.app.state.container.relational
    try:
        if relational is not None:
            await asyncio.wait_for(relational.ping(), CHECK_TIMEOUT_S)
    except Exception:
        return JSONResponse({"status": "down"}, status_code=503)
    return JSONResponse({"status": "ok"})


@router.get("/health", response_model=HealthResponse, response_model_exclude_none=True)
async def health(request: Request) -> JSONResponse:
    service: HealthService = request.app.state.health
    report = await service.report()
    return JSONResponse(
        report.model_dump(exclude_none=True), status_code=200 if report.status == "ok" else 503
    )
