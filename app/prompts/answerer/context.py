"""Answerer input (LLD-3 §7.1): the question, the bundle's facts as data lines, page
mentions as untrusted <source> blocks (§2.2), and the gap notes of slots without a fact.
Facts are stored values written by code; every string is escaped all the same."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.prompts.safety import UNTRUSTED_INSTRUCTION, wrap_source
from app.prompts.safety import escape_untrusted as _e

MENTION_CHARS = 400  # LLD-3 §7.1: a mention excerpt is at most 400 characters


@dataclass(frozen=True)
class FactLine:
    ref_id: str  # the claim ID
    statement: str
    value: str | None
    level_word: str
    geography_name: str
    period: str
    badge: str | None
    confidence: str
    slot_id: str
    contested_with: str | None


@dataclass(frozen=True)
class MentionLine:
    ref_id: str  # m:{source_id}:{char_start}
    excerpt: str
    publisher_class: str


@dataclass(frozen=True)
class GapLine:
    slot_id: str
    note: str


def build_user_message(
    city_name: str,
    question: str,
    facts: Sequence[FactLine],
    mentions: Sequence[MentionLine],
    gaps: Sequence[GapLine],
) -> str:
    lines = [
        f"- [{f.ref_id}] FACT: {_e(f.statement)} | value {_e(f.value or 'none')}"
        f" | describes {f.level_word} ({_e(f.geography_name)}) | period {f.period}"
        f" | badge {f.badge or 'none'} | confidence {f.confidence} | slot {f.slot_id}"
        f" | contested_with: {f.contested_with or 'none'}"
        for f in facts
    ]
    for m in mentions:
        block = wrap_source(m.ref_id.replace(":", "_"), m.excerpt[:MENTION_CHARS])
        lines.append(
            f"- [{m.ref_id}] MENTION (not confirmed) | source {m.publisher_class}\n{block}"
        )
    gap_lines = [f"- {g.slot_id}: {_e(g.note)}" for g in gaps]
    note = f"\n{UNTRUSTED_INSTRUCTION}" if mentions else ""
    return (
        "<task>Answer the question using only the evidence below.</task>\n"
        "<context>\n"
        f"city: {_e(city_name)}\n"
        f"evidence:\n{chr(10).join(lines) if lines else '- none'}\n"
        f"gaps:\n{chr(10).join(gap_lines) if gap_lines else '- none'}{note}\n"
        "</context>\n"
        f"<question>{_e(question)}</question>"
    )
