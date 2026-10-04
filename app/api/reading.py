"""Shared by the read endpoints (LLD-4 §2-3, D3-1): paging, and what turns stored facts
into FactCards (slots, badge and confidence parameters, today's date)."""

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.api.errors import ApiError, dependency_unavailable
from app.domain.cards import FactCard, fact_card
from app.domain.models import SlotDef, StoredFact
from app.domain.params import BadgeParams, ConfidenceParams
from app.ports.repos import RelationalPort

DEFAULT_LIMIT, MAX_LIMIT = 50, 200  # LLD-4 §2


def relational(request: Request) -> RelationalPort:
    store: RelationalPort | None = request.app.state.container.relational
    if store is None:
        raise dependency_unavailable("postgres", "The research store is not available.")
    return store


def page(limit: int | None, cursor: str | None) -> tuple[int, int]:
    """(limit, offset) from `?limit=` and the opaque `?cursor=`."""
    size = DEFAULT_LIMIT if limit is None else limit
    if not 1 <= size <= MAX_LIMIT:
        raise ApiError(400, "invalid_limit", f"limit must be between 1 and {MAX_LIMIT}.")
    if not cursor:
        return size, 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ApiError(400, "invalid_cursor", "That cursor is not one this API gave.") from None
    if offset < 0:
        raise ApiError(400, "invalid_cursor", "That cursor is not one this API gave.")
    return size, offset


def next_cursor(offset: int, size: int, returned: int, total: int | None = None) -> str | None:
    following = offset + size
    if returned < size or (total is not None and following >= total):
        return None
    return base64.urlsafe_b64encode(str(following).encode()).decode()


@dataclass(frozen=True)
class CardMaker:
    """Turns stored facts into FactCards with today's badges and confidence."""

    slots: dict[str, SlotDef]
    badge: BadgeParams
    confidence: ConfidenceParams
    today: Any

    def card(self, fact: StoredFact) -> FactCard:
        slot = self.slots[fact.claim.slot_id]
        return fact_card(fact, slot, self.today, self.badge, self.confidence)


async def card_maker(request: Request) -> CardMaker:
    cfg = request.app.state.container.settings.config
    slots = {s.slot_id: s for s in await relational(request).reference.slots()}
    return CardMaker(
        slots=slots,
        badge=BadgeParams(**cfg.badge.model_dump()),
        confidence=ConfidenceParams(**cfg.confidence.model_dump()),
        today=datetime.now(UTC).date(),
    )


async def city(request: Request, city_id: str) -> dict[str, Any]:
    """The city row; 404 for an unknown city, 404 too when it has no finished run yet."""
    row = await relational(request).runs.city_row(city_id)
    if row is None:
        raise ApiError(404, "not_found", "That city has not been researched.")
    if row["latest_run_id"] is None:
        raise ApiError(404, "no_finished_run", "That city has no finished research run yet.")
    return row
