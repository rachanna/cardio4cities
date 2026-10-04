"""FactCards and the brief's rules (D3-1; LLD-4 §2.1, LLD-2 §16): AT-13 and AT-14 at card
level, the summary keeps High and Medium only (HD-08), and "handle with care" shows both
sides of a disagreement. Fictional Halden Bay, Norvania."""

from datetime import UTC, date, datetime

from app.domain.cards import fact_card, handle_with_care, slot_row, summary
from app.domain.models import Relation, SourceRef, StoredFact, Verdict
from app.domain.vocab import ClaimStatus, PublisherClass, RelationType
from tests.unit.builders import badge_params, claim, confidence_params, slot

TODAY = date(2026, 10, 4)
S03 = slot("S03")


def stored(
    claim_id: str = "clm_a", publisher: str = "government", **overrides: object
) -> StoredFact:
    c = claim(claim_id, **overrides)
    return StoredFact(
        claim=c,
        value_as_written="31.2%",
        verdict=Verdict(
            claim_id=claim_id,
            label="supported",
            rationale="Stated.",
            scope_verified=True,
            period_verified=True,
            verifier_model="m",
            verifier_family="openai",
            prompt_version="checker@v4",
        ),
        source=SourceRef(
            source_id=c.source_id,
            url="https://health.halden-bay.test/survey",
            title="Survey",
            publisher_class=PublisherClass(publisher),
            published_date=None,
            retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )


def card(fact: StoredFact):  # type: ignore[no-untyped-def]
    return fact_card(fact, slot(fact.claim.slot_id), TODAY, badge_params(), confidence_params())


def test_a_national_figure_is_flagged_not_city_level_and_worded_national() -> None:
    """AT-13 (card level): the national flag is visible on the figure itself."""
    c = card(stored(labels={"geography_level": "national", "geography_name": "Norvania"}))
    assert c.main_badge is not None
    assert (c.main_badge.code, c.main_badge.label) == ("not_city_level", "Not city-level")
    assert (c.geography.level_word, c.geography.name) == ("national", "Norvania")


def test_a_wider_area_slot_says_no_city_figure_was_found() -> None:
    """AT-13: the slot's row states that no city figure was found."""
    result = {
        "status": "answered_wider_geo",
        "gap_note": "No city-level figure found. Best available is national (Norvania, 2021).",
        "best_claim_ids": ["clm_a"],
        "queries_tried": ["q1", "q2"],
        "sources_checked": ["s1"],
        "replans_used": 1,
    }
    row = slot_row(result, S03)
    assert row.status_word == "Wider area only"
    assert row.gap_note is not None
    assert row.gap_note.startswith("No city-level figure found")
    assert (row.queries, row.sources) == (2, 1)


def test_a_sub_population_figure_shows_its_population_and_is_flagged() -> None:
    """AT-14: a sub-population figure, with its population and period, flagged."""
    c = card(stored(labels={"population_group": "factory workers", "population_subgroup": True}))
    assert c.population.group == "factory workers"
    assert c.population.subgroup is True
    assert (c.population.age_min, c.population.age_max) == (30, 79)
    assert c.period.end == "2024"
    assert c.main_badge is not None
    assert c.main_badge.code == "not_city_level"


def test_a_stale_figure_shows_its_period_and_is_flagged_outdated() -> None:
    """AT-14: a stale figure, with its reference period, flagged."""
    c = card(
        stored(labels={"reference_start": date(2012, 1, 1), "reference_end": date(2012, 12, 31)})
    )
    assert (c.period.start, c.period.end, c.period.stated) == ("2012", "2012", True)
    assert c.main_badge is not None
    assert c.main_badge.code == "outdated"


def test_the_summary_keeps_each_slot_s_best_high_or_medium_fact() -> None:
    """HD-08: a Low-confidence fact never reaches the summary."""
    good = card(stored("clm_good"))
    low = card(stored("clm_low", publisher="other", labels={
        "representativeness": "non_representative", "geography_level": "national",
        "reference_start": None, "reference_end": None, "denominator_stated": False,
    }))  # fmt: skip
    assert low.confidence is not None
    assert low.confidence.label == "low"
    rows = [
        slot_row({"status": "answered", "best_claim_ids": ["clm_low", "clm_good"]}, S03),
        slot_row({"status": "answered", "best_claim_ids": ["clm_low"]}, slot("S05")),
    ]
    by_dimension = summary(rows, {"clm_good": good, "clm_low": low})
    assert [[c.claim_id for c in cards] for cards in by_dimension.values()] == [["clm_good"]]


def test_both_sides_of_a_disagreement_are_handled_with_care_together() -> None:
    a = stored("clm_a", status=ClaimStatus.CONTESTED)
    b = stored("clm_b", status=ClaimStatus.CONTESTED)
    cards = {f.claim.claim_id: card(f) for f in (a, b)}
    care = handle_with_care([], [a, b], cards, [("clm_a", "clm_b")])
    assert {(i.card.claim_id, i.reason) for i in care} == {
        ("clm_a", "Sources disagree"), ("clm_b", "Sources disagree"),
    }  # fmt: skip


def test_a_leader_named_by_one_source_is_handled_with_care() -> None:
    lead = stored(
        "clm_lead", slot_id="S12", kind="relation", labels={"measure_type": "qualitative"}
    )
    lead = lead.model_copy(update={"relation": Relation(
        claim_id="clm_lead", subject_entity_id="ent_p", relation_type=RelationType.LEADS,
        object_entity_id="ent_o", valid_from=None, valid_to=None,
    )})  # fmt: skip
    care = handle_with_care([], [lead], {"clm_lead": card(lead)}, [])
    assert [(i.card.claim_id, i.reason) for i in care] == [
        ("clm_lead", "Who leads it rests on a single source")
    ]
