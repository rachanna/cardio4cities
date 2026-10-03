"""A fictional gazetteer (Halden Bay, Norvania) in GeoNames dump format, for tests that
need places in the database."""

from app.adapters.postgres.relational import PostgresRelational
from scripts.reference.geonames import build_gazetteer


def _line(*fields: str) -> str:
    return "\t".join(fields) + "\n"


COUNTRIES = "#ISO\tISO3\t...\n" + _line(
    "XN", "XNV", "999", "XN", "Norvania", "Halden Bay", "1", "1", "EU", ".xn", "NVK", "Krona",
    "99", "", "", "nv-XN,en,nor", "1", "", "",
)  # fmt: skip
ADMIN1 = _line("XN.01", "West Coast", "West Coast", "11") + _line("XN.02", "Inland", "Inland", "12")
PLACE = _line(
    "9000001", "Halden Bay", "Halden Bay", "Haldenbukt,HB", "60.1", "5.2", "P", "PPLC", "XN", "",
    "01", "", "", "", "420000", "", "5", "Europe/Oslo", "2026-01-01",
)  # fmt: skip
TOWN = _line(
    "9000002", "Port Ostra", "Port Ostra", "", "61.0", "6.0", "P", "PPL", "XN", "",
    "02", "", "", "", "18000", "", "5", "Europe/Oslo", "2026-01-01",
)  # fmt: skip


async def sync_gazetteer(
    store: PostgresRelational, places: str
) -> list[tuple[str, int, int, int, int]]:
    g = build_gazetteer(COUNTRIES, ADMIN1, places)
    results = await store.reference.sync_gazetteer(g.countries, g.admin1, g.places)
    return [(r.table, r.inserted, r.updated, r.deleted, r.total) for r in results]


# About 25 km from Halden Bay: within geography.nearby_km (Port Ostra is about 110 km away)
NEAR_TOWN = _line(
    "9000005", "Kestrel Point", "Kestrel Point", "", "60.3", "5.5", "P", "PPL", "XN", "",
    "01", "", "", "", "21000", "", "5", "Europe/Oslo", "2026-01-01",
)  # fmt: skip
