"""Parameters for the pure rules. Every `[tunable]` value comes from config
(CLAUDE.md): the caller builds these from `Settings.config`; nothing here has
a default, so a rule can never run on a literal by accident."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class QuoteParams:
    min_words: int  # quote.min_words (LLD-2 §4.1)
    max_words: int  # quote.max_words


@dataclass(frozen=True)
class ConsistencyParams:
    agree_pp: Decimal  # consistency.agree_pp: percentage points for percent values
    agree_rel: Decimal  # consistency.agree_rel: relative difference otherwise


@dataclass(frozen=True)
class BadgeParams:
    stale_years: int  # badge.stale_years: statistics and statements
    stale_years_people: int  # badge.stale_years_people: LEADS relations
    small_sample: int  # badge.small_sample


@dataclass(frozen=True)
class ConfidenceParams:
    recent_years: int  # confidence.recent_years


@dataclass(frozen=True)
class ReplanParams:
    max_rounds: int  # replan.max_rounds
    max_rounds_wider_geo: int  # replan.max_rounds_wider_geo


@dataclass(frozen=True)
class VerifyParams:
    max_claims_per_slot: int  # verify.max_claims_per_slot (LLD-2 §5.3)
