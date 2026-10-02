"""User-facing vocabulary (R-90): the words the City Lead sees for internal values."""

from app.domain.vocab import Badge, ClaimStatus, ConfidenceLabel, GeographyLevel, SlotStatus

LEVEL_WORDS: dict[GeographyLevel, str] = {
    GeographyLevel.CITY_WIDE: "city-wide",
    GeographyLevel.SUB_CITY_AREA: "part of the city",
    GeographyLevel.SUB_CITY_POPULATION: "a group within the city",
    GeographyLevel.METRO_REGION: "metropolitan area",
    GeographyLevel.DISTRICT: "district",
    GeographyLevel.STATE_PROVINCE: "state or regional",
    GeographyLevel.NATIONAL: "national",
    GeographyLevel.GLOBAL: "global",
}

SLOT_STATUS_WORDS: dict[SlotStatus, str] = {  # LLD-4 §2.1
    SlotStatus.ANSWERED: "Answered",
    SlotStatus.ANSWERED_WIDER_GEO: "Wider area only",
    SlotStatus.ANSWERED_NEGATIVE: "Not found",
    SlotStatus.BLOCKED: "Blocked by source",
    SlotStatus.UNREACHABLE: "Source unreachable",
}

REPORTED_NOT_CONFIRMED = "Reported, not confirmed"  # R-90; LLD-4 §3.3

CLAIM_STATUS_WORDS: dict[ClaimStatus, str] = {
    ClaimStatus.EXTRACTED: REPORTED_NOT_CONFIRMED,
    ClaimStatus.DROPPED: REPORTED_NOT_CONFIRMED,
    ClaimStatus.SUPPORTED: "Confirmed",
    ClaimStatus.REFUTED: REPORTED_NOT_CONFIRMED,
    ClaimStatus.INSUFFICIENT: REPORTED_NOT_CONFIRMED,
    ClaimStatus.CONTESTED: "Sources disagree",
    ClaimStatus.SUPERSEDED: "Replaced by newer information",
}

BADGE_LABELS: dict[Badge, str] = {
    Badge.NOT_CITY_LEVEL: "Not city-level",
    Badge.SOURCES_DISAGREE: "Sources disagree",
    Badge.OUTDATED: "Outdated",
    Badge.LIMITED_SAMPLE: "Limited sample",
}

CONFIDENCE_WORDS: dict[ConfidenceLabel, str] = {
    ConfidenceLabel.HIGH: "High confidence",
    ConfidenceLabel.MEDIUM: "Medium confidence",
    ConfidenceLabel.LOW: "Low confidence",
}
