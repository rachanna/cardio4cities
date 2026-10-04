"""Entity resolution (LLD-2 §6, R-43, AT-26) with an in-memory entity store and
deterministic embeddings. Fictional organisations and people only."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.domain.models import CityIdentity, Entity
from app.domain.params import EntityParams
from app.domain.vocab import EntityType
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.entities import EntityResolver
from app.workflow.rules.entity_resolution import (
    acronym_fits,
    acronym_pairs,
    is_acronym,
    is_candidate,
    is_generic,
    normalized_key,
    word_set_key,
)

CITY = "city_hb"
PARAMS = EntityParams(candidate_threshold=0.85)


@dataclass
class MemoryEntities:
    by_id: dict[str, Entity] = field(default_factory=dict)
    aliases: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)

    async def alias(self, city_id: str, surface_form: str) -> str | None:
        hit = self.aliases.get((city_id, surface_form))
        return hit[0] if hit else None

    async def by_key(self, city_id: str, entity_type: str, normalized_key: str) -> str | None:
        return next(
            (
                e.entity_id
                for e in self.by_id.values()
                if (e.city_id, e.entity_type.value, e.normalized_key)
                == (city_id, entity_type, normalized_key)
            ),
            None,
        )

    async def add_entity(self, entity: Entity) -> str:
        found = await self.by_key(entity.city_id, entity.entity_type.value, entity.normalized_key)
        if found:
            return found
        self.by_id[entity.entity_id] = entity
        return entity.entity_id

    async def add_alias(
        self, city_id: str, surface_form: str, entity_id: str, method: str, score: float | None
    ) -> None:
        self.aliases.setdefault((city_id, surface_form), (entity_id, method))

    async def entities(self, city_id: str, entity_type: str) -> list[Entity]:
        return [
            e
            for e in self.by_id.values()
            if e.city_id == city_id and e.entity_type.value == entity_type
        ]

    async def get(self, entity_ids: list[str]) -> dict[str, Entity]:
        return {i: self.by_id[i] for i in entity_ids if i in self.by_id}

    async def match_names(
        self, city_id: str, texts: list[str], keys: list[str], min_similarity: float
    ) -> list[str]:
        return []  # question answering's lookup (D3-2); resolution never reads it

    async def names(self, city_id: str) -> list[tuple[str, str]]:
        return []

    async def with_fact_counts(self, city_id: str) -> list[tuple[Entity, int]]:
        return []  # the read API's query (D3-1); resolution never reads it

    async def update_attributes(self, entity_id: str, change: Any) -> dict[str, Any] | None:
        old = self.by_id[entity_id]
        update = change(dict(old.attributes))
        if update is None:
            return None
        await self.merge_attributes(entity_id, update)
        return dict(self.by_id[entity_id].attributes)

    async def merge_attributes(self, entity_id: str, attributes: dict[str, Any]) -> None:
        old = self.by_id[entity_id]
        self.by_id[entity_id] = old.model_copy(
            update={"attributes": {**old.attributes, **attributes}}
        )


class LetterEmbeddings:
    """Vectors from letter counts: near-identical names score near 1."""

    dimension = 26
    key = "letters"
    calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(t.casefold().count(chr(97 + i))) for i in range(26)] for t in texts]


def resolver() -> tuple[EntityResolver, MemoryEntities]:
    repo = MemoryEntities()
    ledger = BudgetLedger(BudgetLimits(300, 10, 10, 0, 0, 0.85))
    return EntityResolver(repo, LetterEmbeddings(), ledger, PARAMS), repo


SOURCE = "In 2024 the Norvania Health Directorate (NHD) took over coastal clinics."


async def test_full_name_acronym_and_the_form_resolve_to_one_entity() -> None:
    """AT-26: alias forms of one organisation resolve to one entity."""
    r, repo = resolver()
    acronyms = acronym_pairs(SOURCE)
    first = await r.resolve(CITY, "Norvania Health Directorate", EntityType.ORGANIZATION, acronyms)
    assert await r.resolve(CITY, "NHD", EntityType.ORGANIZATION, acronyms) == first
    assert (
        await r.resolve(CITY, "the Norvania Health Directorate", EntityType.ORGANIZATION) == first
    )
    # once registered, the acronym resolves in a source that does not define it
    assert await r.resolve(CITY, "NHD", EntityType.ORGANIZATION) == first
    assert len(repo.by_id) == 1
    assert repo.aliases[(CITY, "NHD")][1] == "acronym"


async def test_acronym_first_then_long_form_is_still_one_entity() -> None:
    r, repo = resolver()
    acronyms = acronym_pairs(SOURCE)
    via_acronym = await r.resolve(CITY, "NHD", EntityType.ORGANIZATION, acronyms)
    assert repo.by_id[via_acronym].canonical_name == "Norvania Health Directorate"
    assert (
        await r.resolve(CITY, "Norvania Health Directorate", EntityType.ORGANIZATION) == via_acronym
    )


async def test_people_with_similar_names_stay_separate() -> None:
    """AT-26: no embedding merge for people."""
    r, repo = resolver()
    a = await r.resolve(CITY, "Ines Marlow", EntityType.PERSON)
    b = await r.resolve(CITY, "Ines Marlowe", EntityType.PERSON)
    assert a != b
    assert len(repo.by_id) == 2


async def test_the_same_words_in_another_order_are_one_organisation() -> None:
    """BD-24: the word-set match replaces the embedding merge."""
    r, repo = resolver()
    a = await r.resolve(CITY, "Norvania Health Directorate", EntityType.ORGANIZATION)
    b = await r.resolve(CITY, "Health Directorate of Norvania", EntityType.ORGANIZATION)
    assert a == b
    assert repo.aliases[(CITY, "Health Directorate of Norvania")][1] == "normalized"


async def test_close_names_of_different_bodies_never_merge() -> None:
    """RV-008: "City Council" and "District Council" scored 0.95 and merged. Embedding
    similarity now only logs a pair for review (owner, BD-24)."""
    r, repo = resolver()
    city = await r.resolve(CITY, "Halden Bay City Council", EntityType.ORGANIZATION)
    district = await r.resolve(CITY, "Halden Bay District Council", EntityType.ORGANIZATION)
    assert city != district
    assert len(repo.by_id) == 2
    assert [(c[0], c[1]) for c in r.candidates] == [(city, CITY)]  # logged for review


async def test_a_place_named_greater_x_is_not_the_city() -> None:
    """RV-008: a metro figure's edge must not land on the city."""
    r, _ = resolver()
    city = await r.resolve(CITY, "Halden Bay", EntityType.PLACE)
    assert await r.resolve(CITY, "Greater Halden Bay", EntityType.PLACE) != city


async def test_a_generic_name_joins_only_within_its_own_source() -> None:
    """RV-025 (owner, BD-24): a city's and a state's "Department of Health" stay apart;
    repeated mentions in one source are one entity; no city-wide alias is registered."""
    r, repo = resolver()
    org = EntityType.ORGANIZATION
    a1 = await r.resolve(CITY, "Department of Health", org, source_id="src_a")
    a2 = await r.resolve(CITY, "the Department of Health", org, source_id="src_a")
    b = await r.resolve(CITY, "Department of Health", org, source_id="src_b")
    assert a1 == a2
    assert a1 != b
    assert (CITY, "Department of Health") not in repo.aliases


async def test_an_acronym_this_source_defines_beats_another_sources_alias() -> None:
    """RV-025: source B defines NHC as another body; B's NHC is that body."""
    r, _ = resolver()
    org = EntityType.ORGANIZATION
    first = await r.resolve(CITY, "NHC", org, {"NHC": "Norvania Heart Council"}, "src_a")
    second = await r.resolve(CITY, "NHC", org, {"NHC": "Northern Hospitals Consortium"}, "src_b")
    assert first != second
    assert await r.resolve(CITY, "Northern Hospitals Consortium", org) == second
    # a source that does not define it still finds the alias the first source registered
    assert await r.resolve(CITY, "NHC", org) == first


async def test_same_name_of_another_type_is_another_entity() -> None:
    r, _ = resolver()
    place = await r.resolve(CITY, "Halden Bay", EntityType.PLACE)
    programme = await r.resolve(CITY, "Halden Bay", EntityType.PROGRAMME)
    assert place != programme


async def test_city_entity_is_created_once_across_runs() -> None:
    r, repo = resolver()
    city = CityIdentity(
        city_id=CITY,
        gazetteer_id="9000001",
        name="Halden Bay",
        ascii_name="Halden Bay",
        country_iso2="XN",
        country_iso3="XNV",
        country_name="Norvania",
        admin1_code="01",
        admin1_name="West Coast",
        admin2_name=None,
        population=420000,
        lat=60.1,
        lon=5.2,
        languages=["nv", "en"],
    )
    first = await r.ensure_city(city)
    assert await r.ensure_city(city) == first
    assert await r.resolve(CITY, "Halden Bay", EntityType.PLACE) == first
    assert len(repo.by_id) == 1


# --- pure rules ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("surface", "key"),
    [
        ("The Norvania Health Directorate", "norvania-health-directorate"),
        ("Norvania  Health-Directorate", "norvania-health-directorate"),
        ("Bureau de Santé", "bureau-de-sante"),
        ("Halden Bay" + chr(0x2019) + "s Office", "halden-bay-s-office"),  # typographic apostrophe
    ],
)
def test_normalized_key(surface: str, key: str) -> None:
    assert normalized_key(surface) == key


def test_acronym_pairs_need_initials_that_fit() -> None:
    text = (
        "The World Health Organization (WHO) agreed. HBHO (Halden Bay Health Office) runs it."
        " The Big Plan (XYZ) failed."
    )
    assert acronym_pairs(text) == {
        "WHO": "World Health Organization",
        "HBHO": "Halden Bay Health Office",
    }
    assert acronym_fits("Norvania Health Directorate", "NHD")
    assert not acronym_fits("Norvania Health Directorate", "NHS")
    assert is_acronym("NHD")
    assert not is_acronym("Nhd")


def test_an_acronym_defined_two_ways_is_not_trusted() -> None:
    text = "Norvania Heart Directorate (NHD) and Northern Health Department (NHD)."
    assert acronym_pairs(text) == {}


@pytest.mark.parametrize(("score", "candidate"), [(0.97, True), (0.85, True), (0.84, False)])
def test_a_close_pair_is_only_a_candidate(score: float, candidate: bool) -> None:
    assert is_candidate(score, PARAMS) is candidate


def test_word_set_keys() -> None:
    assert word_set_key("Health Directorate of Norvania") == word_set_key(
        "the Norvania Health Directorate"
    )
    assert word_set_key("Halden Bay City Council") != word_set_key("Halden Bay District Council")
    assert word_set_key("North Coast Office") != word_set_key("South Coast Office")


@pytest.mark.parametrize(
    ("name", "generic"),
    [("Department of Health", True), ("City Council", True), ("Ministry of Health", True),
     ("National Hypertension Control Programme", True), ("Norvania Health Directorate", False),
     ("Halden Bay City Council", False), ("Healthy Hearts Halden Bay", False)],
)  # fmt: skip
def test_generic_names(name: str, generic: bool) -> None:
    assert is_generic(name) is generic
