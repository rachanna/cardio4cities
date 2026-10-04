"""Relational repositories (LLD-4 §8, ID-04). Postgres is fixed (CON-04), so the
repositories are the port and SQL lives only in `app/adapters/postgres/`.

Each repository is added by the task that first needs it (BD-03).
"""

from collections.abc import Callable
from datetime import date
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
    SourceProvider,
    Statistic,
    Verdict,
)


class ReferenceRepo(Protocol):
    async def slot_ids(self) -> list[str]: ...

    async def place_count(self) -> int:
        """Places in the gazetteer (BD-34): start-up refuses an empty one."""
        ...

    async def indicator_codes(self) -> dict[str, str]:
        """Registry indicator codes keyed 'provider.INDICATOR' (LLD-1 §3.4)."""
        ...

    async def slots(self) -> list[SlotDef]: ...

    async def indicators(self) -> list[IndicatorDef]: ...

    async def search_places(self, query: str, limit: int = 5) -> list[dict[str, Any]]: ...

    async def place_identity(self, gazetteer_id: str) -> dict[str, Any] | None: ...

    async def sources(self) -> list[SourceProvider]:
        """The Wave 0 registry (LLD-1 §3.4)."""
        ...

    async def country_places(self, country_iso2: str, min_population: int) -> list[dict[str, Any]]:
        """gazetteer_id, name, ascii_name, alternate_names of the country's places (BD-15)."""
        ...

    async def places_named(self, names: list[str], country_iso2: str) -> list[dict[str, Any]]:
        """Places in the country whose name keys (`ref_place.name_keys`, made by
        `place_key` from the name, ASCII name and alternate names) include one of `names`:
        gazetteer_id, name, lat, lon, admin1_code, name_keys (BD-10, BD-17)."""
        ...


class SourceRepo(Protocol):
    """Crawl decisions and fetched sources of a run (LLD-1 §4.3)."""

    async def add_crawl_decision(self, decision: CrawlDecision) -> None: ...

    async def add_source(
        self, source: Source, parsed_text: str | None, crawl_decision_id: str | None
    ) -> None:
        """Inserts nothing when the run already holds the source ID or its canonical URL."""
        ...

    async def source_at(self, run_id: str, url_canonical: str) -> tuple[str, bool] | None:
        """The run's source stored at this final URL, and whether it has parsed text
        (BD-21: two candidates that redirect to one page share one source)."""
        ...

    async def fetched_urls(self, run_id: str) -> set[str]:
        """Canonical URLs already fetched in the run (HD-01)."""
        ...

    async def fetched_sources(self, run_id: str) -> dict[str, str | None]:
        """URL (as found and as fetched) -> source ID of the run's stored pages, None
        when unreadable (BD-14, BD-21)."""
        ...

    async def crawl_outcomes(self, decision_ids: list[str]) -> list[str]: ...

    async def outcome_counts(self, run_id: str) -> dict[str, dict[str, int]]:
        """`crawl`: decisions by outcome (per URL); `parse`: pages by parse outcome."""
        ...

    async def source_for_extraction(self, source_id: str) -> dict[str, object] | None: ...

    async def set_parsed_text(self, source_id: str, parsed_text: str) -> None:
        """Wave 0: the canonical line of the record used (LLD-2 §13)."""
        ...


class RunRepo(Protocol):
    """Cities, runs and the event log (LLD-1 §4.2, LLD-2 §10)."""

    async def city_for_place(self, gazetteer_id: str) -> str | None: ...

    async def create_city(self, identity: CityIdentity) -> None: ...

    async def city_identity(self, city_id: str) -> CityIdentity: ...

    async def create_run(
        self,
        run_id: str,
        city_id: str,
        budget: dict[str, Any],
        versions: dict[str, str],
        owner: str | None = None,
    ) -> None:
        """`owner`: the process that runs it; its heartbeat starts now (BD-25)."""
        ...

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

    # --- coverage and resume (D2-5, BD-14) ---------------------------------------------

    async def save_slot_result(self, run_id: str, result: dict[str, Any]) -> None: ...

    async def slot_results(self, run_id: str) -> list[dict[str, Any]]: ...

    async def save_budget_used(self, run_id: str, used: dict[str, Any]) -> None: ...

    async def stranded_runs(self) -> list[dict[str, Any]]:
        """Runs `queued` or `running`, with `owner` and `quiet_s` (seconds since the last
        heartbeat; None when none was ever recorded)."""
        ...

    async def heartbeat(self, owner: str) -> None: ...

    async def claim_stale(self, run_id: str, owner: str, stale_after_s: float) -> bool:
        """Take over a run whose heartbeat is older than `stale_after_s`, counting one
        resume; False when its owner is still alive or another process took it."""
        ...


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

    async def stored_verdict(self, claim_id: str) -> dict[str, Any] | None:
        """label, verifier_model, fallback_used of the claim's verdict, if one is stored."""
        ...

    async def claim_statuses(self, run_id: str) -> dict[str, int]: ...

    async def evidence(self, claim_id: str) -> dict[str, Any] | None: ...

    async def claim_with_statistic(self, claim_id: str) -> tuple[Claim, Statistic | None]: ...

    async def add_contested_pair(
        self, pair_id: str, claim_a: str, claim_b: str, headline: str, reason: str
    ) -> None: ...

    # --- relations and graph links (D2-4, LLD-1 §6.3) ---------------------------------

    async def relation(self, claim_id: str) -> Relation | None: ...

    async def statistic_claims(self, run_id: str, statuses: list[str]) -> list[str]:
        """Statistic claims of the run with one of `statuses` (all slots, Wave 0)."""
        ...

    async def record_consistency(
        self, claim_id: str, outcome: str, compared_with: list[str], reason: str
    ) -> None: ...

    async def set_superseded_on(self, claim_id: str, on: date) -> None: ...

    async def superseded_live_links(self, run_id: str) -> list[str]: ...

    async def contested_links(self, run_id: str) -> list[str]: ...

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

    # --- coverage (D2-5, LLD-2 §11) ----------------------------------------------------

    async def slot_claims(self, run_id: str, slot_id: str) -> list[tuple[Claim, str]]:
        """Every claim of the slot in the run, with its source's publisher class."""
        ...

    async def contested_claim_ids(self, run_id: str) -> set[str]: ...

    async def queries(self, query_ids: list[str]) -> list[tuple[str, str]]:
        """(text, language) of the given searches."""
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

    async def update_attributes(
        self, entity_id: str, change: Callable[[dict[str, Any]], dict[str, Any] | None]
    ) -> dict[str, Any] | None:
        """Merge what `change` returns into the attributes under a row lock (BD-19)."""
        ...

    async def merge_attributes(self, entity_id: str, attributes: dict[str, Any]) -> None:
        """Shallow-merge into `entity.attributes`, e.g. a programme's status (T-06)."""
        ...


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
