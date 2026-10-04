"""Classifier input (LLD-3 §6.1): the city, the slot and indicator catalogues, today's
date, the previous turn's classification (never its answer text, RD-09), and the
question in its own tag, escaped: it is user input to classify, not instructions."""

from collections.abc import Sequence
from datetime import date

from app.domain.models import IndicatorDef, SlotDef
from app.prompts.safety import escape_untrusted as _e


def build_user_message(
    city_name: str,
    slots: Sequence[SlotDef],
    indicators: Sequence[IndicatorDef],
    today: date,
    previous: str | None,
    question: str,
) -> str:
    slot_lines = "\n".join(f"  {s.slot_id}: {s.short_label}" for s in slots)
    indicator_lines = "\n".join(f"  {i.code}: {i.name}" for i in indicators)
    return (
        "<task>Classify the question and name what it refers to.</task>\n"
        "<context>\n"
        f"city: {_e(city_name)}\n"
        f"slots:\n{slot_lines}\n"
        f"indicators:\n{indicator_lines}\n"
        f"today: {today.isoformat()}\n"
        f"previous turn: {_e(previous) if previous else 'none'}\n"
        "</context>\n"
        f"<question>{_e(question)}</question>"
    )
