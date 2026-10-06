"""What the brief and report show (D4-3): key findings stay on the brief's topics, a
world figure gives way to a narrower one, a fact found twice shows once with both
sources, coverage separates the city's own answers from national ones a question
accepts, and "Period not stated" marks figures only. Fictional Halden Bay, Norvania."""

from typing import Any

from app.api.reading import summary_topics, visible
from app.domain.cards import FactCard, fact_card, fold_repeats, hide_global, slot_row, summary
from app.domain.models import SlotDef, StoredFact
from app.report.assemble import Cited, Report, assemble
from app.report.render import caveats, refs
from tests.unit.builders import badge_params, confidence_params, slot
from tests.unit.test_cards import TODAY, stored

TOPICS = summary_topics()
NATIONAL = {"geography_level": "national", "geography_name": "Norvania"}
WORLD = {"geography_level": "global", "geography_name": "world"}
S09 = slot(
    "S09",
    dimension="D4",
    answer_kind="mixed",
    indicator_codes=[],
    relation_types=["APPLIES_TO"],
    accepted_levels=["city_wide", "national"],
)


def statement(claim_id: str, text: str, slot_id: str = "S09", **labels: str) -> StoredFact:
    return stored(
        claim_id,
        slot_id=slot_id,
        kind="statement",
        statement=text,
        labels={**NATIONAL, "measure_type": "qualitative", **labels},
    )


def cards_of(*facts: StoredFact, slots: dict[str, SlotDef] | None = None) -> dict[str, FactCard]:
    defs = slots or {}
    return {
        f.claim.claim_id: fact_card(
            f,
            defs.get(f.claim.slot_id) or slot(f.claim.slot_id),
            TODAY,
            badge_params(),
            confidence_params(),
        )
        for f in facts
    }


def one(fact: StoredFact, slots: dict[str, SlotDef] | None = None) -> FactCard:
    return cards_of(fact, slots=slots)[fact.claim.claim_id]


def test_the_summary_takes_only_facts_on_the_brief_s_topics() -> None:
    """A true but off-topic fact (a workforce plan for another field) stays under its
    question; the next fact on topic takes its place in the summary."""
    off = statement("clm_off", "The Norvania workforce plan aims to grow mental health staff.")
    on = statement("clm_on", "The Norvania tobacco law bans sales to anyone born after 2009.")
    cards = cards_of(off, on, slots={"S09": S09})
    row = slot_row({"status": "answered", "best_claim_ids": ["clm_off", "clm_on"]}, S09)
    assert [c.claim_id for c in summary([row], cards)["D4"]] == ["clm_off"]
    assert [c.claim_id for c in summary([row], cards, TOPICS)["D4"]] == ["clm_on"]


def test_who_governs_and_who_works_on_it_may_enter_the_summary_without_a_topic_word() -> None:
    leader = one(statement("clm_lead", "Ama Lind is the Director of Public Affairs.", "S12"))
    assert TOPICS.admits(leader, "D5")
    assert not TOPICS.admits(leader, "D4")


def test_topics_match_at_the_start_of_a_word_only() -> None:
    hypertensive = one(statement("clm_h", "Clinics treat hypertensive adults in Halden Bay."))
    inside = one(statement("clm_x", "The Halden Bay harbour wall is built of basalt."))
    assert TOPICS.admits(hypertensive, "D3")
    assert not TOPICS.admits(inside, "D3")  # "salt" inside "basalt" is not the topic


def test_a_world_figure_gives_way_to_a_narrower_one_unless_it_is_one_side_of_a_disagreement() -> (
    None
):
    world = statement("clm_world", "Heart disease causes most deaths in the world.", "S06", **WORLD)
    national = statement("clm_nat", "Heart disease caused 31% of deaths in Norvania.", "S06")
    alone = statement("clm_alone", "Stroke causes many deaths in the world.", "S08", **WORLD)
    cards = cards_of(world, national, alone)
    shown = [c.claim_id for c in hide_global(list(cards.values()))]
    assert shown == ["clm_nat", "clm_alone"]  # a question with only a world figure keeps it
    assert visible(cards, [("clm_world", "clm_nat")]) == {"clm_world", "clm_nat", "clm_alone"}


def test_a_fact_found_twice_shows_once_and_different_values_never_fold() -> None:
    text = "In Norvania 9.7% of adults will have diabetes by 2035."
    first = stored("clm_1", slot_id="S05", statement=text)
    copy = stored("clm_2", slot_id="S05", statement=text.replace(" 9.7", "  9.7"))
    other = stored("clm_3", slot_id="S05", statement=text).model_copy(
        update={"value_as_written": "9.9%"}
    )
    folded = fold_repeats(list(cards_of(first, copy, other).values()))
    assert [(c.claim_id, [r.claim_id for r in rs]) for c, rs in folded] == [
        ("clm_1", ["clm_2"]),
        ("clm_3", []),
    ]


def _report(facts: list[StoredFact], statuses: dict[str, str]) -> Report:
    slots = {"S03": slot("S03"), "S09": S09}
    cards = cards_of(*facts, slots=slots)
    rows = [
        slot_row(
            {
                "status": status,
                "best_claim_ids": [f.claim.claim_id for f in facts if f.claim.slot_id == sid],
            },
            slots[sid],
        )
        for sid, status in statuses.items()
    ]
    city = {"name": "Halden Bay", "country_name": "Norvania", "admin1_name": "West Coast"}
    run: dict[str, Any] = {"run_id": "run_1", "status": "completed", "summary": {}}
    return assemble(city, run, rows, facts, cards, [], slots, topics=TOPICS)


def test_coverage_separates_city_answers_from_national_ones_a_question_accepts() -> None:
    """A national plan answers a policy question by design; it is not a city-level answer."""
    city_figure = stored("clm_city", slot_id="S03")
    plan = statement("clm_plan", "Norvania's heart plan sets a hypertension control target.")
    totals = _report([city_figure, plan], {"S03": "answered", "S09": "answered"}).totals
    assert (totals.city_level, totals.national_applies) == (1, 1)


def test_a_repeat_cites_both_sources_in_the_report() -> None:
    first = stored("clm_1")
    copy = stored("clm_2", source_id="src_2")
    report = _report([first, copy], {"S03": "answered"})
    (block,) = [b for s in report.sections for b in s.slots if b.facts]
    (fact,) = block.facts
    assert refs(fact) == "[1][2]"


def test_period_not_stated_marks_figures_only() -> None:
    dated_by_publication = {"period_type": "publication_date_proxy"}
    figure = one(stored("clm_fig", labels=dated_by_publication))
    plan = one(statement("clm_plan", "Norvania has a heart plan.", **dated_by_publication))
    assert "Period not stated" in caveats(Cited(figure, 1))
    assert "Period not stated" not in caveats(Cited(plan, 2))
