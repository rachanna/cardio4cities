"""GET /api/v1/health (LLD-4 §7, R-77, AT-29). No auth; no hostnames, URLs or errors.

D1-4 covers the stores and reference data; provider checks (cached, at most every
10 minutes) are added with their adapters.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.schemas import ComponentHealth, HealthResponse
from app.ports.health import HealthProbe
from app.ports.repos import RelationalPort
from app.settings import check_reference_slots

router = APIRouter(tags=["operations"])
CHECK_TIMEOUT_S = 3.0  # each store gets one trivial round trip


@dataclass
class HealthService:
    relational: RelationalPort | None
    probes: list[HealthProbe]
    same_family_checker: bool
    app_version: str

    async def report(self) -> HealthResponse:
        checks: dict[str, Callable[[], Awaitable[ComponentHealth]]] = {
            "postgres": self._postgres,
            "reference_data": self._reference_data,
        }
        for probe in self.probes:
            checks[probe.component] = _timed(probe.check)
        for name in ("qdrant", "neo4j"):
            checks.setdefault(name, _not_configured)
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
            versions={"app": self.app_version},
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


def _timed(check: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[ComponentHealth]]:
    async def run() -> ComponentHealth:
        started = time.perf_counter()
        try:
            await asyncio.wait_for(check(), CHECK_TIMEOUT_S)
        except Exception:
            return ComponentHealth(status="down")
        return ComponentHealth(
            status="ok", latency_ms=round((time.perf_counter() - started) * 1000)
        )

    return run


async def _not_configured() -> ComponentHealth:
    return ComponentHealth(status="not_configured")


@router.get("/health", response_model=HealthResponse, response_model_exclude_none=True)
async def health(request: Request) -> JSONResponse:
    service: HealthService = request.app.state.health
    report = await service.report()
    return JSONResponse(
        report.model_dump(exclude_none=True), status_code=200 if report.status == "ok" else 503
    )
