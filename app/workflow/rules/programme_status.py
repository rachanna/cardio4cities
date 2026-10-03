"""Programme status on Programme entities (T-06, LLD-1 §6.1, BD-14).

A programme's status, the claim that supports it and the date it holds as of are kept on
the entity, so "planned" is never shown as "running". A newer supported claim replaces an
older one; `unknown` never replaces a stated status, and an undated claim never replaces
a dated one.
"""

from datetime import date
from typing import Any

from app.domain.vocab import ProgrammeStatus

STATUS = "status"
CLAIM = "status_claim_id"
AS_OF = "status_as_of"


def programme_status_update(
    attributes: dict[str, Any], status: ProgrammeStatus, claim_id: str, as_of: date | None
) -> dict[str, Any] | None:
    """The attributes to merge into the entity, or None when the current status stands."""
    new = {STATUS: status.value, CLAIM: claim_id, AS_OF: as_of.isoformat() if as_of else None}
    current = attributes.get(STATUS)
    if current is None or current == ProgrammeStatus.UNKNOWN.value:
        return new if current is None or status is not ProgrammeStatus.UNKNOWN else None
    if status is ProgrammeStatus.UNKNOWN or as_of is None:
        return None
    held = attributes.get(AS_OF)
    if held is not None and date.fromisoformat(held) >= as_of:
        return None  # the same date or older: the first claim to arrive stands
    return new
