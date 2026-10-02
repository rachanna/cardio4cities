"""Reference-file parsing (no database). Gazetteer lines are fictional (Halden Bay, Norvania)."""

import shutil
from pathlib import Path

import pytest
import yaml

from app.domain.models import SlotDef
from scripts.reference import load_yaml_reference
from scripts.reference.geonames import (
    build_gazetteer,
    iso639_1,
    large_place_names,
    parse_admin1,
    parse_places,
)
from scripts.reference.yaml_reference import (
    REFERENCE_DIR,
    ReferenceError,
    read_indicators,
    read_slots,
    read_sources,
)

CITY = "\t".join([
    "9000001", "Halden Bay", "Halden Bay", "Haldenbukt", "60.1", "5.2", "P", "PPLC", "XN", "",
    "01", "", "", "", "420000", "", "5", "Europe/Oslo", "2026-01-01",
])  # fmt: skip
TOWN = "\t".join([
    "9000002", "Port Ostra", "Port Ostra", "", "61.0", "6.0", "P", "PPL", "XN", "",
    "", "", "", "", "", "", "5", "", "2026-01-01",
])  # fmt: skip
COUNTRY = (
    "XN\tXNV\t999\tXN\tNorvania\tHalden Bay\t1\t1\tEU\t.xn\tNVK\tKrona\t99\t\t\tnv-XN,en,nor\t1\t\t"
)


# --- GeoNames ---------------------------------------------------------------


def test_iso639_1_keeps_two_letter_codes_in_order() -> None:
    assert iso639_1("en-US,es-US,haw,fr,en") == ["en", "es", "fr"]
    assert iso639_1("") == []


def test_parse_places_maps_columns_and_empty_fields() -> None:
    city, town = parse_places(f"{CITY}\n{TOWN}\n")

    assert city == (
        "9000001", "Halden Bay", "Halden Bay", ["Haldenbukt"], "XN", "01", None, 420000,
        60.1, 5.2, "Europe/Oslo",
    )  # fmt: skip
    assert (town[3], town[5], town[7], town[10]) == ([], None, None, None)


def test_parse_admin1_splits_country_and_code() -> None:
    assert parse_admin1("XN.01\tWest Coast\tWest Coast\t11\n") == [("XN", "01", "West Coast")]


def test_rows_with_unknown_country_are_skipped_and_counted() -> None:
    other = CITY.replace("\tXN\t", "\tXQ\t", 1)

    gazetteer = build_gazetteer("# comment\n" + COUNTRY, "XQ.01\tNowhere\tNowhere\t1\n", other)

    assert gazetteer.places == []
    assert gazetteer.admin1 == []
    assert (gazetteer.skipped_places, gazetteer.skipped_admin1) == (1, 1)
    assert gazetteer.countries == [("XN", "XNV", "Norvania", ["nv", "en"])]


def test_large_place_names_uses_population_threshold() -> None:
    assert large_place_names(f"{CITY}\n{TOWN}\n", 300_000) == {"Halden Bay"}


# --- YAML reference ---------------------------------------------------------


def test_shipped_slots_are_s01_to_s16_with_s04_headline() -> None:
    slots = read_slots()

    assert [s.slot_id for s in slots] == [f"S{n:02d}" for n in range(1, 17)]
    assert [s.slot_id for s in slots if s.headline] == ["S04"]
    assert all(s.short_label for s in slots)


def test_slot_kind_must_match_its_targets() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        SlotDef(
            slot_id="S03", dimension="D2", question="q", short_label="l",
            answer_kind="statistic", indicator_codes=[], relation_types=["GOVERNS"],
            headline=False, accepted_levels=["city_wide"],
        )  # fmt: skip


def _copy_reference(tmp_path: Path) -> Path:
    for name in ("slots.yaml", "indicators.yaml", "sources.yaml"):
        shutil.copy(REFERENCE_DIR / name, tmp_path / name)
    return tmp_path


def test_missing_slot_refused(tmp_path: Path) -> None:
    directory = _copy_reference(tmp_path)
    slots = yaml.safe_load((directory / "slots.yaml").read_text(encoding="utf-8"))
    (directory / "slots.yaml").write_text(yaml.safe_dump(slots[:-1]), encoding="utf-8")

    with pytest.raises(ReferenceError, match="exactly S01-S16"):
        read_slots(directory)


def test_invalid_level_reported_as_reference_error(tmp_path: Path) -> None:
    directory = _copy_reference(tmp_path)
    slots = yaml.safe_load((directory / "slots.yaml").read_text(encoding="utf-8"))
    slots[0]["accepted_levels"] = ["citywide"]
    (directory / "slots.yaml").write_text(yaml.safe_dump(slots), encoding="utf-8")

    with pytest.raises(ReferenceError, match=r"slots\.yaml"):
        read_slots(directory)


def test_sources_with_placeholders_are_pending_not_ready() -> None:
    sources = read_sources(REFERENCE_DIR, {i.code for i in read_indicators()})

    assert [s.provider for s in sources.ready] == ["world_bank"]
    assert set(sources.pending) == {"who_gho", "dhs"}
    assert sources.ready[0].config["indicators"]["POP_TOTAL"]["code"] == "SP.POP.TOTL"


def test_source_with_unknown_indicator_refused() -> None:
    with pytest.raises(ReferenceError, match="unknown indicators"):
        read_sources(REFERENCE_DIR, {"POP_TOTAL"})


def test_strict_load_refuses_placeholders_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert load_yaml_reference.main(["--strict"]) == 1
    assert "placeholder indicator codes" in capsys.readouterr().err
