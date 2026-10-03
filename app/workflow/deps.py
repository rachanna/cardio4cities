"""What the graph nodes need, built once per run by the runner and passed through the
LangGraph config. Ports and parameters only: nodes never import adapters."""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.domain.models import IndicatorDef, SlotDef
from app.domain.params import (
    BadgeParams,
    ConsistencyParams,
    QuoteParams,
    VerifyParams,
)
from app.ports.embeddings import EmbeddingsPort
from app.ports.llm import Effort, LLMPort
from app.ports.repos import RelationalPort
from app.ports.search import SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.vector import VectorPort
from app.workflow.budget import BudgetLedger
from app.workflow.collection import Collector
from app.workflow.events import EventEmitter
from app.workflow.rules.chunking import ChunkParams
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
    chunk: ChunkParams
    window: WindowParams
    max_new_urls: int  # select.max_new_urls_per_slot_round [tunable]
    today: Callable[[], object] = field(default=lambda: None)

    @property
    def collection(self) -> str:
        return f"source_chunks__{self.embeddings.key}"
