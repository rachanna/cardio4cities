"""Question answering's pure rules (D3-2; LLD-5 §3, §5-§9): understanding, re-validation
(AT-39), fusion, anchors (AT-40), bundle assembly, and the post-check (AT-15, AT-28,
AT-41, AT-45, AT-13/AT-14 for answers). Fictional Halden Bay, Norvania."""

from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

from app.domain.cards import fact_card
from app.domain.models import Relation, SourceRef, StoredFact, Verdict
from app.domain.vocab import ClaimStatus, PublisherClass, RelationType
from app.prompts.answerer.schema import AnswerSentence
from app.prompts.classifier.schema import ClassifierOutput
from app.query.bundle import assemble
from app.query.fuse import anchor, fuse
from app.query.postcheck import Context, Evidence, check
from app.query.revalidate import revalidate
from app.query.routes.keyword import keywords
from app.query.types import AskParams, Mention, Understanding
from app.query.understand import merge, parse_as_of, validate
from tests.unit.builders import badge_params, claim, confidence_params, slot

TODAY = date(2026, 10, 4)
SLOTS = {s: slot(s) for s in ("S03", "S04", "S05")}
PARAMS = AskParams(
    rrf_k=60,
    r2_top=20,
    r2_trigram_min=0.4,
    r3_top=20,
    r3_mentions_top=5,
    max_facts=8,
    max_mentions=4,
    max_per_slot=2,
    mentions_only_if_facts_below=3,
)


def stored(
    claim_id: str,
    slot_id: str = "S03",
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    verdict: str | None = "supported",
    value: str = "31.2%",
    run_id: str = "run_1",
    publisher: str = "government",
    **overrides: Any,
) -> StoredFact:
    c = claim(claim_id, slot_id=slot_id, status=status, run_id=run_id, **overrides)
    return StoredFact(
        claim=c,
        value_as_written=value,
        verdict=Verdict(
            claim_id=claim_id,
            label=verdict,
            rationale="Stated.",
            scope_verified=True,
            period_verified=True,
            verifier_model="m",
            verifier_family="openai",
            prompt_version="checker@v4",
        )
        if verdict
        else None,
        source=SourceRef(
            source_id=c.source_id,
            url="https://health.halden-bay.test/survey",
            title="Halden Bay Heart Survey",
            publisher_class=PublisherClass(publisher),
            published_date=None,
            retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )


def understanding(**overrides: Any) -> Understanding:
    values: dict[str, Any] = {
        "question_type": "figure",
        "slot_ids": ("S03",),
        "indicator_codes": (),
        "entity_mentions": (),
        "as_of": None,
        "sub_questions": (),
        "refers_to_previous": False,
    }
    values.update(overrides)
    return Understanding(**values)


# --- understanding (LLD-5 §3) ----------------------------------------------------------------


def test_unknown_slots_and_indicators_are_dropped_and_the_date_parsed() -> None:
    out = ClassifierOutput(
        question_type="figure",
        slot_ids=["S03", "S99", "S03"],
        indicator_codes=["HTN_PREV", "X"],
        entity_mentions=[],
        as_of="2023-02",
        sub_questions=["a", "b", "c"],
        refers_to_previous=False,
    )
    u = validate(out, ["S03", "S04"], ["HTN_PREV"])
    assert (u.slot_ids, u.indicator_codes, u.as_of) == (("S03",), ("HTN_PREV",), date(2023, 2, 28))
    assert parse_as_of("2023") == date(2023, 12, 31)
    assert parse_as_of("last spring") is None


def test_a_follow_up_takes_the_previous_turn_s_slots_when_it_names_none() -> None:
    """AT-44 (merge rule): "and nationally?" after a question on S03 retrieves S03."""
    follow_up = understanding(question_type="out_of_scope", slot_ids=(), refers_to_previous=True)
    previous = {
        "question_type": "figure",
        "slot_ids": ["S03"],
        "indicator_codes": [],
        "entity_mentions": [],
    }
    merged = merge(follow_up, previous)
    assert merged.slot_ids == ("S03",)
    assert merged.merged_from_previous == ("S03",)
    assert merged.question_type == "figure"  # in scope after all
    assert merge(understanding(slot_ids=("S05",), refers_to_previous=True), previous).slot_ids == (
        "S05",
    )


def test_keyword_words_leave_out_stop_words_and_the_city_name() -> None:
    words = keywords(
        "What is the STEPS hypertension rate in Halden Bay?",
        frozenset({"what", "is", "the", "in"}),
        ["Halden Bay"],
    )
    assert words == ["steps", "hypertension", "rate"]


# --- re-validation (LLD-5 §5; AT-39) ----------------------------------------------------------


def test_only_confirmed_claims_of_the_city_s_latest_run_survive() -> None:
    """AT-39: a refuted claim a stale index still calls supported never gets through."""
    facts = {
        "clm_ok": stored("clm_ok"),
        "clm_refuted": stored("clm_refuted", status=ClaimStatus.REFUTED, verdict="refuted"),
        "clm_old_run": stored("clm_old_run", run_id="run_0"),
        "clm_superseded": stored("clm_superseded", status=ClaimStatus.SUPERSEDED),
        "clm_no_verdict": stored("clm_no_verdict", verdict=None),
    }
    kept, removed = revalidate([*facts, "clm_ghost"], facts, understanding(), "city_hb", "run_1")
    assert kept == ["clm_ok"]
    assert removed == Counter(
        {"refuted": 1, "other_run": 1, "superseded": 1, "no_supported_verdict": 1, "not_stored": 1}
    )


def test_superseded_claims_count_for_change_questions_and_dates_cut_by_time() -> None:
    facts = {
        "clm_old": stored("clm_old", status=ClaimStatus.SUPERSEDED),
        "clm_late": stored(
            "clm_late",
            labels={"reference_start": date(2025, 1, 1), "reference_end": date(2025, 12, 31)},
        ),
    }
    kept, _ = revalidate(
        facts, facts, understanding(question_type="change_over_time"), "city_hb", "run_1"
    )
    assert kept == ["clm_old", "clm_late"]
    kept, removed = revalidate(
        facts, facts, understanding(as_of=date(2024, 6, 30)), "city_hb", "run_1"
    )
    assert kept == ["clm_old"]
    assert removed["out_of_time"] == 1


# --- fusion, anchors and the bundle (LLD-5 §6-§7; AT-40) ---------------------------------------


def test_fusion_adds_reciprocal_ranks_and_breaks_ties_by_trust() -> None:
    facts = {c: stored(c, publisher=p) for c, p in (("clm_a", "news"), ("clm_b", "government"))}
    fused = fuse({"R2": ["clm_a"], "R3": ["clm_b"]}, ["clm_a", "clm_b"], facts, SLOTS, 60)
    assert [c for c, _ in fused] == ["clm_b", "clm_a"]  # same score: the government source first
    fused = fuse({"R1": ["clm_a"], "R2": ["clm_a", "clm_b"]}, ["clm_a", "clm_b"], facts, SLOTS, 60)
    assert fused[0] == ("clm_a", round(2 / 61, 6))


def test_a_slot_s_best_claim_is_anchored_when_no_route_found_it() -> None:
    """AT-40: the recall guarantee, independent of how the search did."""
    results = {
        "S03": {"status": "answered", "best_claim_ids": ["clm_best"]},
        "S05": {
            "status": "answered_negative",
            "best_claim_ids": [],
            "gap_note": "Searched 6 queries.",
        },
    }
    anchors = anchor(["S03", "S05"], results, found=[], valid={"clm_best"})
    assert anchors.injected == ["clm_best"]
    assert list(anchors.gaps) == ["S05"]
    facts = {"clm_best": stored("clm_best")}
    bundle = assemble(understanding(), [], anchors.injected, {"clm_best"}, facts, [], [], PARAMS)
    assert bundle.facts == ["clm_best"]


def test_contested_partners_travel_together_and_slots_are_capped() -> None:
    facts = {c: stored(c) for c in ("clm_1", "clm_2", "clm_3", "clm_x")}
    fused = [("clm_1", 0.03), ("clm_2", 0.02), ("clm_3", 0.01)]
    bundle = assemble(
        understanding(), fused, [], set(facts), facts, [("clm_3", "clm_x")], [], PARAMS
    )
    assert bundle.facts == ["clm_1", "clm_2"]  # two per slot; the pair is not split
    fused = [("clm_3", 0.03), ("clm_1", 0.02)]
    bundle = assemble(
        understanding(), fused, [], set(facts), facts, [("clm_3", "clm_x")], [], PARAMS
    )
    assert bundle.facts[:2] == ["clm_3", "clm_x"]  # the partner right after, whatever its score
    assert bundle.partners == {"clm_3": "clm_x", "clm_x": "clm_3"}


def test_mentions_only_for_open_questions_with_few_facts() -> None:
    mention = Mention("src_1", 0, 50, "Screening camps were reported.", "news")
    open_q = assemble(understanding(question_type="open"), [], [], set(), {}, [], [mention], PARAMS)
    figure = assemble(understanding(), [], [], set(), {}, [], [mention], PARAMS)
    assert (open_q.mentions, figure.mentions) == ([mention], [])


# --- the post-check (LLD-5 §9) -------------------------------------------------------------------


def evidence(*facts: StoredFact, names: tuple[str, ...] = ()) -> dict[str, Evidence]:
    return {
        f.claim.claim_id: Evidence(
            f,
            fact_card(f, SLOTS[f.claim.slot_id], TODAY, badge_params(), confidence_params()),
            names,
        )
        for f in facts
    }


def ctx(asked: tuple[str, ...] = ("S03",), results: dict[str, Any] | None = None) -> Context:
    return Context(
        city_name="Halden Bay",
        other_names=("Norvania",),
        question="What share of adults have hypertension?",
        asked=asked,
        slots=SLOTS,
        results=results or {},
        unavailable={},
    )


def say(
    text: str, refs: list[str], kind: str = "fact", slot_id: str | None = "S03"
) -> AnswerSentence:
    return AnswerSentence(text=text, refs=refs, kind=kind, slot_id=slot_id)


def test_a_number_not_in_the_cited_evidence_is_removed_for_an_abstention() -> None:
    """AT-28."""
    ev = evidence(stored("clm_a", value="31.2%"))
    out = check(
        [say("In Halden Bay, 34.0% of adults had hypertension.", ["clm_a"])],
        ev,
        set(),
        {},
        ctx(results={"S03": {"status": "answered", "gap_note": None}}),
    )
    assert out.removed[0]["check"] == 2
    texts = [s.text for s in out.sentences]
    assert not any("34.0" in t for t in texts)
    assert out.first_pass_survival == 0.0


def test_a_sentence_citing_nothing_in_the_bundle_is_removed() -> None:
    ev = evidence(stored("clm_a"))
    out = check([say("Hypertension is common.", ["clm_other"])], ev, set(), {}, ctx())
    assert out.removed[0]["check"] == 1


def test_an_invented_name_is_removed() -> None:
    """AT-45 and AT-15: a person absent from the evidence is never named."""
    ev = evidence(stored("clm_a"))
    out = check(
        [
            say(
                "Dr Mira Solberg leads the Halden Bay programme,"
                " where 31.2% of adults had hypertension.",
                ["clm_a"],
            )
        ],
        ev,
        set(),
        {},
        ctx(),
    )
    assert out.removed[0]["check"] == 4
    assert not any("Solberg" in s.text for s in out.sentences)


def test_a_wider_area_figure_stated_for_the_city_needs_its_level() -> None:
    """AT-13 for answers: a national figure about the city says it is national."""
    national = stored("clm_n", labels={"geography_level": "national", "geography_name": "Norvania"})
    ev = evidence(national)
    bad = check(
        [say("In Halden Bay, 31.2% of adults had hypertension.", ["clm_n"])], ev, set(), {}, ctx()
    )
    assert bad.removed[0]["check"] == 3
    good = check(
        [
            say(
                "No city-level figure was found for Halden Bay;"
                " nationally, 31.2% of adults had hypertension.",
                ["clm_n"],
            )
        ],
        ev,
        set(),
        {},
        ctx(),
    )
    assert good.removed == []
    assert good.sentences[0].main_badge is not None
    assert good.sentences[0].main_badge.code == "not_city_level"


def test_one_side_of_a_disagreement_is_repaired_into_both() -> None:
    """AT-41: citing one side of a contested pair yields both sides in the answer."""
    a = stored("clm_a", status=ClaimStatus.CONTESTED, value="31.2%")
    b = stored("clm_b", status=ClaimStatus.CONTESTED, value="27.0%")
    ev = evidence(a, b)
    out = check(
        [say("In Halden Bay, 31.2% of adults had hypertension.", ["clm_a"])],
        ev,
        set(),
        {"clm_a": "clm_b", "clm_b": "clm_a"},
        ctx(),
    )
    (sentence,) = out.sentences
    assert sentence.text.startswith(
        "Sources disagree: 31.2% (Halden Bay Heart Survey, 2024) and 27.0%"
    )
    assert sentence.refs == ["clm_a", "clm_b"]
    assert sentence.status_word == "Sources disagree"
    assert out.repaired == [{"check": 5, "claims": ["clm_a", "clm_b"]}]


def test_an_outdated_figure_gets_its_year() -> None:
    """AT-14 for answers: a stale figure is shown with its reference period."""
    old = stored(
        "clm_old", labels={"reference_start": date(2012, 1, 1), "reference_end": date(2012, 12, 31)}
    )
    out = check(
        [say("In Halden Bay, 31.2% of adults had hypertension.", ["clm_old"])],
        evidence(old),
        set(),
        {},
        ctx(),
    )
    assert out.sentences[0].text.endswith("(as of 2012).")
    assert out.sentences[0].main_badge is not None
    assert out.sentences[0].main_badge.code == "outdated"


def test_a_slot_asked_about_is_always_covered() -> None:
    """Check 7: an asked slot without a sentence gets its stored fact, or its gap."""
    ev = evidence(stored("clm_a"))
    results = {
        "S05": {"status": "answered_negative", "gap_note": "Searched 6 queries; nothing found."}
    }
    out = check([], ev, set(), {}, ctx(asked=("S03", "S05"), results=results))
    by_slot = {s.slot_id: s for s in out.sentences}
    assert by_slot["S03"].refs == ["clm_a"]
    assert by_slot["S03"].written_by == "code"
    assert by_slot["S05"].kind == "abstain"
    assert (
        by_slot["S05"].text
        == "No confirmed "
        + SLOTS["S05"].short_label
        + " for Halden Bay. Searched 6 queries; nothing found."
    )


def test_abstentions_use_the_stored_gap_and_mentions_must_say_unconfirmed() -> None:
    results = {"S03": {"status": "answered_negative", "gap_note": "Searched 6 queries."}}
    mention_ok = say(
        "A news report says screening camps ran, but this is not confirmed.",
        ["m:src_1:0"],
        "mention",
        None,
    )
    mention_bad = say("Screening camps ran.", ["m:src_1:0"], "mention", None)
    out = check(
        [say("I could not find it, sorry!", [], "abstain"), mention_ok, mention_bad],
        {},
        {"m:src_1:0"},
        {},
        ctx(results=results),
    )
    assert (
        out.sentences[0].text
        == "No confirmed " + SLOTS["S03"].short_label + " for Halden Bay. Searched 6 queries."
    )
    assert [s.kind for s in out.sentences] == ["abstain", "mention"]
    assert out.removed[0]["check"] == 8


def test_names_in_the_evidence_or_the_question_are_allowed() -> None:
    lead = stored(
        "clm_l",
        slot_id="S05",
        kind="relation",
        statement="The Halden Bay Health Office runs the HEARTS programme.",
        quote="the Halden Bay Health Office runs the HEARTS programme",
        labels={"measure_type": "qualitative"},
    )
    lead = lead.model_copy(
        update={
            "relation": Relation(
                claim_id="clm_l",
                subject_entity_id="ent_o",
                relation_type=RelationType.RUNS,
                object_entity_id="ent_p",
                valid_from=None,
                valid_to=None,
            )
        }
    )
    ev = evidence(lead, names=("Halden Bay Health Office", "HEARTS"))
    out = check(
        [say("The Halden Bay Health Office runs HEARTS in Halden Bay.", ["clm_l"], slot_id="S05")],
        ev,
        set(),
        {},
        ctx(asked=("S05",)),
    )
    assert out.removed == []
