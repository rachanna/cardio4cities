"""What question answering works with (LLD-5): its dependencies, the understood question,
route results and mentions. The composition (`app/api`) builds `AskDeps` per question,
with its own budget ledger (owner, BD-38)."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

from app.domain.models import CityIdentity, IndicatorDef, SlotDef
from app.domain.params import BadgeParams, ConfidenceParams
from app.ports.embeddings import EmbeddingsPort
from app.ports.graph import GraphPort
from app.ports.llm import LLMParams, LLMPort
from app.ports.repos import RelationalPort
from app.ports.vector import VectorPort
from app.prompts.classifier.schema import EntityMention, QuestionType

Route = Literal["R1", "R2", "R3", "R4"]
RouteStatus = Literal["ok", "skipped", "degraded", "unavailable"]


class AskLedger(Protocol):
    """The budget ledger as question answering uses it: every external call reserves
    first (CLAUDE.md), and a question has its own ledger (BD-38)."""

    async def reserve(self, kind: Any) -> None: ...

    async def record_model(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: int,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None: ...

    async def record_embedding(self, model: str, tokens: int, cost: int) -> None: ...

    def time_left_s(self) -> float: ...


@dataclass(frozen=True)
class ModelRole:
    provider: str
    family: str
    params: LLMParams


@dataclass(frozen=True)
class AskParams:
    """`retrieval.*` (LLD-5 §14)."""

    rrf_k: int
    r2_top: int
    r2_trigram_min: float
    r3_top: int
    r3_mentions_top: int
    max_facts: int
    max_mentions: int
    max_per_slot: int
    mentions_only_if_facts_below: int


@dataclass
class AskDeps:
    relational: RelationalPort
    vector: VectorPort | None
    graph: GraphPort | None
    embeddings: EmbeddingsPort | None
    embedding_model: str
    llm: dict[str, LLMPort]  # by provider
    roles: dict[str, ModelRole]  # classifier, answerer
    ledger: AskLedger
    params: AskParams
    badge: BadgeParams
    confidence: ConfidenceParams
    stopwords: frozenset[str]
    slots: dict[str, SlotDef]
    indicators: dict[str, IndicatorDef]
    city: CityIdentity
    city_id: str
    run_id: str  # the city's latest run
    claim_collection: str  # claim_index__{key}
    chunk_collection: str  # source_chunks__{key}
    today: date
    graph_on: bool = True  # admin switch (R-88)


@dataclass(frozen=True)
class Understanding:
    """The question as classified, validated and merged with the previous turn."""

    question_type: QuestionType
    slot_ids: tuple[str, ...]
    indicator_codes: tuple[str, ...]
    entity_mentions: tuple[EntityMention, ...]
    as_of: date | None
    sub_questions: tuple[str, ...]
    refers_to_previous: bool
    merged_from_previous: tuple[str, ...] = ()
    classified_by: str | None = None  # model ID

    def hint(self) -> dict[str, Any]:
        """What the next turn may see (LLD-5 §3.2): never this turn's answer text."""
        return {
            "question_type": self.question_type,
            "slot_ids": list(self.slot_ids),
            "indicator_codes": list(self.indicator_codes),
            "entity_mentions": [m.model_dump(mode="json") for m in self.entity_mentions],
        }


@dataclass(frozen=True)
class Mention:
    """A page passage that did not become a confirmed claim (LLD-5 §4.2): never a fact."""

    source_id: str
    char_start: int
    char_end: int
    text: str
    publisher_class: str

    @property
    def ref_id(self) -> str:
        return f"m:{self.source_id}:{self.char_start}"


@dataclass
class RouteResult:
    route: Route
    candidates: list[str] = field(default_factory=list)  # claim IDs, best first
    mentions: list[Mention] = field(default_factory=list)
    status: RouteStatus = "ok"
    ms: int = 0
    note: str | None = None  # why skipped, degraded or unavailable
