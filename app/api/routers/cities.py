"""Reading a researched city (LLD-4 §3.2-3.3, D3-1): "Open existing", the brief, findings
and entities. Only facts in `v_city_facts` become FactCards; both sides of a disagreement
are always returned together; entity edges come from the knowledge graph and are checked
again in Postgres before they are shown."""

import logging
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.api import reading
from app.api.auth import Session, current_session
from app.api.errors import ApiError, dependency_unavailable
from app.api.schemas import (
    BriefResponse,
    BriefRun,
    CitiesResponse,
    CityItem,
    ContestedPair,
    EntitiesResponse,
    EntityEdgeOut,
    EntityItem,
    EntityResponse,
    FindingsResponse,
    OtherEntity,
    SlotInfo,
)
from app.domain.cards import FactCard, handle_with_care, slot_row, summary
from app.domain.vocab import Badge, ClaimStatus, VerdictLabel
from app.ports.graph import GraphEdgeHit, GraphPort

log = logging.getLogger(__name__)
router = APIRouter(tags=["cities"])
SessionDep = Annotated[Session, Depends(current_session)]
# Claims whose edges the entity page shows: facts, and facts a newer claim ended (BD-19)
EDGE_STATUSES = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED, ClaimStatus.SUPERSEDED})


@router.get("/slots", response_model=list[SlotInfo])
async def slots(request: Request, _: SessionDep) -> list[SlotInfo]:
    """The 16 questions every run answers, for the live coverage grid (D3-4, BD-41)."""
    defs = await reading.relational(request).reference.slots()
    return [
        SlotInfo(
            slot_id=s.slot_id, dimension=s.dimension, question=s.question,
            short_label=s.short_label, headline=s.headline,
        )
        for s in sorted(defs, key=lambda s: s.slot_id)
    ]  # fmt: skip


@router.get("/cities", response_model=CitiesResponse)
async def list_cities(
    request: Request,
    _: SessionDep,
    limit: Annotated[int | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> CitiesResponse:
    """ "Open existing": every city with a finished run, the newest first (AT-25, AT-37)."""
    size, offset = reading.page(limit, cursor)
    rows = await reading.relational(request).runs.cities(size, offset)
    return CitiesResponse(
        items=[CityItem.model_validate(r) for r in rows],
        next_cursor=reading.next_cursor(offset, size, len(rows)),
    )


async def _cards(
    request: Request, city_id: str
) -> tuple[dict[str, Any], reading.CardMaker, list[Any], dict[str, FactCard]]:
    row = await reading.city(request, city_id)
    maker = await reading.card_maker(request)
    facts = await reading.relational(request).research.city_facts(city_id)
    return row, maker, facts, {f.claim.claim_id: maker.card(f) for f in facts}


async def _slot_rows(request: Request, run_id: str, maker: reading.CardMaker) -> list[Any]:
    results = await reading.relational(request).runs.slot_results(run_id)
    return [slot_row(r, maker.slots[r["slot_id"]]) for r in results if r["slot_id"] in maker.slots]


@router.get("/cities/{city_id}/brief", response_model=BriefResponse)
async def brief(city_id: str, request: Request, _: SessionDep) -> BriefResponse:
    """The city's latest run as a brief (LLD-4 §3.3): stored knowledge, no new research
    (AT-25), with the date it is as of."""
    row, maker, facts, cards = await _cards(request, city_id)
    run_id = row["latest_run_id"]
    store = reading.relational(request)
    rows = await _slot_rows(request, run_id, maker)
    pairs = await store.research.contested_pairs(run_id)
    shown = reading.visible(cards, pairs)  # D4-3
    facts = [f for f in facts if f.claim.claim_id in shown]
    cards = {i: c for i, c in cards.items() if i in shown}
    summarised = summary(rows, cards, reading.summary_topics())
    run = await store.runs.run_row(run_id)
    return BriefResponse(
        city=row["identity"],
        run=BriefRun(
            run_id=run_id,
            status=row["latest_run_status"],
            started_at=row["latest_run_started"],
            finished_at=row["latest_run_at"],
        ),
        summary=summarised,
        coverage=rows,
        handle_with_care=handle_with_care(
            [c for group in summarised.values() for c in group], facts, cards, pairs
        ),
        counts=(run or {}).get("summary") or {},
    )


@router.get("/cities/{city_id}/findings", response_model=FindingsResponse)
async def findings(
    city_id: str,
    request: Request,
    _: SessionDep,
    dimension: Annotated[str | None, Query(pattern=r"^D[1-6]$")] = None,
    slot: Annotated[str | None, Query(pattern=r"^S(0[1-9]|1[0-6])$")] = None,
    status: Annotated[ClaimStatus | None, Query()] = None,
    badge: Annotated[Badge | None, Query()] = None,
    limit: Annotated[int | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> FindingsResponse:
    """FactCards of the latest run, filtered. When a filter keeps one side of a
    disagreement, the other side comes with it."""
    size, offset = reading.page(limit, cursor)
    row, maker, _facts, cards = await _cards(request, city_id)

    def wanted_slot(slot_id: str) -> bool:
        s = maker.slots[slot_id]
        return (dimension is None or s.dimension == dimension) and (slot is None or slot_id == slot)

    def wanted(card: FactCard) -> bool:
        badges = {card.main_badge.code} if card.main_badge else set()
        badges |= {b.code for b in card.other_badges}
        return (
            wanted_slot(card.slot_id)
            and (status is None or card.status == status.value)
            and (badge is None or badge.value in badges)
        )

    pairs = await reading.relational(request).research.contested_pairs(row["latest_run_id"])
    shown = reading.visible(cards, pairs)  # D4-3
    kept = {i for i, c in cards.items() if wanted(c) and i in shown}
    shown_pairs = [(a, b) for a, b in pairs if a in kept or b in kept]
    for a, b in shown_pairs:  # both sides of a disagreement, always together
        kept |= {a, b} & cards.keys()
    ordered = [cards[i] for i in sorted(kept, key=lambda i: (cards[i].slot_id, i))]
    rows = await _slot_rows(request, row["latest_run_id"], maker)
    window = ordered[offset : offset + size]
    return FindingsResponse(
        items=window,
        contested=[ContestedPair(headline_claim_id=a, other_claim_id=b) for a, b in shown_pairs],
        slots=[r for r in rows if wanted_slot(r.slot_id)],
        next_cursor=reading.next_cursor(offset, size, len(window), len(ordered)),
    )


@router.get("/cities/{city_id}/entities", response_model=EntitiesResponse)
async def entities(city_id: str, request: Request, _: SessionDep) -> EntitiesResponse:
    """Entities named by the latest run's facts, by type, with how many facts name them."""
    await reading.city(request, city_id)
    counted = await reading.relational(request).entities.with_fact_counts(city_id)
    by_type: dict[str, list[EntityItem]] = defaultdict(list)
    for entity, facts in counted:
        by_type[entity.entity_type.value].append(
            EntityItem(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type.value,
                name=entity.canonical_name,
                facts=facts,
            )
        )
    return EntitiesResponse(by_type=dict(by_type))


def _graph(request: Request) -> GraphPort:
    graph: GraphPort | None = request.app.state.container.graph
    if graph is None:
        raise dependency_unavailable("neo4j", "The knowledge graph is not available.")
    return graph


@router.get("/cities/{city_id}/entities/{entity_id}", response_model=EntityResponse)
async def entity(city_id: str, entity_id: str, request: Request, _: SessionDep) -> EntityResponse:
    """The entity and its one-hop edges from the knowledge graph (non-negotiable 5). Each
    edge's claims are checked again in Postgres: only confirmed claims of the latest run,
    or ones a newer claim ended, keep an edge (LLD-5 re-validation)."""
    row = await reading.city(request, city_id)
    store = reading.relational(request)
    found = (await store.entities.get([entity_id])).get(entity_id)
    if found is None or found.city_id != city_id:
        raise ApiError(404, "not_found", "That entity is not part of this city's research.")
    try:
        hits = await _graph(request).neighbours(city_id, found.graph_uuid)
    except ApiError:
        raise
    except Exception as exc:  # the graph is down: the page says so; other pages still work
        log.warning("entity page: graph read failed (%s)", type(exc).__name__)
        raise dependency_unavailable("neo4j", "The knowledge graph is not available.") from exc
    claim_ids = sorted({c for h in hits for c in h.edge.attributes.get("claim_ids", [])})
    stored = await store.research.stored_facts(claim_ids)
    confirmed = {
        i: f
        for i, f in stored.items()
        if f.claim.run_id == row["latest_run_id"]
        and f.claim.status in EDGE_STATUSES
        and f.verdict is not None
        and f.verdict.label is VerdictLabel.SUPPORTED
    }
    edges = [e for e in (_edge(h, found.graph_uuid, confirmed) for h in hits) if e is not None]
    counted = {e.entity_id: n for e, n in await store.entities.with_fact_counts(city_id)}
    return EntityResponse(
        entity=EntityItem(
            entity_id=found.entity_id,
            entity_type=found.entity_type.value,
            name=found.canonical_name,
            facts=counted.get(found.entity_id, 0),
        ),
        attributes=dict(found.attributes),
        edges=sorted(
            edges, key=lambda e: (e.relation, e.other_entity.name, str(e.valid_from or ""))
        ),
        graph_used=True,
    )


def _edge(hit: GraphEdgeHit, own_uuid: str, confirmed: dict[str, Any]) -> EntityEdgeOut | None:
    ids = [c for c in hit.edge.attributes.get("claim_ids", []) if c in confirmed]
    if not ids:
        return None  # no confirmed claim behind it in Postgres: never shown
    outgoing = hit.subject.uuid == own_uuid
    other = hit.object if outgoing else hit.subject
    statuses = {confirmed[i].claim.status for i in ids}
    if ClaimStatus.CONTESTED in statuses or hit.edge.attributes.get("status") == "contested":
        status = "contested"
    elif hit.edge.invalid_at is not None or statuses == {ClaimStatus.SUPERSEDED}:
        status = "ended"
    else:
        status = "current"
    return EntityEdgeOut(
        relation=hit.edge.name,
        direction="outgoing" if outgoing else "incoming",
        other_entity=OtherEntity(
            entity_id=other.attributes.get("entity_id"),
            entity_type=other.entity_type,
            name=other.name,
        ),
        valid_from=hit.edge.valid_at,
        valid_to=hit.edge.invalid_at,
        status=status,
        claim_ids=ids,
    )
