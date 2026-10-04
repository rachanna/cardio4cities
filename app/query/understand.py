"""Understanding the question (LLD-5 §3): the classifier names the type, slots,
indicators, entities and date; code validates them and, for an elliptical follow-up,
merges the previous turn's classification (never its answer text, RD-09)."""

import calendar
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from app.prompts.classifier import context
from app.prompts.classifier.schema import ClassifierOutput, EntityMention
from app.prompts.loader import load_prompt
from app.query.llm import call
from app.query.types import AskDeps, Understanding

MAX_SUB_QUESTIONS = 3  # LLD-5 §3.1
_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def parse_as_of(value: str | None) -> date | None:
    """A date the user gave, as its last day: "2023" is 2023-12-31, "2023-04" is
    2023-04-30; anything else is dropped (LLD-3 §6.3)."""
    if not value:
        return None
    m = _DATE.match(value.strip())
    if m is None:
        return None
    year, month, day = int(m[1]), m[2], m[3]
    try:
        if month is None:
            return date(year, 12, 31)
        if day is None:
            return date(year, int(month), calendar.monthrange(year, int(month))[1])
        return date(year, int(month), int(day))
    except ValueError:
        return None


def validate(
    out: ClassifierOutput,
    known_slots: Sequence[str],
    known_indicators: Sequence[str],
    model_id: str | None = None,
) -> Understanding:
    """Unknown slots and indicators removed; the date parsed or dropped; at most three
    sub-questions (LLD-5 §3.1). Order is kept, repeats removed."""
    return Understanding(
        question_type=out.question_type,
        slot_ids=tuple(dict.fromkeys(s for s in out.slot_ids if s in known_slots)),
        indicator_codes=tuple(
            dict.fromkeys(c for c in out.indicator_codes if c in known_indicators)
        ),
        entity_mentions=tuple(m for m in out.entity_mentions if m.text.strip()),
        as_of=parse_as_of(out.as_of),
        sub_questions=tuple(q for q in out.sub_questions if q.strip())[:MAX_SUB_QUESTIONS],
        refers_to_previous=out.refers_to_previous,
        classified_by=model_id,
    )


def merge(current: Understanding, previous: Mapping[str, Any] | None) -> Understanding:
    """A follow-up takes the previous turn's slots, indicators and entities for whatever
    it does not name itself (LLD-5 §3.2). Only the immediately previous turn is used."""
    if not current.refers_to_previous or not previous:
        return current
    merged: list[str] = []
    slots, indicators, entities = (
        current.slot_ids,
        current.indicator_codes,
        current.entity_mentions,
    )
    if not slots and previous.get("slot_ids"):
        slots = tuple(previous["slot_ids"])
        merged += list(slots)
    if not indicators and previous.get("indicator_codes"):
        indicators = tuple(previous["indicator_codes"])
        merged += list(indicators)
    if not entities and previous.get("entity_mentions"):
        entities = tuple(EntityMention.model_validate(m) for m in previous["entity_mentions"])
        merged += [m.text for m in entities]
    question_type = current.question_type
    if question_type == "out_of_scope" and slots:
        question_type = previous.get("question_type") or "open"  # "and nationally?" is in scope
    return Understanding(
        question_type=question_type,
        slot_ids=slots,
        indicator_codes=indicators,
        entity_mentions=entities,
        as_of=current.as_of,
        sub_questions=current.sub_questions,
        refers_to_previous=True,
        merged_from_previous=tuple(merged),
        classified_by=current.classified_by,
    )


def previous_line(previous: Mapping[str, Any] | None) -> str | None:
    """The previous turn's classification as the classifier sees it (LLD-3 §6.1)."""
    if not previous:
        return None
    mentions = ", ".join(m.get("text", "") for m in previous.get("entity_mentions") or [])
    return (
        f"slots {', '.join(previous.get('slot_ids') or []) or 'none'}; "
        f"indicators {', '.join(previous.get('indicator_codes') or []) or 'none'}; "
        f"entities {mentions or 'none'}"
    )


async def understand(
    deps: AskDeps, question: str, previous: Mapping[str, Any] | None
) -> Understanding:
    prompt = load_prompt("classifier")
    user = context.build_user_message(
        deps.city.name,
        [deps.slots[s] for s in sorted(deps.slots)],
        [deps.indicators[c] for c in sorted(deps.indicators)],
        deps.today,
        previous_line(previous),
        question,
    )
    out, model_id = await call(deps, "classifier", prompt.system, user, ClassifierOutput)
    valid = validate(out, list(deps.slots), list(deps.indicators), model_id)
    return merge(valid, previous)
