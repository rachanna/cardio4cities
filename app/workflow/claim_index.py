"""The only way a claim's status changes (CHG-01, LLD-5 §4.1-4.2, AT-39).

`set_status` writes Postgres first, then brings the two retrieval indexes in line:
`claim.search_tsv` (keyword route) and the claim's point in `claim_index__{key}`
(semantic route). Supported and contested claims are indexed; any other status removes
the point. An index failure is logged and never undoes the Postgres status: Postgres has
the final word, and retrieval re-validates every candidate against it (RD-04).

A claim becomes supported or contested only when its stored verdict is `supported`
(BD-18): whatever calls this, a refuted or insufficient verdict can never become a fact.
"""

import logging

from app.domain.ids import graph_uuid
from app.domain.vocab import ClaimStatus
from app.ports.vector import VectorPoint
from app.workflow.deps import RunDeps

log = logging.getLogger(__name__)

INDEXED = frozenset({ClaimStatus.SUPPORTED.value, ClaimStatus.CONTESTED.value})
PAYLOAD_FIELDS = (
    "claim_id",
    "city_id",
    "run_id",
    "slot_id",
    "kind",
    "status",
    "geography_level",
    "indicator_code",
)


def claim_point_id(claim_id: str) -> str:
    """uuid5(NAMESPACE, claim_id), LLD-5 §4.2."""
    return graph_uuid(claim_id)


def index_text(statement: str, quote: str, translation: str | None) -> str:
    """The statement (always English) and the translation, or the quote (LLD-5 §4.2)."""
    return f"{statement} | {translation or quote}"


class VerdictMismatchError(RuntimeError):
    """A claim would become a fact without a supported verdict (BD-18)."""


async def set_status(d: RunDeps, claim_id: str, status: ClaimStatus) -> None:
    research = d.relational.research
    if status.value in INDEXED:
        verdict = await research.stored_verdict(claim_id)
        if verdict is None or verdict["label"] != "supported":
            label = verdict["label"] if verdict else "none"
            raise VerdictMismatchError(f"{claim_id}: status {status.value} with verdict {label}")
    await research.set_claim_status(claim_id, status.value)
    await sync(d, claim_id)


async def sync(d: RunDeps, claim_id: str) -> None:
    """Refresh both indexes from the claim's current row."""
    research = d.relational.research
    try:
        await research.refresh_search_tsv(claim_id)
        row = await research.claim_index_row(claim_id)
        if row is None:
            return
        if row["status"] not in INDEXED:
            await d.vector.delete_by_filter(d.claim_collection, {"claim_id": claim_id})
            return
        await d.ledger.reserve("indexing")  # a confirmed claim: never refused (BD-19)
        text = index_text(row["statement"], row["quote"], row["quote_translation"])
        (vector,) = await d.embeddings.embed([text])
        payload = {k: row[k] for k in PAYLOAD_FIELDS if row.get(k) is not None}
        if row.get("reference_end") is not None:
            payload["reference_end"] = row["reference_end"].isoformat()
        await d.vector.upsert(
            d.claim_collection,
            [VectorPoint(id=claim_point_id(claim_id), vector=vector, payload=payload)],
        )
    except Exception as exc:  # any index failure: Postgres keeps the final word
        log.warning("claim index not updated for %s (%s)", claim_id, type(exc).__name__)
