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

# Search languages in gap notes (LLD-2 §11.4). Generic ISO 639-1 names; a code not listed
# is shown as written.
LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic", "bn": "Bengali", "de": "German", "en": "English", "es": "Spanish",
    "fa": "Persian", "fr": "French", "gu": "Gujarati", "hi": "Hindi", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "kn": "Kannada", "ko": "Korean", "ml": "Malayalam",
    "mr": "Marathi", "ms": "Malay", "nl": "Dutch", "pa": "Punjabi", "pl": "Polish",
    "pt": "Portuguese", "ru": "Russian", "sw": "Swahili", "ta": "Tamil", "te": "Telugu",
    "th": "Thai", "tl": "Tagalog", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "vi": "Vietnamese", "zh": "Chinese",
}  # fmt: skip


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.lower(), code)
