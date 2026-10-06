"""Local first (BD-50): the planner hears which sites refused access, search hits that name
the city are read first, and once a question holds a figure it cannot accept as its answer,
pages that never name the city are read only a few at a time. Fictional Halden Bay,
Norvania."""

from app.prompts.planner import context
from app.workflow.rules.other_places import place_matcher
from app.workflow.rules.selection import publisher_table, select_urls, sources_to_read
from tests.unit.test_geography_attribution import HALDEN

ROWS = [
    {"gazetteer_id": "9000001", "name": "Halden Bay", "ascii_name": "Halden Bay",
     "alternate_names": ["Haldenbay"]},
    {"gazetteer_id": "9000002", "name": "Port Ostra", "ascii_name": "Port Ostra",
     "alternate_names": []},
]  # fmt: skip
MATCHER = place_matcher(HALDEN, ROWS)
TABLE = publisher_table(
    {
        "deny": {"domains": []},
        "classes": {
            "government": {"second_level": ["gov"]},
            "news": {"domains": ["herald.xn"]},
        },
    }
)


def test_a_hit_names_the_city_by_any_of_its_names_but_not_by_its_region_or_country() -> None:
    assert MATCHER.names_city("Heart health in Halden Bay", "", "https://a.test/")
    assert MATCHER.names_city("", "", "https://health.gov.xn/haldenbay/profile")
    assert not MATCHER.names_city(
        "Coast region heart survey", "Norvania figures", "https://a.test/"
    )


def test_hits_naming_the_city_are_read_first_within_trusted_publishers() -> None:
    hits = [
        ("https://health.gov.xn/national-survey", 1),
        ("https://herald.xn/halden-bay-clinics", 2),
        ("https://council.gov.xn/halden-bay-health-profile", 3),
    ]
    local = {
        "https://herald.xn/halden-bay-clinics",
        "https://council.gov.xn/halden-bay-health-profile",
    }
    chosen = [c.url for c in select_urls(hits, (), TABLE, 5, local=local)]
    assert chosen == [
        "https://council.gov.xn/halden-bay-health-profile",  # local and trusted: first
        "https://health.gov.xn/national-survey",
        "https://herald.xn/halden-bay-clinics",  # news keeps its tier, local or not
    ]
    without = select_urls(hits, (), TABLE, 5)  # prefer_local off: tier first, as before
    assert without[0].url == "https://health.gov.xn/national-survey"


def test_once_a_wider_fact_is_held_only_a_few_pages_not_naming_the_city_are_read() -> None:
    pages = [("src_national_1", False), ("src_city", True), ("src_national_2", False)]
    assert sources_to_read(pages, holds_wider_fact=True, max_without_city=1) == [
        "src_city",
        "src_national_1",
    ]
    assert sources_to_read(pages, holds_wider_fact=False, max_without_city=1) == [
        "src_city",
        "src_national_1",
        "src_national_2",
    ]


def test_the_planner_hears_which_sites_refused_access() -> None:
    line = context.previous_attempt(
        "S03", "answered_wider_geo", ["Halden Bay hypertension"], None, ["stats.gov.xn"]
    )
    assert line.endswith("; sites refusing access: stats.gov.xn")
    assert context.previous_attempt("S03", "answered_negative", [], None).endswith("access: none")
