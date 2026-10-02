"""ReferenceRepo on Postgres: loads are idempotent and the start-up checks pass on the
shipped reference files. Gazetteer rows are fictional (Halden Bay, Norvania)."""

import pytest
from sqlalchemy import text

from app.adapters.postgres.relational import PostgresRelational
from app.settings import check_indicator_codes, check_reference_slots
from scripts.reference.geonames import build_gazetteer
from scripts.reference.yaml_reference import (
    REFERENCE_DIR,
    read_indicators,
    read_slots,
    read_sources,
)

pytestmark = pytest.mark.db


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


async def _sync_gazetteer(
    store: PostgresRelational, places: str
) -> list[tuple[str, int, int, int, int]]:
    g = build_gazetteer(COUNTRIES, ADMIN1, places)
    results = await store.reference.sync_gazetteer(g.countries, g.admin1, g.places)
    return [(r.table, r.inserted, r.updated, r.deleted, r.total) for r in results]


async def test_shipped_reference_yaml_loads_and_passes_startup_checks(
    relational: PostgresRelational,
) -> None:
    indicators = read_indicators()
    sources = read_sources(REFERENCE_DIR, {i.code for i in indicators})

    await relational.reference.sync_indicators(indicators)
    await relational.reference.sync_slots(read_slots())
    await relational.reference.sync_sources(sources.ready)

    assert await relational.reference.slot_ids() == [f"S{n:02d}" for n in range(1, 17)]
    assert check_reference_slots(await relational.reference.slot_ids()) == []
    assert check_indicator_codes(await relational.reference.indicator_codes()) == []


async def test_yaml_sync_is_idempotent(relational: PostgresRelational) -> None:
    slots = read_slots()

    first = await relational.reference.sync_slots(slots)
    second = await relational.reference.sync_slots(slots)

    assert (first.inserted, first.total) == (16, 16)
    assert (second.inserted, second.updated, second.deleted, second.total) == (0, 0, 0, 16)


async def test_yaml_sync_updates_changed_rows_and_removes_dropped_ones(
    relational: PostgresRelational,
) -> None:
    indicators = read_indicators()
    await relational.reference.sync_indicators(indicators)
    changed = [indicators[0].model_copy(update={"notes": "changed"}), *indicators[1:-1]]

    result = await relational.reference.sync_indicators(changed)

    assert (result.updated, result.deleted, result.total) == (1, 1, len(indicators) - 1)


async def test_placeholder_providers_are_never_written(relational: PostgresRelational) -> None:
    sources = read_sources(REFERENCE_DIR, {i.code for i in read_indicators()})
    await relational.reference.sync_sources(sources.ready)

    codes = await relational.reference.indicator_codes()

    assert sources.pending  # WHO and DHS stay pending until the D1-5 spike
    assert not any(key.split(".")[0] in sources.pending for key in codes)


async def test_gazetteer_sync_is_idempotent(relational: PostgresRelational) -> None:
    first = await _sync_gazetteer(relational, PLACE + TOWN)
    second = await _sync_gazetteer(relational, PLACE + TOWN)

    assert first == [
        ("ref_country", 1, 0, 0, 1),
        ("ref_admin1", 2, 0, 0, 2),
        ("ref_place", 2, 0, 0, 2),
    ]
    assert second == [
        ("ref_country", 0, 0, 0, 1),
        ("ref_admin1", 0, 0, 0, 2),
        ("ref_place", 0, 0, 0, 2),
    ]


async def test_gazetteer_sync_keeps_places_a_city_refers_to(relational: PostgresRelational) -> None:
    await _sync_gazetteer(relational, PLACE + TOWN)
    engine = relational._engine
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO city (city_id, gazetteer_id, identity) "
                "VALUES ('city_t', '9000001', '{}')"
            )
        )

    result = await _sync_gazetteer(relational, "")  # both places gone from the dump

    assert result[2] == ("ref_place", 0, 0, 1, 1)  # Port Ostra deleted, Halden Bay kept


async def test_gazetteer_stores_parsed_fields(relational: PostgresRelational) -> None:
    await _sync_gazetteer(relational, PLACE)
    async with relational._engine.connect() as conn:
        place = (await conn.execute(text("SELECT * FROM ref_place"))).one()
        country = (await conn.execute(text("SELECT * FROM ref_country"))).one()

    assert place.alternate_names == ["Haldenbukt", "HB"]
    assert (place.admin1_code, place.population, place.timezone) == ("01", 420000, "Europe/Oslo")
    assert country.languages == ["nv", "en"]
