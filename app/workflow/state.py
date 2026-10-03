"""Graph state (LLD-2 §2). The state holds IDs: everything else lives in Postgres, so a
checkpoint stays small and a resumed run reads current data. One exception (BD-09):
claim drafts between `extract` and `match_quotes` live in the slot state, because a
claim row needs the span that matching produces.

Slot reports are keyed `<slot_id>@<round>`, so a re-plan round adds to the slot's history
instead of replacing it; coverage reads every round (BD-14)."""

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
    round: int = 0  # plans merge across rounds; only the current round's are sent


class SlotReport(BaseModel):
    slot_id: str
    round: int
    query_ids: list[str] = []
    source_ids: list[str] = []
    crawl_decision_ids: list[str] = []
    claim_ids: list[str] = []
    supported_claim_ids: list[str] = []
    error: str | None = None


def report_key(slot_id: str, round_no: int) -> str:
    return f"{slot_id}@{round_no}"


class RunState(TypedDict, total=False):
    run_id: str
    city: CityIdentity
    round: int
    all_slots: list[str]  # every slot of the run: each ends with a status (AT-32)
    slots_to_work: list[str]
    replans: Annotated[dict[str, int], merge_dicts]  # slot_id -> re-plans used
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
    # Search text, for ranking only (the other-place rule, BD-15); never evidence (R-58)
    title: str = ""
    snippet: str = ""


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
    reused: list[Candidate]  # fetched by another slot this run: read, not fetched (BD-14)
    allowed: list[Candidate]
    crawl_decision_ids: Annotated[list[str], operator.add]
    source_ids: list[str]
    drafts: list[Draft]
    claim_ids: Annotated[list[str], operator.add]
    matched_claim_ids: list[str]
    supported_claim_ids: list[str]
    error: str | None
    slot_reports: Annotated[dict[str, SlotReport], merge_dicts]  # the only output


class SlotOutput(TypedDict):
    slot_reports: Annotated[dict[str, SlotReport], merge_dicts]


# The only classes a checkpoint may hold besides plain values (BD-14): the checkpointer
# reads nothing else back.
CHECKPOINT_TYPES: list[type[Any]] = [
    CityIdentity,
    PlannedQuery,
    SlotPlan,
    SlotReport,
    Candidate,
    Draft,
]
