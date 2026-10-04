"""Report writer input (LLD-3 §8.1-8.2): placed facts as data lines (reference, statement,
badge) and gap notes. Every string is escaped: statements and notes are stored values,
but quotes behind them came from fetched pages."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.prompts.safety import escape_untrusted as _e


@dataclass(frozen=True)
class FactRef:
    ref_id: str
    statement: str
    badge: str | None


def _facts(facts: Sequence[FactRef]) -> str:
    lines = [f"- [{f.ref_id}] {_e(f.statement)} | badge {f.badge or 'none'}" for f in facts]
    return "\n".join(lines) if lines else "- none"


def _gaps(gaps: Sequence[str]) -> str:
    return "\n".join(f"- {_e(g)}" for g in gaps) if gaps else "- none"


def intro_message(
    city_name: str, dimension: str, facts: Sequence[FactRef], gaps: Sequence[str], max_words: int
) -> str:
    return (
        f"<task>Write the introduction to the {_e(dimension)} section: one paragraph of at"
        f" most {max_words} words.</task>\n"
        "<context>\n"
        f"city: {_e(city_name)}\n"
        f"facts in this section:\n{_facts(facts)}\n"
        f"gaps in this section:\n{_gaps(gaps)}\n"
        "</context>"
    )


def analysis_message(
    city_name: str, facts: Sequence[FactRef], gaps: Sequence[str], max_points: int
) -> str:
    return (
        f"<task>Write up to {max_points} points on opportunities, risks and gaps, each"
        " derived from the facts it names.</task>\n"
        "<context>\n"
        f"city: {_e(city_name)}\n"
        f"summary facts:\n{_facts(facts)}\n"
        f"gaps:\n{_gaps(gaps)}\n"
        "</context>"
    )
