"""Graph state (LLD-2 §2). The state holds IDs: everything else lives in Postgres, so a
checkpoint stays small and a resumed run reads current data. One exception (BD-09):
claim drafts between `extract` and `match_quotes` live in the slot state, because a
claim row needs the span that matching produces."""

import operator
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel

from app.domain.models import CityIdentity


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class PlannedQuery(BaseModel):
    text: str
    lang: str
    purpose: str = ""


class SlotPlan(BaseModel):
    slot_id: str
    queries: list[PlannedQuery]
    fallback: bool = False


class SlotReport(BaseModel):
    slot_id: str
    round: int
    query_ids: list[str] = []
    source_ids: list[str] = []
    crawl_decision_ids: list[str] = []
    claim_ids: list[str] = []
    supported_claim_ids: list[str] = []
    error: str | None = None


class RunState(TypedDict, total=False):
    run_id: str
    city: CityIdentity
    round: int
    slots_to_work: list[str]
    wave0_claim_ids: list[str]
    plans: Annotated[dict[str, SlotPlan], merge_dicts]
    slot_reports: Annotated[dict[str, SlotReport], merge_dicts]
    finished: bool


class Candidate(BaseModel):
    url: str
    domain: str
    publisher_class: str
    rank: int
    query_id: str


class Draft(BaseModel):
    """An extracted claim before its quote is located (BD-09)."""

    claim_id: str
    source_id: str
    window_start: int
    window_end: int
    output: dict[str, Any]  # ClaimOut as JSON
    extractor_model: str
    prompt_version: str


class SlotState(TypedDict, total=False):
    run_id: str
    city: CityIdentity
    slot_id: str
    round: int
    plan: SlotPlan
    query_ids: list[str]
    candidates: list[Candidate]
    allowed: list[Candidate]
    crawl_decision_ids: Annotated[list[str], operator.add]
    source_ids: list[str]
    drafts: list[Draft]
    claim_ids: Annotated[list[str], operator.add]
    matched_claim_ids: list[str]
    supported_claim_ids: list[str]
    ended: dict[str, str]  # claim ID -> ISO date its edge ends (consistency -> write)
    error: str | None
    slot_reports: Annotated[dict[str, SlotReport], merge_dicts]  # the only output


class SlotOutput(TypedDict):
    slot_reports: Annotated[dict[str, SlotReport], merge_dicts]
