"""Request and response models (LLD-4 §2-3); the single source for the OpenAPI document."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    access_code: str = Field(min_length=1, max_length=200)


ComponentStatus = Literal["ok", "down", "not_loaded", "not_configured"]


class ComponentHealth(BaseModel):
    status: ComponentStatus
    latency_ms: int | None = None
    slots: int | None = None  # reference_data only


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checked_at: str
    components: dict[str, ComponentHealth]
    checker_independence: Literal["different_family", "same_family_allowed"]
    versions: dict[str, str]
    # "off": no checkpoints in this process (Windows' Proactor loop), so a run cannot
    # resume after a restart (BD-14, BD-25). Shown, not counted against the status.
    resume: Literal["on", "off"] | None = None


# --- Cities and runs (LLD-4 §3.2) ---------------------------------------------------


class ResolveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class PlaceCandidate(BaseModel):
    gazetteer_id: str
    name: str
    admin1_name: str | None
    country_name: str
    country_iso2: str
    population: int | None
    lat: float | None = None  # tells apart places of one name in one region (BD-34)
    lon: float | None = None


class ResolveResponse(BaseModel):
    exact: bool
    candidates: list[PlaceCandidate]


class StartRunRequest(BaseModel):
    gazetteer_id: str = Field(min_length=1, max_length=20)


class StartRunResponse(BaseModel):
    run_id: str
    city_id: str
    status: str
    events_url: str


class RunResponse(BaseModel):
    run_id: str
    city_id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict[str, Any] | None
    versions: dict[str, str]
