"""Request and response models (LLD-4 §2-3); the single source for the OpenAPI document."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.cards import CareItem, FactCard, SlotRow


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


# --- Reading a city (LLD-4 §3.3, D3-1) ---------------------------------------------------
# FactCard, SlotRow and CareItem are built in app/domain/cards.py, shared with answers and
# the report.


class CityItem(BaseModel):
    city_id: str
    name: str
    country_name: str
    latest_run_id: str
    latest_run_at: datetime | None
    latest_run_status: str


class CitiesResponse(BaseModel):
    items: list[CityItem]
    next_cursor: str | None


class BriefRun(BaseModel):
    run_id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None  # the date the brief is "as of" (AT-25)


class BriefResponse(BaseModel):
    city: dict[str, Any]  # CityIdentity
    run: BriefRun
    summary: dict[str, list[FactCard]]  # by dimension, D1-D6 (HD-08)
    coverage: list[SlotRow]
    handle_with_care: list[CareItem]
    counts: dict[str, Any]  # the run summary (LLD-1 §2.7)


class ContestedPair(BaseModel):
    headline_claim_id: str
    other_claim_id: str


class FindingsResponse(BaseModel):
    items: list[FactCard]
    contested: list[ContestedPair]
    slots: list[SlotRow]  # the matching slots, with their gap notes (AT-13)
    next_cursor: str | None


class EntityItem(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    facts: int  # facts of the latest run that name it


class EntitiesResponse(BaseModel):
    by_type: dict[str, list[EntityItem]]


class OtherEntity(BaseModel):
    entity_id: str | None
    entity_type: str
    name: str


class EntityEdgeOut(BaseModel):
    relation: str
    direction: Literal["outgoing", "incoming"]
    other_entity: OtherEntity
    valid_from: date | None
    valid_to: date | None
    status: Literal["current", "ended", "contested"]
    claim_ids: list[str]  # re-checked in Postgres: confirmed claims of the latest run


class EntityResponse(BaseModel):
    entity: EntityItem
    attributes: dict[str, Any]
    edges: list[EntityEdgeOut]
    graph_used: bool  # read from the knowledge graph (non-negotiable 5)


class Passage(BaseModel):
    text: str  # the located quote with up to 600 characters of context
    highlight_start: int  # offsets of the quote inside `text`
    highlight_end: int


class VerdictOut(BaseModel):
    label: str
    rationale: str
    model: str
    fallback_used: bool
    checker_prompt: str


class SnapshotOut(BaseModel):
    sha256: str
    size_bytes: int
    content_type: str
    url: str


class ConsistencyOut(BaseModel):
    outcome: str
    compared_with: list[str]
    reason: str


class EvidenceResponse(BaseModel):
    card: FactCard
    quote: str
    quote_lang: str
    quote_translation: str | None
    passage: Passage | None
    label_passages: dict[str, str]  # where a period, population or area is stated (BD-10)
    geography_fit: dict[str, Any] | None
    verdict: VerdictOut | None
    snapshot: SnapshotOut | None
    consistency: ConsistencyOut | None
