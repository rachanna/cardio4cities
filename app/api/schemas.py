"""Request and response models (LLD-4 §2-3); the single source for the OpenAPI document."""

from typing import Literal

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
