"""A figure never answers a question that asks for no figure, and an indexing hiccup is
not an incomplete run (BD-52). Fictional Halden Bay, Norvania."""

from app.domain.cards import slot_row, summary
from app.domain.vocab import AnswerKind, ClaimKind, SlotStatus
from app.report.render import lost_steps
from app.workflow.rules.slot_status import slot_status
from tests.unit.builders import claim, slot
from tests.unit.test_cards import stored
from tests.unit.test_report_honesty import cards_of, statement

SCREENING = slot(
    "S08",
    dimension="D3",
    answer_kind=AnswerKind.STATEMENT,
    indicator_codes=[],
    relation_types=[],
    accepted_levels=["city_wide", "sub_city_area"],
)


def test_a_figure_does_not_answer_a_question_that_asks_for_no_figure() -> None:
    """A community survey's prevalence figure filed under "is there screening?" is shown,
    but the question is not answered by it."""
    figure = claim("clm_fig", slot_id="S08", kind=ClaimKind.STATISTIC)
    said = claim("clm_said", slot_id="S08", kind=ClaimKind.STATEMENT)
    assert slot_status(SCREENING, [figure], 1, []) is SlotStatus.ANSWERED_WIDER_GEO
    assert slot_status(SCREENING, [figure, said], 1, []) is SlotStatus.ANSWERED


def test_a_figure_never_stands_as_the_key_finding_of_such_a_question() -> None:
    figure = stored("clm_fig", slot_id="S08", statement="In Halden Bay 15% had diabetes.")
    said = statement("clm_said", "Halden Bay clinics screen adults for diabetes.", "S08")
    cards = cards_of(figure, said, slots={"S08": SCREENING})
    row = slot_row({"status": "answered", "best_claim_ids": ["clm_fig", "clm_said"]}, SCREENING)
    assert [c.claim_id for c in summary([row], cards)["D3"]] == ["clm_fig"]
    assert [c.claim_id for c in summary([row], cards, slots={"S08": SCREENING})["D3"]] == [
        "clm_said"
    ]


def test_an_indexing_failure_does_not_mark_the_run_incomplete() -> None:
    assert lost_steps({"failed_steps": {"index_chunks": 1}}) is None
    assert lost_steps({"failed_steps": {"index_chunks": 1, "extract": 2}}) == "2 extraction steps"
