"""Controlled vocabularies (LLD-1 §1). Database CHECK constraints use the same values.

Started in D1-3 with what reference data needs; D2-1 adds the rest.
"""

from enum import StrEnum


class GeographyLevel(StrEnum):
    """What a figure actually describes, ordered from finest to broadest."""

    CITY_WIDE = "city_wide"
    SUB_CITY_AREA = "sub_city_area"
    SUB_CITY_POPULATION = "sub_city_population"
    METRO_REGION = "metro_region"
    DISTRICT = "district"
    STATE_PROVINCE = "state_province"
    NATIONAL = "national"
    GLOBAL = "global"


class AnswerKind(StrEnum):
    STATISTIC = "statistic"
    RELATION = "relation"
    STATEMENT = "statement"
    MIXED = "mixed"


class RelationType(StrEnum):
    """Graph relation types (LLD-1 §6.2)."""

    GOVERNS = "GOVERNS"
    REPLACED_BY = "REPLACED_BY"
    PART_OF = "PART_OF"
    RUNS = "RUNS"
    FUNDS = "FUNDS"
    PARTNERS_WITH = "PARTNERS_WITH"
    OPERATES_IN = "OPERATES_IN"
    ISSUED_BY = "ISSUED_BY"
    APPLIES_TO = "APPLIES_TO"
    LEADS = "LEADS"
    MEASURED_IN = "MEASURED_IN"
