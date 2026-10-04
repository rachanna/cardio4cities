"""ReferenceRepo on Postgres: loads are idempotent and the start-up checks pass on the
shipped reference files. Gazetteer rows are fictional (Halden Bay, Norvania)."""

import copy
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from app.adapters.postgres.relational import PostgresRelational
from app.settings import check_indicator_codes, check_reference_slots
from app.workflow.rules.geography_fit import lookup_names
from scripts.reference.load_yaml_reference import load
from scripts.reference.yaml_reference import (
    REFERENCE_DIR,
    read_indicators,
    read_slots,
    read_sources,
)
from tests.support.gazetteer import PLACE, TOWN, _line
from tests.support.gazetteer import sync_gazetteer as _sync_gazetteer

pytestmark = pytest.mark.db


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


async def test_placeholder_providers_are_never_written(
    relational: PostgresRelational, tmp_path: Path
) -> None:
    """BD-03: a provider whose code is still a placeholder is listed as pending, never loaded."""
    shipped = yaml.safe_load((REFERENCE_DIR / "sources.yaml").read_text(encoding="utf-8"))
    pending = copy.deepcopy(shipped[0])
    pending["provider"] = "pending_provider"
    pending["indicators"]["HTN_PREV"]["code"] = "<confirmed by a spike>"
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump([*shipped, pending]), encoding="utf-8")
    sources = read_sources(tmp_path, {i.code for i in read_indicators()})
    await relational.reference.sync_sources(sources.ready)

    codes = await relational.reference.indicator_codes()

    assert sources.pending == {"pending_provider": ["HTN_PREV"]}
    assert not any(key.split(".")[0] == "pending_provider" for key in codes)
    assert any(key.startswith("who_gho.") for key in codes)


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
    assert (place.admin1_code, place.population, place.timezone) == ("01", 420000, "Etc/UTC")
    assert country.languages == ["nv", "en"]


async def test_strict_load_accepts_the_shipped_reference_data(
    relational: PostgresRelational, migrated: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S-2 confirmed every Wave 0 code (BD-13), so the deployed `--strict` load passes and
    the start-up checks accept what it wrote."""
    monkeypatch.setenv("DATABASE_URL", migrated)
    assert await load(REFERENCE_DIR, strict=True) == 0
    assert check_reference_slots(await relational.reference.slot_ids()) == []
    assert check_indicator_codes(await relational.reference.indicator_codes()) == []
    providers = {p.provider: p for p in await relational.reference.sources()}
    assert sorted(providers) == ["who_gho", "world_bank"]
    assert providers["who_gho"].indicators["HTN_CONTROL"].code == "NCD_HYP_CONTROL_A"


async def test_gazetteer_sync_stores_normalised_name_keys(relational: PostgresRelational) -> None:
    """BD-17: name, ASCII name and alternate names, each through `place_key`."""
    await _sync_gazetteer(relational, PLACE)
    async with relational._engine.connect() as conn:
        place = (await conn.execute(text("SELECT name_keys FROM ref_place"))).one()
    assert place.name_keys == ["halden bay", "haldenbukt", "hb"]


async def test_places_are_found_by_the_same_key_claims_use(relational: PostgresRelational) -> None:
    """RV-002 (reviewer C): "St. Ostra" is found as written, and a distinct place named
    "Halden Bay City" is that place, never the city."""
    extra = _line(
        "9000020", "St. Ostra", "St. Ostra", "", "60.2", "5.3", "P", "PPL", "XN", "",
        "01", "", "", "", "20000", "", "5", "Etc/UTC", "2026-01-01",
    ) + _line(
        "9000021", "Halden Bay City", "Halden Bay City", "", "61.9", "5.2", "P", "PPL", "XN",
        "", "02", "", "", "", "30000", "", "5", "Etc/UTC", "2026-01-01",
    )  # fmt: skip
    await _sync_gazetteer(relational, PLACE + extra)

    saint = await relational.reference.places_named(lookup_names("St. Ostra"), "XN")
    assert [r["gazetteer_id"] for r in saint] == ["9000020"]
    city_named = await relational.reference.places_named(lookup_names("Halden Bay City"), "XN")
    assert {r["gazetteer_id"] for r in city_named} == {"9000021", "9000001"}
    assert {r["admin1_code"] for r in city_named} == {"01", "02"}
