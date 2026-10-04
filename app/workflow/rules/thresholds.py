"""Threshold coding (LLD-2 §4.3): `case_definition` as written -> a code such as
`bp_140_90`, using the pattern table from `reference/thresholds.yaml`.

The caller loads the YAML and passes its parsed content; this module does no I/O.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.workflow.rules.quotes import normalise_text


@dataclass(frozen=True)
class ThresholdRule:
    code: str
    patterns: tuple[re.Pattern[str], ...]
    exclude: re.Pattern[str] | None = None  # never applies when this matches (BD-33)


def threshold_table(raw: Sequence[Mapping[str, Any]]) -> tuple[ThresholdRule, ...]:
    """Build the table from the YAML content; refuses empty or invalid entries."""
    rules = []
    for entry in raw:
        code, patterns = entry.get("code"), entry.get("patterns")
        if not isinstance(code, str) or not code or not patterns:
            raise ValueError(f"threshold rule needs a code and patterns: {entry!r}")
        exclude = entry.get("exclude")
        rules.append(ThresholdRule(code, tuple(re.compile(p) for p in patterns),
                                   re.compile(exclude) if exclude else None))  # fmt: skip
    return tuple(rules)


# Comparison signs, as the patterns read them (BD-33)
_SIGNS = str.maketrans({"\u2265": ">=", "\u2a7e": ">=", "\u2264": "<=", "\u2a7d": "<="})


def threshold_code(case_definition: str | None, table: Sequence[ThresholdRule]) -> str | None:
    if not case_definition:
        return None
    text = normalise_text(case_definition).lower().translate(_SIGNS)
    for rule in table:
        if rule.exclude is not None and rule.exclude.search(text):
            continue
        if any(p.search(text) for p in rule.patterns):
            return rule.code
    return None
