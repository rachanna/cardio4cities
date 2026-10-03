"""Relational repositories (LLD-4 §8, ID-04). Postgres is fixed (CON-04), so the
repositories are the port and SQL lives only in `app/adapters/postgres/`.

Each repository is added by the task that first needs it (BD-03).
"""

from typing import Any, Protocol

from app.domain.models import (
    CityIdentity,
    Claim,
    CrawlDecision,
    Entity,
    IndicatorDef,
    Relation,
    SlotDef,
    Source,
    Statistic,
    Verdict,
)


class ReferenceRepo(Protocol):
    async def slot_ids(self) -> list[str]: ...

    async def indicator_codes(self) -> dict[str, str]:
        """Registry indicator codes keyed 'provider.INDICATOR' (LLD-1 §3.4)."""
        ...

    async def slots(self) -> list[SlotDef]: ...

    async def indicators(self) -> list[IndicatorDef]: ...

    async def search_places(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...

    async def place_identity(self, gazetteer_id: str) -> dict[str, Any] | None: ...

    async def places_named(self, names: list[str], country_iso2: str) -> list[dict[str, Any]]:
        """Places in the country whose name, ASCII name or an alternate name equals one of
        `names` (lower case): gazetteer_id, name, lat, lon (BD-10)."""
        ...


class SourceRepo(Protocol):
    """Crawl decisions and fetched sources of a run (LLD-1 §4.3)."""

    async def add_crawl_decision(self, decision: CrawlDecision) -> None: ...

    async def add_source(
        self, source: Source, parsed_text: str | None, crawl_decision_id: str | None
    ) -> None: ...

    async def fetched_urls(self, run_id: str) -> set[str]:
        """Canonical URLs already fetched in the run: the fetch cache (HD-01)."""
        ...

    async def source_for_extraction(self, source_id: str) -> dict[str, object] | None: ...


class RunRepo(Protocol):
    """Cities, runs and the event log (LLD-1 §4.2, LLD-2 §10)."""

    async def city_for_place(self, gazetteer_id: str) -> str | None: ...

    async def create_city(self, identity: CityIdentity) -> None: ...

    async def city_identity(self, city_id: str) -> CityIdentity: ...

    async def create_run(
        self, run_id: str, city_id: str, budget: dict[str, Any], versions: dict[str, str]
    ) -> None: ...

    async def active_run(self) -> str | None: ...

    async def runs_today(self) -> int: ...

    async def set_status(self, run_id: str, status: str, error: str | None = None) -> None: ...

    async def run_row(self, run_id: str) -> dict[str, Any] | None: ...

    async def save_summary(self, run_id: str, summary: dict[str, Any]) -> None: ...

    async def append_event(
        self, run_id: str, event_id: str, type_: str, payload: dict[str, Any]
    ) -> int: ...

    async def events_after(
        self, run_id: str, after_seq: int, limit: int = 500
    ) -> list[dict[str, Any]]: ...


class ResearchRepo(Protocol):
    """Searches, claims, statistics and verdicts (LLD-1 §4.3-4.4)."""

    async def add_search(
        self,
        query_id: str,
        run_id: str,
        slot_id: str,
        query: str,
        lang: str,
        provider: str,
        result_count: int,
        round_no: int,
    ) -> None: ...

    async def add_claim(
        self, claim: Claim, statistic: Statistic | None, relation: Relation | None = None
    ) -> None: ...

    async def set_claim_status(self, claim_id: str, status: str) -> None: ...

    async def set_comparability_key(self, claim_id: str, key: str | None) -> None: ...

    async def add_verdict(self, verdict: Verdict) -> None: ...

    async def claim_statuses(self, run_id: str) -> dict[str, int]: ...

    async def evidence(self, claim_id: str) -> dict[str, Any] | None: ...

    async def claim_with_statistic(self, claim_id: str) -> tuple[Claim, Statistic | None]: ...

    async def add_contested_pair(
        self, pair_id: str, claim_a: str, claim_b: str, headline: str, reason: str
    ) -> None: ...

    # --- relations and graph links (D2-4, LLD-1 §6.3) ---------------------------------

    async def relation(self, claim_id: str) -> Relation | None: ...

    async def relation_claims(self, run_id: str, statuses: list[str]) -> list[str]:
        """Relation claims of the run with one of `statuses`."""
        ...

    async def add_graph_link(self, claim_id: str, edge_uuid: str) -> None: ...

    async def graph_link(self, claim_id: str) -> str | None: ...

    async def invalidate_graph_link(self, claim_id: str) -> None: ...

    async def claims_without_graph_link(self, run_id: str) -> list[str]:
        """Supported, contested or superseded claims that should have an edge but have none."""
        ...

    # --- retrieval indexes (CHG-01, LLD-5 §4.1-4.2) -------------------------------------

    async def refresh_search_tsv(self, claim_id: str) -> None: ...

    async def claim_index_row(self, claim_id: str) -> dict[str, Any] | None:
        """Fields for the claim-index point: text parts and the LLD-5 §4.2 payload."""
        ...


class EntityRepo(Protocol):
    """Entities and aliases per city (LLD-1 §4.4, LLD-2 §6)."""

    async def alias(self, city_id: str, surface_form: str) -> str | None: ...

    async def by_key(self, city_id: str, entity_type: str, normalized_key: str) -> str | None: ...

    async def add_entity(self, entity: Entity) -> str:
        """Insert unless `(city, type, key)` exists; returns the stored entity's ID."""
        ...

    async def add_alias(
        self, city_id: str, surface_form: str, entity_id: str, method: str, score: float | None
    ) -> None: ...

    async def entities(self, city_id: str, entity_type: str) -> list[Entity]: ...

    async def get(self, entity_ids: list[str]) -> dict[str, Entity]: ...


class RelationalPort(Protocol):
    @property
    def reference(self) -> ReferenceRepo: ...

    @property
    def sources(self) -> SourceRepo: ...

    @property
    def runs(self) -> RunRepo: ...

    @property
    def research(self) -> ResearchRepo: ...

    @property
    def entities(self) -> EntityRepo: ...

    async def ping(self) -> None:
        """`SELECT 1`; raises when the database is unreachable (LLD-4 §7)."""
        ...

    async def close(self) -> None: ...
