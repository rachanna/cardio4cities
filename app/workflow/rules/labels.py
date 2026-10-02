"""Label rules applied by code after extraction (LLD-1 §2.3, §2.4).

Never infers a label: only fills what the rules say, and records what is missing
as a flag.
"""

from datetime import date

from app.domain.models import Labels
from app.domain.params import BadgeParams
from app.domain.vocab import (
    DENOMINATOR_MEASURES,
    ClaimFlag,
    ClaimKind,
    DatePrecision,
    PeriodType,
    Representativeness,
)
from app.workflow.rules.numbers import ParsedValue


def apply_reference_period_rule(
    labels: Labels, published_date: date | None, published_precision: DatePrecision | None
) -> Labels:
    """No stated reference period: the source's publication date stands in, and the
    period type says so (`publication_date_proxy`, always flagged)."""
    if labels.reference_start is not None or labels.reference_end is not None:
        return labels
    return labels.model_copy(
        update={
            "period_type": PeriodType.PUBLICATION_DATE_PROXY,
            "reference_end": published_date,
            "reference_precision": published_precision if published_date else None,
        }
    )


def derive_flags(
    kind: ClaimKind,
    labels: Labels,
    quote_lang: str,
    parsed: ParsedValue | None,
    params: BadgeParams,
) -> frozenset[ClaimFlag]:
    """Stored flags that follow from the labels. `republished` and
    `governing_body_uncertain` are set by the steps that detect them."""
    flags = set()
    if labels.period_type is PeriodType.PUBLICATION_DATE_PROXY:
        flags.add(ClaimFlag.PERIOD_NOT_STATED)
    if quote_lang != "en":
        flags.add(ClaimFlag.TRANSLATED)
    if kind is ClaimKind.STATISTIC:
        if labels.measure_type in DENOMINATOR_MEASURES and not labels.denominator_stated:
            flags.add(ClaimFlag.DENOMINATOR_NOT_STATED)
        if labels.sample_size is not None and labels.sample_size < params.small_sample:
            flags.add(ClaimFlag.SMALL_SAMPLE)
        if labels.representativeness is Representativeness.NON_REPRESENTATIVE:
            flags.add(ClaimFlag.NON_REPRESENTATIVE)
        if labels.setting is None:
            flags.add(ClaimFlag.SETTING_NOT_STATED)
        if parsed is None or parsed.unparsed:
            flags.add(ClaimFlag.VALUE_UNPARSED)
    return frozenset(flags)
