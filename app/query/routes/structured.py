"""R1 structured (LLD-5 §4): confirmed claims for the slots or indicators asked about,
from `v_city_facts`, ordered by the ranking key (LLD-2 §5.2)."""

from collections.abc import Sequence

from app.domain.models import StoredFact
from app.domain.ranking import Candidate, rank_key
from app.query.routes import timed
from app.query.types import AskDeps, RouteResult, Understanding


def structured(facts: Sequence[StoredFact], u: Understanding, deps: AskDeps) -> list[str]:
    """Confirmed claims for the slots or indicators asked about, by the ranking key."""
    wanted = [
        f
        for f in facts
        if f.claim.slot_id in u.slot_ids
        or (f.indicator_code and f.indicator_code in u.indicator_codes)
    ]

    def key(f: StoredFact) -> tuple[object, ...]:
        accepted = deps.slots[f.claim.slot_id].accepted_levels
        return rank_key(Candidate(f.claim, f.source.publisher_class), accepted)

    return [f.claim.claim_id for f in sorted(wanted, key=key)]


async def r1(deps: AskDeps, u: Understanding, facts: Sequence[StoredFact]) -> RouteResult:
    async def work(route: RouteResult) -> None:
        if not (u.slot_ids or u.indicator_codes):
            route.status, route.note = "skipped", "no slot or indicator identified"
            return
        route.candidates = structured(facts, u, deps)

    return await timed(RouteResult("R1"), work)
