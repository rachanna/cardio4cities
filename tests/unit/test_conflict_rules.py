"""Pure pieces of FX-4 (BD-19): publication-date proxies are not periods (RV-023), Wave 0
values are numbers (RV-020), programme status as observed (RV-026), and confirmed claims
always reach the indexes (RV-031). Fictional values only."""

from datetime import date
from decimal import Decimal

from app.domain.params import ConsistencyParams
from app.domain.vocab import (
    ConsistencyOutcome,
    GeographyLevel,
    PeriodType,
    ProgrammeStatus,
    PublisherClass,
)
from app.workflow.budget import BudgetExhaustedError, BudgetLedger, BudgetLimits
from app.workflow.rules.consistency import StatisticFact, check_statistic
from app.workflow.rules.numbers import PERCENT
from app.workflow.rules.programme_status import observed_on, programme_status_update
from app.workflow.rules.wave0 import record_value
from tests.unit.builders import claim, statistic

P = ProgrammeStatus
PARAMS = ConsistencyParams(agree_pp=Decimal("0.5"), agree_rel=Decimal("0.02"))


def proxy_dated(claim_id: str, published: date, value: str) -> StatisticFact:
    c = claim(
        claim_id,
        labels={
            "period_type": PeriodType.PUBLICATION_DATE_PROXY,
            "reference_start": None,
            "reference_end": published,
        },
    )
    return StatisticFact(c, statistic(claim_id, value), PublisherClass.GOVERNMENT)


def test_figures_dated_only_by_publication_overlap_and_can_disagree() -> None:
    """RV-023: reports published in different years may describe the same period."""
    a = proxy_dated("clm_a", date(2022, 3, 1), "31.5")
    b = proxy_dated("clm_b", date(2024, 6, 1), "45.0")
    decision = check_statistic(b, [a], [GeographyLevel.CITY_WIDE], PARAMS)
    assert decision.outcome is ConsistencyOutcome.CONFLICTS


def test_a_wave0_value_is_read_in_code_with_the_registry_unit() -> None:
    """RV-020: the WHO API writes "22.6"; the registry's "%" is the parser's "percent"."""
    parsed = record_value("22.6", "%")
    assert (parsed.value_num, parsed.unit, parsed.unparsed) == (Decimal("22.6"), PERCENT, False)
    unusual = record_value("4.90% (4.80 to 5.00%)", "%")  # not a form the parser reads
    assert unusual.unparsed  # stays flagged, never guessed
    assert unusual.unit == PERCENT


def test_status_counts_as_of_when_it_was_observed() -> None:
    """RV-026 (owner): "running since 2018" in a 2024 report is a 2024 observation."""
    assert observed_on(P.RUNNING, date(2024, 12, 31), date(2018, 1, 1), None) == date(2024, 12, 31)
    assert observed_on(P.ENDED, date(2024, 12, 31), None, date(2023, 6, 30)) == date(2023, 6, 30)
    assert observed_on(P.PLANNED, None, date(2022, 6, 1), None) == date(2022, 6, 1)
    held = programme_status_update({}, P.PLANNED, "clm_p", date(2022, 6, 1)) or {}
    newer = programme_status_update(held, P.RUNNING, "clm_r", date(2024, 12, 31))
    assert newer is not None
    assert newer["status"] == "running"


def test_one_report_telling_a_history_ends_on_its_latest_state() -> None:
    """Observed on one date, "planned in 2023" and "running since 2025" mean running now."""
    day = date(2025, 6, 1)
    for order in ((P.PLANNED, P.RUNNING), (P.RUNNING, P.PLANNED)):
        since = {P.PLANNED: date(2023, 1, 1), P.RUNNING: date(2025, 3, 1)}
        held: dict[str, object] = {}
        for status in order:
            held = programme_status_update(held, status, f"clm_{status.value}", day,
                                           since[status]) or held  # fmt: skip
        assert held["status"] == "running"


def test_a_tie_is_settled_by_claim_id_whatever_the_arrival_order() -> None:
    day = date(2024, 1, 1)
    first = programme_status_update({}, P.PILOTING, "clm_b", day) or {}
    assert programme_status_update(first, P.RUNNING, "clm_a", day) is not None  # lower ID wins
    second = programme_status_update({}, P.RUNNING, "clm_a", day) or {}
    assert programme_status_update(second, P.PILOTING, "clm_b", day) is None


def test_indexing_a_confirmed_claim_is_never_refused() -> None:
    """RV-031: past the wall clock and the cost cap, model calls stop; indexing does not."""
    now = [0.0]
    ledger = BudgetLedger(
        BudgetLimits(wall_clock_s=10, searches=1, fetches=1, tokens=0, cost_micro_usd=1,
                     wind_down_at=0.85),
        clock=lambda: now[0],
    )  # fmt: skip
    now[0] = 99.0
    ledger.cost_micro_usd = 5

    async def run() -> None:
        try:
            await ledger.reserve("model")
            raise AssertionError("a model call past the limits must be refused")
        except BudgetExhaustedError:
            pass
        await ledger.reserve("indexing")

    import asyncio

    asyncio.run(run())
    assert ledger.indexing == 1
