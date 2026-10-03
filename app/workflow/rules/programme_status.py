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
SINCE = "status_since"


def programme_status_update(
    attributes: dict[str, Any],
    status: ProgrammeStatus,
    claim_id: str,
    as_of: date | None,
    since: date | None = None,
) -> dict[str, Any] | None:
    """The attributes to merge into the entity, or None when the current status stands.
    Observed on the same date (one report telling a history), the status with the later
    stated start is the later state; then the lower claim ID, in any arrival order."""
    new = {
        STATUS: status.value,
        CLAIM: claim_id,
        AS_OF: as_of.isoformat() if as_of else None,
        SINCE: since.isoformat() if since else None,
    }
    current = attributes.get(STATUS)
    if current is None or current == ProgrammeStatus.UNKNOWN.value:
        return new if current is None or status is not ProgrammeStatus.UNKNOWN else None
    if status is ProgrammeStatus.UNKNOWN or as_of is None:
        return None
    held = attributes.get(AS_OF)
    if held is not None:
        held_date = date.fromisoformat(held)
        if held_date > as_of:
            return None
        if held_date == as_of:
            held_since, new_since = attributes.get(SINCE) or "", new[SINCE] or ""
            if new_since < held_since:
                return None
            if new_since == held_since and claim_id >= str(attributes.get(CLAIM, "")):
                return None
    return new


def observed_on(
    status: ProgrammeStatus,
    reference_end: date | None,
    valid_from: date | None,
    valid_to: date | None,
) -> date | None:
    """When the status was observed (owner, BD-19): for `ended`, when it ended; otherwise
    the claim's period end, which is the source's publication date when no period is
    stated, so "running since 2018" in a 2024 report counts as of 2024."""
    if status is ProgrammeStatus.ENDED:
        return valid_to or reference_end
    return reference_end or valid_from
