"""What the graph nodes need, built once per run by the runner and passed through the
LangGraph config. Ports and parameters only: nodes never import adapters."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.domain.models import IndicatorDef, SlotDef
from app.domain.params import (
    BadgeParams,
    ConsistencyParams,
    GeographyParams,
    QuoteParams,
    ReplanParams,
    VerifyParams,
)
from app.ports.embeddings import EmbeddingsPort
from app.ports.graph import GraphPort
from app.ports.llm import Effort, LLMPort
from app.ports.repos import RelationalPort
from app.ports.search import SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.structured import StructuredDataPort
from app.ports.vector import VectorPort
from app.workflow.budget import BudgetLedger
from app.workflow.collection import Collector
from app.workflow.entities import EntityResolver
from app.workflow.events import EventEmitter
from app.workflow.fetch_cache import FetchCache
from app.workflow.limits import StageClock
from app.workflow.rules.chunking import ChunkParams
from app.workflow.rules.other_places import PlaceMatcher
from app.workflow.rules.selection import PublisherTable
from app.workflow.rules.thresholds import ThresholdRule


@dataclass(frozen=True)
class Binding:
    """One model binding from config (BD-05)."""

    provider: str
    model: str
    family: str
    effort: Effort | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class RoleBinding:
    primary: Binding
    escalate_to: Binding | None = None
    fallback: Binding | None = None


@dataclass(frozen=True)
class WindowParams:
    window_tokens: int  # extract.window_tokens [tunable]
    overlap_tokens: int  # extract.overlap_tokens [tunable]
    max_windows_per_source: int  # extract.max_windows_per_source [tunable] (BD-29)
    stop_windows_below_s: float  # extract.stop_windows_below_s [tunable] (BD-29)
    max_sources_without_city: int = 1  # extract.max_sources_without_city [tunable] (BD-50)


@dataclass
class RunDeps:
    run_id: str
    relational: RelationalPort
    llm: dict[str, LLMPort]  # by provider
    roles: dict[str, RoleBinding]
    search: SearchPort
    search_provider: str
    collector: Collector
    embeddings: EmbeddingsPort
    vector: VectorPort
    graph: GraphPort
    structured: dict[str, StructuredDataPort]  # by registry provider (Wave 0)
    entities: EntityResolver
    snapshots: SnapshotPort
    ledger: BudgetLedger
    events: EventEmitter
    slots: dict[str, SlotDef]
    indicators: dict[str, IndicatorDef]
    publishers: PublisherTable
    thresholds: tuple[ThresholdRule, ...]
    quote: QuoteParams
    verify: VerifyParams
    consistency: ConsistencyParams
    badge: BadgeParams
    geography: GeographyParams
    chunk: ChunkParams
    window: WindowParams
    max_new_urls: int  # select.max_new_urls_per_slot_round [tunable]
    max_reused_urls: int  # select.max_reused_per_slot_round [tunable] (BD-14)
    replan: ReplanParams
    queries_per_slot: int  # plan.queries_per_slot [tunable] (BD-15)
    other_place_min_population: int  # select.other_place_min_population [tunable] (BD-15)
    today: Callable[[], date] = date.today
    fetch_cache: FetchCache = field(default_factory=FetchCache)  # one fetch per URL per run
    stages: StageClock = field(default_factory=StageClock)  # busy time per stage (AT-38)
    places: PlaceMatcher | None = None  # the other-place rule, built once per run (BD-15)
    checkpointed: bool = True  # False when no checkpoint can be saved: no resume (BD-25)
    prefer_local: bool = True  # select.prefer_local [tunable] (BD-50)
    max_per_domain: int = 2  # select.max_per_domain_per_round [tunable] (BD-51)
    # (slot, source) pairs this process extracted: a later round never repeats one (BD-29)
    extracted: set[tuple[str, str]] = field(default_factory=set)

    @property
    def collection(self) -> str:
        return chunk_collection(self.embeddings.key)

    @property
    def claim_collection(self) -> str:
        """Confirmed claims for the semantic route (CHG-01, LLD-5 §4.2)."""
        return claim_collection(self.embeddings.key)


def chunk_collection(embedding_key: str) -> str:
    return f"source_chunks__{embedding_key}"


def claim_collection(embedding_key: str) -> str:
    return f"claim_index__{embedding_key}"
