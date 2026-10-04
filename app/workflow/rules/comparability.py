"""Comparability key (LLD-2 §4.4, R-35). Two figures are comparable only if their
keys are equal and not None.

BD-06 adds one rule to LLD-2 §4.4 for AT-21: a care-cascade or prevalence figure
whose denominator is not stated gets no key, so it is never compared with, or
combined with, figures from other sources.
"""

import re
import unicodedata

from app.domain.models import Labels, Statistic
from app.domain.vocab import DENOMINATOR_MEASURES

PART_NAMES = (
    "indicator",
    "threshold",
    "measure type",
    "age band",
    "sex",
    "geography level",
    "geography name",
    "unit",
)


def slug(text: str) -> str:
    """Accents dropped, letters of every script kept: an ASCII-only slug turned a
    non-Latin district name into "", so two districts shared a key (BD-33, RV-085)."""
    decomposed = unicodedata.normalize("NFKD", text)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return re.sub(r"[\W_]+", "-", bare).strip("-")


def _needs_threshold(indicator_code: str) -> bool:
    return indicator_code.startswith("HTN_") or indicator_code == "DM_PREV"


def key_gaps(stat: Statistic, labels: Labels) -> list[str]:
    """Why a statistic has no key; empty when it has one."""
    gaps = []
    if stat.indicator_code == "OTHER":
        gaps.append("indicator is OTHER, never compared")
    if stat.value_num is None:
        gaps.append("no single parsed value")
    if _needs_threshold(stat.indicator_code) and labels.threshold_code is None:
        gaps.append("threshold not stated or not recognised")
    if labels.population_age_min is None or labels.population_age_max is None:
        gaps.append("age band not fully stated")
    if labels.measure_type in DENOMINATOR_MEASURES and not labels.denominator_stated:
        gaps.append("denominator not stated")  # BD-06, AT-21
    return gaps


def key_parts(stat: Statistic, labels: Labels) -> tuple[str, ...]:
    return (
        stat.indicator_code,
        labels.threshold_code or "-",
        labels.measure_type.value,
        f"{labels.population_age_min}-{labels.population_age_max}",
        labels.population_sex.value,
        labels.geography_level.value,
        slug(labels.geography_name),
        stat.unit or "-",
    )


def comparability_key(stat: Statistic, labels: Labels) -> str | None:
    if key_gaps(stat, labels):
        return None
    return "|".join(key_parts(stat, labels))


def differing_parts(a: tuple[Statistic, Labels], b: tuple[Statistic, Labels]) -> list[str]:
    """Names of the key parts that differ between two statistics."""
    return [
        name for name, x, y in zip(PART_NAMES, key_parts(*a), key_parts(*b), strict=True) if x != y
    ]
