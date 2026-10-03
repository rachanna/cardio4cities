"""Owner's tuning decisions after S-6 (BD-15): re-plan priority and the searches left,
the queries per slot, the other-place rule of source selection, and the model call that
never outlives the run. Fictional places only (Halden Bay, Norvania)."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.models import CityIdentity
from app.ports.errors import ProviderUnavailableError
from app.ports.llm import LLMParams, LLMResult
from app.prompts.planner.schema import PlannedQuery, PlannerOutput, SlotQueries, validate
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.deps import Binding
from app.workflow.llm import _call_once
from app.workflow.rules.other_places import place_matcher
from app.workflow.rules.selection import publisher_table, select_urls
from app.workflow.rules.slot_status import replan_capacity, replan_order

# --- re-plan priority (owner: S04, then S03, S05, S06, then the rest) --------------------


def test_priority_slots_come_first_then_the_catalogue_order() -> None:
    qualifying = ["S12", "S05", "S01", "S04", "S09"]
    assert replan_order(qualifying, ["S04", "S03", "S05", "S06"]) == [
        "S04", "S05", "S01", "S09", "S12",
    ]  # fmt: skip


def test_only_as_many_slots_as_the_searches_left_can_serve() -> None:
    assert replan_capacity(searches_used=32, searches_limit=64, per_slot=2) == 16
    assert replan_capacity(searches_used=59, searches_limit=64, per_slot=2) == 2
    assert replan_capacity(searches_used=70, searches_limit=64, per_slot=2) == 0


def test_the_planner_gives_exactly_the_configured_number_of_queries() -> None:
    three = PlannerOutput(
        slots=[
            SlotQueries(
                slot_id="S04",
                queries=[PlannedQuery(text=f"Halden Bay survey {n}", lang="en", purpose="t")
                         for n in range(3)],
            )
        ]
    )  # fmt: skip
    assert validate(three, {"S04"}, ["en"], per_slot=2) == ["S04: give exactly 2 new queries"]


# --- other-place rule (owner: down-rank, never exclude) ----------------------------------

CITY = CityIdentity(
    city_id="city_hb", gazetteer_id="9000001", name="Halden Bay", ascii_name="Halden Bay",
    country_iso2="XN", country_iso3="XNV", country_name="Norvania", admin1_code="01",
    admin1_name="West Coast", admin2_name=None, population=420000, lat=60.1, lon=5.2,
    languages=["nv", "en"],
)  # fmt: skip
PLACES = [
    {"gazetteer_id": "9000001", "name": "Halden Bay", "ascii_name": "Halden Bay",
     "alternate_names": ["Haldenbukt", "HB"]},
    {"gazetteer_id": "9000002", "name": "Port Ostra", "ascii_name": "Port Ostra",
     "alternate_names": []},
    {"gazetteer_id": "9000005", "name": "Kestrel Point", "ascii_name": "Kestrel Point",
     "alternate_names": []},
]  # fmt: skip
MATCHER = place_matcher(CITY, PLACES)


@pytest.mark.parametrize(
    ("title", "snippet", "url", "later"),
    [
        ("Port Ostra heart survey", "Blood pressure in adults", "https://a.test/r", True),
        ("Heart survey", "", "https://health.test/kestrel-point/report", True),
        ("Port Ostra and Halden Bay compared", "", "https://a.test/r", False),  # names the city
        ("Haldenbukt and Port Ostra", "", "https://a.test/r", False),  # the city's other name
        ("Norvania national NCD survey", "Port Ostra, Kestrel Point", "https://a.test/r", False),
        ("West Coast health plan", "Port Ostra clinics", "https://a.test/r", False),  # region
        ("Hypertension guideline", "Adults over 30", "https://a.test/r", False),  # no place
    ],
)
def test_a_hit_about_another_place_only_is_ranked_later(
    title: str, snippet: str, url: str, later: bool
) -> None:
    assert MATCHER.names_other_place(title, snippet, url) is later


def test_a_later_hit_is_kept_after_its_tier_never_dropped() -> None:
    table = publisher_table(
        {"deny": {"domains": []}, "classes": {"government": {"second_level": ["gov"]}}}
    )
    hits = [("https://health.gov.xn/port-ostra", 1), ("https://health.gov.xn/survey", 2)]
    chosen = select_urls(hits, (), table, 5, later={"https://health.gov.xn/port-ostra"})
    assert [c.url for c in chosen] == [
        "https://health.gov.xn/survey",
        "https://health.gov.xn/port-ostra",
    ]


# --- model calls never outlive the run -------------------------------------------------


class Slow:
    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        self.timeout = params.timeout_s
        await asyncio.sleep(10)
        raise AssertionError("the call should have been cut off")


async def test_a_model_call_is_cut_off_when_the_run_has_no_time_left() -> None:
    clock = [0.0]
    ledger = BudgetLedger(
        BudgetLimits(wall_clock_s=420, searches=64, fetches=60, tokens=0, cost_micro_usd=0,
                     wind_down_at=0.85),
        clock=lambda: clock[0],
    )  # fmt: skip
    clock[0] = 419.95  # 50 ms left
    slow = Slow()
    deps: Any = type("Deps", (), {"ledger": ledger, "llm": {"p": slow}})()
    binding = Binding(provider="p", model="m", family="f")
    with pytest.raises(ProviderUnavailableError, match="time ran out"):
        await _call_once(deps, "checker", binding, "system", "user", BaseModel)
    assert slow.timeout == pytest.approx(0.05, abs=0.01)
