"""The report's linking prose is checked like an answer (LLD-3 §8.5, HD-07; D3-3,
BD-40): only facts of its section, numbers and names from them, and a paragraph under
the minimum is omitted. Fictional Halden Bay, Norvania."""

from types import SimpleNamespace

from app.api.reporting import check_points, check_sentences
from app.domain.cards import fact_card
from app.query.postcheck import Context, Evidence
from tests.unit.builders import badge_params, confidence_params
from tests.unit.test_query_rules import SLOTS, TODAY, stored

CTX = Context("Halden Bay", ("Norvania",), "Burden", (), SLOTS, {}, {})
FACT = stored("clm_a", value="31.2%")
EVIDENCE = {
    "clm_a": Evidence(
        FACT, fact_card(FACT, SLOTS["S03"], TODAY, badge_params(), confidence_params())
    )
}
LONG = (
    "Hypertension figures for the city come from one household survey and are cited to it"
    " below in full, 31.2% of adults."
)


def say(text: str, refs: list[str], kind: str = "fact") -> SimpleNamespace:
    return SimpleNamespace(text=text, refs=refs, kind=kind)


def check(*sentences: SimpleNamespace, max_words: int = 120, min_words: int = 20) -> list[str]:
    return [p.text for p in check_sentences(sentences, EVIDENCE, "", CTX, max_words, min_words)]


def test_a_sentence_citing_a_fact_outside_its_section_is_dropped() -> None:
    assert check(say(LONG, ["clm_other"])) == []


def test_a_number_its_facts_do_not_hold_is_dropped() -> None:
    assert check(say(LONG.replace("31.2%", "45.0%"), ["clm_a"])) == []


def test_an_invented_name_is_dropped() -> None:
    assert check(say(LONG + " The Kestrel Heart Trust funds it.", ["clm_a"])) == []


def test_a_paragraph_under_the_minimum_is_omitted_and_one_over_the_limit_is_cut() -> None:
    assert check(say("Figures are cited below, 31.2% of adults.", ["clm_a"])) == []  # HD-07
    kept = check(say(LONG, ["clm_a"]), say(LONG, ["clm_a"]), max_words=25)
    assert kept == [LONG]


def test_analysis_points_must_rest_on_summary_facts() -> None:
    points = [
        SimpleNamespace(
            text="City figures exist, 31.2% of adults.", derived_from=["clm_a"], kind="opportunity"
        ),
        SimpleNamespace(
            text="Half the clinics lack staff.", derived_from=["clm_other"], kind="risk"
        ),
    ]
    assert [p.text for p in check_points(points, EVIDENCE, CTX, 5)] == [
        "City figures exist, 31.2% of adults."
    ]


def test_failed_steps_are_named_so_an_incomplete_run_is_not_read_as_an_empty_city() -> None:
    """D4-3: a run that lost steps says so on the cover and in the run details."""
    from app.report.render import counts, failed_steps

    summary = {"failed_steps": {"extract": 55, "fetch_parse": 1, "verify": 0}}
    assert failed_steps(summary) == "55 extraction steps, 1 page reading step"
    assert "Failed steps: 55 extraction steps, 1 page reading step" in counts(summary)
    assert failed_steps({"failed_steps": {"extract": 0}}) is None
    assert failed_steps({}) is None
