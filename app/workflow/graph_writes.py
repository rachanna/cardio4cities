"""Graph writes for supported facts (LLD-1 §6.3, BD-11).

One supported relation claim becomes one edge; a supported statistic for a catalogue
indicator becomes an `Indicator -MEASURED_IN-> Place` edge that carries no value (R-87).
Edge UUID = uuid5(claim_id); attributes carry claim and source IDs, status and the
proxy-date flag. Supersession is applied as `invalid_at`; nothing is deleted (R-44).
A graph failure leaves the claim supported in Postgres with no `graph_link`; the write
is retried once at `brief_ready` (LLD-2 §3.3). A supported claim that states a programme's
status also updates the Programme entity (T-06).
"""

import logging
from datetime import date

from app.domain.ids import graph_uuid
from app.domain.models import Claim, Entity, Statistic
from app.domain.vocab import ClaimKind, ClaimStatus, EntityType, PeriodType, RelationType
from app.ports.graph import GraphEdge, GraphEntity
from app.workflow.deps import RunDeps
from app.workflow.rules.programme_status import observed_on, programme_status_update

log = logging.getLogger(__name__)
# Statistics that name no indicator a slot asks about: no MEASURED_IN edge (BD-19)
NO_EDGE_INDICATORS = frozenset({"OTHER", "POP_TOTAL"})


def _node(entity: Entity) -> GraphEntity:
    return GraphEntity(
        uuid=entity.graph_uuid,
        group_id=entity.city_id,
        entity_type=entity.entity_type.value,
        name=entity.canonical_name,
        attributes={"entity_id": entity.entity_id, **entity.attributes},
    )


def _attributes(claim: Claim, proxy: bool) -> dict[str, object]:
    return {
        "claim_ids": [claim.claim_id],
        "source_ids": [claim.source_id],
        "status": claim.status.value,
        "proxy_date": proxy,
    }


async def triplet(
    d: RunDeps, claim: Claim, statistic: Statistic | None, ended_at: date | None
) -> tuple[GraphEntity, GraphEdge, GraphEntity] | None:
    """The edge for one claim, or None when the claim has no place in the graph."""
    research = d.relational.research
    if claim.kind is ClaimKind.RELATION:
        relation = await research.relation(claim.claim_id)
        if relation is None:
            return None
        ents = await d.relational.entities.get(
            [relation.subject_entity_id, relation.object_entity_id]
        )
        edge = GraphEdge(
            uuid=graph_uuid(claim.claim_id),
            group_id=claim.city_id,
            name=relation.relation_type.value,
            fact=claim.statement,
            valid_at=relation.valid_from,
            invalid_at=relation.valid_to or ended_at,
            attributes=_attributes(claim, relation.valid_from_is_proxy),
        )
        return _node(ents[relation.subject_entity_id]), edge, _node(ents[relation.object_entity_id])
    if (
        statistic is None
        or statistic.indicator_code not in d.indicators
        or statistic.indicator_code in NO_EDGE_INDICATORS
    ):
        return None
    indicator = d.indicators[statistic.indicator_code]
    indicator_id = await d.entities.ensure_indicator(claim.city_id, indicator.code, indicator.name)
    place_id = await d.entities.resolve(
        claim.city_id, claim.labels.geography_name, EntityType.PLACE
    )
    ents = await d.relational.entities.get([indicator_id, place_id])
    place = ents[place_id]
    edge = GraphEdge(
        uuid=graph_uuid(claim.claim_id),
        group_id=claim.city_id,
        name=RelationType.MEASURED_IN.value,
        fact=f"{indicator.name} was measured in {place.canonical_name}.",  # no value (R-87)
        valid_at=claim.labels.reference_end,
        invalid_at=ended_at,
        attributes=_attributes(
            claim, claim.labels.period_type is PeriodType.PUBLICATION_DATE_PROXY
        ),
    )
    return _node(ents[indicator_id]), edge, _node(place)


async def write_graph(d: RunDeps, claim_id: str) -> bool:
    """Write the claim's edge once; True when an edge exists afterwards. A superseded
    claim's edge is written ended on its stored `superseded_on`, and never without it:
    a superseded edge must not look current (BD-19)."""
    research = d.relational.research
    if await research.graph_link(claim_id):
        return True
    claim, statistic = await research.claim_with_statistic(claim_id)
    ended_at: date | None = None
    if claim.status is ClaimStatus.SUPERSEDED:
        relation = await research.relation(claim_id)
        ended_at = relation.superseded_on if relation else None
        if ended_at is None:
            return False
    try:
        built = await triplet(d, claim, statistic, ended_at)
        if built is None:
            return False
        subject, edge, obj = built
        # The edge fact and new node names are embedded. A confirmed claim's edge is never
        # refused by the budget (BD-19).
        await d.ledger.reserve("indexing")
        await d.graph.add_triplet(subject, edge, obj)
    except Exception as exc:  # graph down or refused: the claim stays supported in Postgres
        log.warning("graph write failed for %s (%s)", claim_id, type(exc).__name__)
        return False
    await research.add_graph_link(claim_id, edge.uuid)
    if ended_at is not None:
        await research.invalidate_graph_link(claim_id)
    return True


async def end_edge(d: RunDeps, claim_id: str, at: date) -> None:
    """Supersession of an edge already written: end-date it, keep it (R-44, R-60)."""
    edge_uuid = await d.relational.research.graph_link(claim_id)
    if edge_uuid is None:
        return  # not written yet: `write` writes it already ended
    try:
        await d.graph.invalidate_edge(edge_uuid, at)
        await d.graph.update_edge_attributes(edge_uuid, {"status": "superseded"})
    except Exception as exc:
        log.warning("graph supersession failed for %s (%s)", claim_id, type(exc).__name__)
        return
    await d.relational.research.invalidate_graph_link(claim_id)


async def mark_edge(d: RunDeps, claim_id: str, status: str) -> None:
    """A written edge whose claim became contested says so in its attributes."""
    edge_uuid = await d.relational.research.graph_link(claim_id)
    if edge_uuid is None:
        return
    try:
        await d.graph.update_edge_attributes(edge_uuid, {"status": status})
    except Exception as exc:
        log.warning("graph status update failed for %s (%s)", claim_id, type(exc).__name__)


async def apply_programme_status(d: RunDeps, claim: Claim) -> None:
    """A supported relation claim that states a programme's status updates the Programme
    entity, in Postgres and in the graph, when it is newer than the status held (T-06)."""
    if claim.kind is not ClaimKind.RELATION:
        return
    relation = await d.relational.research.relation(claim.claim_id)
    if relation is None or relation.programme_status is None:
        return
    status = relation.programme_status
    as_of = observed_on(
        status, claim.labels.reference_end, relation.valid_from, relation.valid_to
    )  # when the status was observed (owner, BD-19)
    ents = await d.relational.entities.get([relation.subject_entity_id, relation.object_entity_id])
    for entity in ents.values():
        if entity.entity_type is not EntityType.PROGRAMME:
            continue
        # Decided under a row lock, so two slots updating one programme cannot let an
        # older status win (BD-19)
        merged = await d.relational.entities.update_attributes(
            entity.entity_id,
            lambda held: programme_status_update(
                held, status, claim.claim_id, as_of, relation.valid_from
            ),
        )
        if merged is None:
            continue
        updated = entity.model_copy(update={"attributes": merged})
        try:
            await d.ledger.reserve("indexing")  # the node name is embedded again
            await d.graph.upsert_entity(_node(updated))
        except Exception as exc:  # Postgres holds the status; the node catches up on retry
            log.warning(
                "graph programme status failed for %s (%s)", claim.claim_id, type(exc).__name__
            )
