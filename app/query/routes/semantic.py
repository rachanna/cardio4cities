"""R3 semantic (LLD-5 §4.2): the claim index by meaning; separately, page passages that
became no confirmed claim, as mentions only."""

from collections.abc import Sequence

from app.domain.models import StoredFact
from app.domain.prices import embedding_cost_micro_usd
from app.domain.vocab import ClaimStatus
from app.query.routes import timed
from app.query.types import AskDeps, Mention, RouteResult


def unconfirmed(mention: Mention, facts: Sequence[StoredFact]) -> bool:
    """A passage holding no confirmed claim's quote: only those may be mentions."""
    return not any(
        f.claim.source_id == mention.source_id
        and f.claim.span_start < mention.char_end
        and f.claim.span_end > mention.char_start
        for f in facts
    )


async def r3(deps: AskDeps, question: str, facts: Sequence[StoredFact]) -> RouteResult:
    async def work(route: RouteResult) -> None:
        if deps.embeddings is None or deps.vector is None:
            route.status, route.note = "degraded", "no embeddings or vector store"
            return
        await deps.ledger.reserve("embedding")
        (vector,) = await deps.embeddings.embed([question])
        tokens = max(len(question) // 4, 1)
        await deps.ledger.record_embedding(
            deps.embedding_model, tokens, embedding_cost_micro_usd(deps.embedding_model, tokens)
        )
        filters = {
            "city_id": deps.city_id,
            "run_id": deps.run_id,
            "status": [ClaimStatus.SUPPORTED.value, ClaimStatus.CONTESTED.value],
        }
        hits = await deps.vector.search(deps.claim_collection, vector, filters, deps.params.r3_top)
        route.candidates = list(dict.fromkeys(str(h.payload["claim_id"]) for h in hits))
        # Every vector search names the city (the adapter refuses one that does not):
        # without it this search failed and took the claim hits with it (FX-19, BD-53)
        chunks = await deps.vector.search(
            deps.chunk_collection,
            vector,
            {"city_id": deps.city_id, "run_id": deps.run_id},
            deps.params.r3_mentions_top * 3,
        )
        mentions = [
            Mention(
                source_id=str(h.payload["source_id"]),
                char_start=int(h.payload["char_start"]),
                char_end=int(h.payload["char_end"]),
                text=str(h.payload.get("text", "")),
                publisher_class=str(h.payload.get("publisher_class", "other")),
            )
            for h in chunks
        ]
        route.mentions = [m for m in mentions if unconfirmed(m, facts)][
            : deps.params.r3_mentions_top
        ]

    return await timed(RouteResult("R3"), work)
