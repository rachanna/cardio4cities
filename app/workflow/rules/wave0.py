"""Wave 0 rules (LLD-2 §13, BD-13). Pure.

The record used is the latest one for the registry's sex and age group in the city's
country. Its canonical one-line rendering is the claim's quote and the source's parsed
text. Code verification re-parses the stored snapshot and requires the same record:
indicator, area, period and value exactly equal.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from app.domain.models import SourceIndicator
from app.ports.structured import StructuredRecord
from app.workflow.rules.numbers import PERCENT, ParsedValue, parse_value

CODE_VERIFIER = "code:record_match"
CODE_FAMILY = "code"


_PLAIN_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
UNIT_NAMES = {"%": PERCENT}  # registry units in the parser's words (BD-19)


def record_value(value_as_written: str, unit: str | None) -> ParsedValue:
    """The value of an official record: parsed as any figure, and a bare number such as
    "22.6" (how the WHO API writes values) read in code with the registry's unit."""
    parsed = parse_value(value_as_written)
    named = UNIT_NAMES.get(unit or "", unit)
    if parsed.unparsed and _PLAIN_NUMBER.match(value_as_written.strip()):
        return ParsedValue(Decimal(value_as_written.strip()), named)
    if parsed.unit is None and named:
        return replace(parsed, unit=named)
    return parsed


def select_record(
    records: Sequence[StructuredRecord], indicator: SourceIndicator, country_iso3: str
) -> StructuredRecord | None:
    """The latest record of the registry's own indicator for the country, sex and, when
    the indicator has an age dimension, age group. Never guessed (BD-34; code review
    RV-033): two records for the latest year (dimensions the registry does not name), or
    a latest value code cannot read, give no record, never an older year. A year the
    provider did not publish is not a record at all."""
    matching = [
        r
        for r in records
        if r.indicator_code == indicator.code
        and r.area_code == country_iso3
        and r.sex == indicator.sex
        and (indicator.age_group is None or r.age_group == indicator.age_group)
    ]
    if not matching:
        return None
    latest = max(r.year for r in matching)
    newest = [r for r in matching if r.year == latest]
    if len(newest) != 1 or not newest[0].value_as_written:
        return None
    return newest[0]


def age_text(indicator: SourceIndicator) -> str:
    if indicator.age is None:
        return "all ages"
    low, high = indicator.age
    return f"{low}+" if high is None else f"{low}-{high}"


def canonical_line(record: StructuredRecord, indicator: SourceIndicator) -> str:
    """e.g. `NCD_HYP_CONTROL_A | XNV | 2019 | SEX_BTSX | 30-79 | 14.8 [9.6-21.2]`."""
    return " | ".join(
        [
            record.indicator_code,
            record.area_code,
            str(record.year),
            record.sex,
            age_text(indicator),
            record.display or record.value_as_written,
        ]
    )


@dataclass(frozen=True)
class CodeCheck:
    matched: bool
    reason: str  # stored as the verdict rationale (at most 400 characters)


def code_check(
    quote: str,
    value_as_written: str,
    reread: Sequence[StructuredRecord],
    indicator: SourceIndicator,
    country_iso3: str,
) -> CodeCheck:
    """Re-read the record from the snapshot; the claim must equal it exactly."""
    record = select_record(reread, indicator, country_iso3)
    if record is None:
        return CodeCheck(
            False, "The stored response holds no record for this country, sex and age."
        )
    if canonical_line(record, indicator) != quote:
        return CodeCheck(
            False, "The stored record's indicator, area, period or value differs from the claim."
        )
    if record.value_as_written != value_as_written:
        return CodeCheck(False, "The stored record's value differs from the claim's value.")
    return CodeCheck(
        True,
        f"The stored {record.indicator_code} record for {record.area_code}, {record.year} "
        f"({record.sex}, {age_text(indicator)}) has the value {record.value_as_written},"
        " as claimed.",
    )
