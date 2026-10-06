"""Slot status, flags, re-plan rule and gap notes (LLD-2 §11, AT-32 rules)."""

from datetime import date

import pytest

from app.domain.vocab import AnswerKind, Badge, ClaimStatus, CrawlOutcome, SlotFlag, SlotStatus
from app.workflow.rules.gap_notes import gap_note
from app.workflow.rules.slot_status import should_replan, slot_flags, slot_status
from tests.unit.builders import claim, replan_params, slot

NATIONAL = {
    "geography_level": "national",
    "geography_name": "Norvania",
    "reference_start": None,
    "reference_end": date(2023, 12, 31),
}


def test_city_level_supported_claim_answers_the_slot() -> None:
    assert slot_status(slot(), [claim()], 3, []) is SlotStatus.ANSWERED


def test_slot_with_only_a_national_figure_is_wider_geo_and_replanned_once() -> None:
    """LLD-2 §11 test."""
    national = claim(labels=NATIONAL)
    params = replan_params()

    status = slot_status(slot(), [national], 4, [])

    assert status is SlotStatus.ANSWERED_WIDER_GEO
    assert should_replan(slot(), status, 0, False, params)
    assert not should_replan(slot(), status, 1, False, params)


def test_wider_geo_is_not_replanned_for_policy_slots() -> None:
    policy = slot(
        "S09", answer_kind=AnswerKind.MIXED, indicator_codes=[], relation_types=["APPLIES_TO"]
    )

    assert not should_replan(policy, SlotStatus.ANSWERED_WIDER_GEO, 0, False, replan_params())


def test_slot_whose_only_candidates_were_blocked_is_blocked() -> None:
    """LLD-2 §11 test."""
    outcomes = [CrawlOutcome.BLOCKED_ROBOTS, CrawlOutcome.UNREACHABLE_NETWORK]

    assert slot_status(slot(), [], 0, outcomes) is SlotStatus.BLOCKED


def test_only_unreachable_candidates_is_unreachable() -> None:
    outcomes = [CrawlOutcome.UNREACHABLE_SERVER_ERROR, CrawlOutcome.RATE_LIMITED]

    assert slot_status(slot(), [], 0, outcomes) is SlotStatus.UNREACHABLE


def test_sources_fetched_but_nothing_supported_is_negative() -> None:
    refuted = claim(status=ClaimStatus.REFUTED)

    assert (
        slot_status(slot(), [refuted], 2, [CrawlOutcome.BLOCKED_ROBOTS])
        is SlotStatus.ANSWERED_NEGATIVE
    )


@pytest.mark.parametrize(
    "status", [SlotStatus.ANSWERED_NEGATIVE, SlotStatus.BLOCKED, SlotStatus.UNREACHABLE]
)
def test_negative_statuses_replan_up_to_the_limit(status: SlotStatus) -> None:
    params = replan_params()

    assert should_replan(slot(), status, params.max_rounds - 1, False, params)
    assert not should_replan(slot(), status, params.max_rounds, False, params)


def test_after_a_budget_stop_every_slot_still_has_a_status_and_none_replans() -> None:
    """LLD-2 §11 test: a budget warning stops re-planning; statuses still resolve."""
    cases = [([claim()], 1, []), ([], 0, [CrawlOutcome.BLOCKED_ROBOTS]), ([], 0, [])]
    for claims, fetched, outcomes in cases:
        status = slot_status(slot(), claims, fetched, outcomes)
        assert status in SlotStatus
        assert not should_replan(slot(), status, 0, True, replan_params())


def test_slot_flags() -> None:
    assert slot_flags("clm_a", ["clm_a", "clm_b"], None) == {SlotFlag.CONFLICTING}
    assert slot_flags("clm_a", [], Badge.NOT_CITY_LEVEL, [Badge.OUTDATED]) == {SlotFlag.STALE}
    assert slot_flags(None, ["clm_a"], None) == frozenset()


# --- gap notes ---------------------------------------------------------------------


def test_wider_geo_note_names_the_level_place_and_year() -> None:
    note = gap_note(SlotStatus.ANSWERED_WIDER_GEO, best=claim(labels=NATIONAL))

    assert note == "No city-level figure found. Best available is national (Norvania, 2023)."


def test_negative_note_says_what_was_searched() -> None:
    note = gap_note(
        SlotStatus.ANSWERED_NEGATIVE, n_queries=9, languages=["English", "Norvanian"], n_sources=7
    )

    assert note == (
        "Searched 9 queries in English and Norvanian and checked 7 sources; "
        "nothing acceptable found for this question."
    )


def test_blocked_note_lists_top_reasons() -> None:
    outcomes = [CrawlOutcome.BLOCKED_ROBOTS] * 2 + [CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL]

    note = gap_note(SlotStatus.BLOCKED, crawl_outcomes=outcomes)

    assert note == (
        "3 candidate sources refuse automated access "
        "(robots.txt disallows (2), login or paywall (1))."
    )


def test_unreachable_note() -> None:
    note = gap_note(SlotStatus.UNREACHABLE, crawl_outcomes=[CrawlOutcome.UNREACHABLE_NETWORK])

    assert note == "1 candidate source could not be reached (network error (1))."


def test_unconfirmed_claims_are_appended() -> None:
    note = gap_note(
        SlotStatus.ANSWERED_NEGATIVE, n_queries=3, languages=["English"], n_sources=2, unconfirmed=4
    )

    assert note is not None
    assert note.endswith(" 4 claims were found but could not be confirmed against their sources.")


def test_answered_slot_has_no_gap_note() -> None:
    assert gap_note(SlotStatus.ANSWERED, unconfirmed=2) is None


def test_gap_notes_read_as_plain_english_for_one_of_anything() -> None:
    """D4-3: '1 source', not '1 sources'; '1 candidate source refuses'."""
    note = gap_note(SlotStatus.ANSWERED_NEGATIVE, n_queries=1, languages=["English"], n_sources=1)
    assert note == (
        "Searched 1 query in English and checked 1 source; "
        "nothing acceptable found for this question."
    )
    blocked = gap_note(SlotStatus.BLOCKED, crawl_outcomes=[CrawlOutcome.BLOCKED_ROBOTS])
    assert blocked == "1 candidate source refuses automated access (robots.txt disallows (1))."
