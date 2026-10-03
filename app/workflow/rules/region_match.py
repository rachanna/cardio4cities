"""Sub-national records (LLD-2 §13): a provider's region counts as the city's first-level
region only when the names match after normalisation, or the region appears in
`reference/region_aliases.yaml` for that admin-1 name. Otherwise it is skipped, never
guessed. Pure. No provider in the registry serves sub-national data yet (BD-13); the rule
is ready for one that does."""

from collections.abc import Mapping, Sequence

from app.workflow.rules.entity_resolution import normalized_key

# Generic words for kinds of first-level region, dropped before comparing
REGION_WORDS = frozenset(
    [
        "region",
        "state",
        "province",
        "division",
        "department",
        "departement",
        "governorate",
        "oblast",
        "county",
        "district",
        "territory",
        "prefecture",
        "zone",
    ]
)


def region_key(name: str) -> str:
    return "-".join(w for w in normalized_key(name).split("-") if w not in REGION_WORDS)


def region_matches(
    provider_region: str, admin1_name: str | None, aliases: Mapping[str, Sequence[str]]
) -> bool:
    """`aliases`: admin-1 name -> other names a provider uses for it (owner-approved)."""
    if not admin1_name:
        return False
    wanted = region_key(provider_region)
    if not wanted:
        return False
    if wanted == region_key(admin1_name):
        return True
    return any(wanted == region_key(alias) for alias in aliases.get(admin1_name, ()))
