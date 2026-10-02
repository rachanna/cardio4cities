"""Pure collection rules: canonicalising, address checks, RFC 9309 status handling,
Content-Usage, source selection and chunking (LLD-2 §9, §14; LLD-1 §5.3)."""

from itertools import pairwise
from pathlib import Path

import pytest
import yaml

from app.domain.vocab import PublisherClass
from app.workflow.rules.chunking import ChunkParams, chunk_text, estimate_tokens
from app.workflow.rules.content_usage import from_header, from_robots, parse_preferences
from app.workflow.rules.crawl_gate import (
    canonicalise,
    check_addresses,
    check_scheme_and_port,
    is_public_address,
    literal_address,
)
from app.workflow.rules.robots import parse_groups, robots_availability, select_rules
from app.workflow.rules.selection import classify, is_denied, publisher_table, select_urls
from tests.unit.builders import config

UA = "CARDIO4CitiesResearchBot/0.1 (+https://github.com/rachanna/cardio4cities)"
PUBLISHERS = Path(__file__).resolve().parents[2] / "reference" / "publishers.yaml"

# --- canonicalise and address checks --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("HTTPS://Health.Halden-Bay.TEST/Report#top", "https://health.halden-bay.test/Report"),
        (
            "https://health.halden-bay.test:443/a?utm_source=x&id=7&gclid=1",
            "https://health.halden-bay.test/a?id=7",
        ),
        ("http://health.halden-bay.test", "http://health.halden-bay.test/"),
        ("http://health.halden-bay.test:8080/x", "http://health.halden-bay.test:8080/x"),
        ("not a url", None),
        ("http://[::1]/x", "http://[::1]/x"),
    ],
)
def test_canonicalise(raw: str, canonical: str | None) -> None:
    assert canonicalise(raw) == canonical


def test_scheme_and_port() -> None:
    assert check_scheme_and_port("https://a.test/", (80, 443)) is None
    assert check_scheme_and_port("ftp://a.test/", (80, 443)) == "unsupported scheme 'ftp'"
    assert check_scheme_and_port("http://a.test:8080/", (80, 443)) == "unsupported port 8080"


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),  # noqa: S104
        ("224.0.0.1", False),
        ("240.0.0.1", False),
        ("192.0.2.10", False),
        ("::1", False),
        ("fe80::1", False),
        ("fd00:ec2::254", False),
        ("::ffff:10.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_is_public_address(address: str, public: bool) -> None:
    assert is_public_address(address) is public


def test_check_addresses_and_literals() -> None:
    assert check_addresses([]) == "host does not resolve"
    assert (
        check_addresses(["93.184.216.34", "10.0.0.1"])
        == "resolves to a non-public address (10.0.0.1)"
    )
    assert literal_address("[::1]") == "::1"
    assert literal_address("health.halden-bay.test") is None


# --- robots.txt (RFC 9309) ------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "availability"),
    [
        (200, "parsed"),
        (404, "unavailable"),
        (403, "unavailable"),
        (401, "unavailable"),
        (503, "unreachable_server_error"),
        (500, "unreachable_server_error"),
        (None, "unreachable_network"),
    ],
)
def test_robots_status_handling(status: int | None, availability: str) -> None:
    assert robots_availability(status) == availability


def test_group_selection_by_product_token_with_star_fallback() -> None:
    groups = parse_groups(
        "User-agent: *\nDisallow: /a\n\nUser-agent: Cardio4CitiesResearchBot\n"
        "User-agent: OtherBot\nDisallow: /b\n\nUser-agent: cardio4citiesresearchbot\nDisallow: /c\n"
    )

    assert select_rules(groups, UA) == [("disallow", "/b"), ("disallow", "/c")]
    assert select_rules(groups, "SomeBot/2") == [("disallow", "/a")]


# --- Content-Usage -------------------------------------------------------------------


def test_preferences_parse_dictionary_syntax() -> None:
    assert parse_preferences('train-ai=n, ai-use="y"; search=n') == {
        "train-ai": "n",
        "ai-use": "y",
        "search": "n",
    }


@pytest.mark.parametrize(
    ("line", "blocked"),
    [
        ("ai-use=n", True),
        ("ai=n", True),
        ("tdm=n", True),
        ("train-ai=n", False),
        ("search=n", False),
        ("ai-use=y", False),
    ],
)
def test_which_opt_outs_block(line: str, blocked: bool) -> None:
    groups = parse_groups(f"User-agent: *\nAllow: /\nContent-Usage: {line}\n")

    assert from_robots(groups, UA, "https://h.test/page").blocked is blocked


def test_content_signal_ai_input_no_blocks() -> None:
    groups = parse_groups("User-agent: *\nContent-Signal: search=yes, ai-input=no, ai-train=no\n")

    assert from_robots(groups, UA, "https://h.test/").blocked


def test_longer_path_overrides_general_preference() -> None:
    """Example from draft-ietf-aipref-attach-05."""
    groups = parse_groups(
        "User-Agent: *\nAllow: /\nDisallow: /never/\nContent-Usage: ai-use=n\n"
        "Content-Usage: /ai-ok/ ai-use=y\n"
    )

    assert from_robots(groups, UA, "https://h.test/other").blocked
    assert not from_robots(groups, UA, "https://h.test/ai-ok/page").blocked


def test_header_preferences() -> None:
    assert from_header({"content-usage": "train-ai=n, ai-use=n"}).blocked
    assert not from_header({"content-usage": "train-ai=n"}).blocked
    assert from_header({}).preferences == {}


# --- selection (§14) -----------------------------------------------------------------


@pytest.fixture(scope="module")
def table():  # type: ignore[no-untyped-def]
    return publisher_table(yaml.safe_load(PUBLISHERS.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("host", "cls"),
    [
        ("health.gov.xn", PublisherClass.GOVERNMENT),
        ("ministerio.gob.xn", PublisherClass.GOVERNMENT),
        ("data.cdc.gov", PublisherClass.GOVERNMENT),
        ("www.who.int", PublisherClass.MULTILATERAL),
        ("iris.who.int", PublisherClass.MULTILATERAL),
        ("uni.ac.xn", PublisherClass.ACADEMIC),
        ("pubmed.ncbi.nlm.nih.gov", PublisherClass.ACADEMIC),
        ("www.thelancet.com", PublisherClass.ACADEMIC),
        ("www.reuters.com", PublisherClass.NEWS),
        ("heart-foundation.org", PublisherClass.NGO),
        ("blog.example.com", PublisherClass.OTHER),
    ],
)
def test_publisher_class_by_domain_pattern(table, host: str, cls: PublisherClass) -> None:  # type: ignore[no-untyped-def]
    assert classify(host, table) is cls


def test_selection_dedupes_denies_ranks_and_caps(table) -> None:  # type: ignore[no-untyped-def]
    hits = [
        ("https://blog.example.com/a", 1),
        ("https://www.reddit.com/r/health", 2),
        ("https://health.gov.xn/report?utm_source=s", 3),
        ("https://HEALTH.gov.xn/report", 4),
        ("https://heart-foundation.org/x", 5),
        ("https://www.who.int/fact", 6),
        ("https://done.gov.xn/old", 7),
    ]

    chosen = select_urls(hits, {"https://done.gov.xn/old"}, table, max_new=3)

    assert [c.url for c in chosen] == [
        "https://health.gov.xn/report",
        "https://www.who.int/fact",
        "https://heart-foundation.org/x",
    ]
    assert chosen[0].search_rank == 3
    assert is_denied("old.reddit.com", table)


# --- chunking (LLD-1 §5.3) -------------------------------------------------------------


def _params() -> ChunkParams:
    return ChunkParams(**config()["chunk"])


def test_shipped_chunk_settings() -> None:
    assert _params() == ChunkParams(prose_tokens=400, overlap_tokens=60, table_max_tokens=1200)


def test_prose_chunks_follow_sentences_with_overlap() -> None:
    sentence = "Halden Bay reported heart health figures for adults in the survey year. "
    text = sentence * 60  # about 760 tokens
    params = ChunkParams(prose_tokens=200, overlap_tokens=40, table_max_tokens=1200)

    chunks = chunk_text(text, [], params)

    assert len(chunks) > 3
    assert all(c.text.endswith(".") for c in chunks)
    assert all(text[c.start : c.end].strip() == c.text for c in chunks)
    assert all(b.start < a.end for a, b in pairwise(chunks))  # overlap
    assert all(estimate_tokens(c.text) <= 200 + 20 for c in chunks)


def test_tables_are_whole_chunks_with_their_header() -> None:
    table = "| Indicator | Value |\n|---|---|\n| Raised blood pressure | 31.2% |\n"
    text = "Intro sentence about Halden Bay.\n" + table + "Closing sentence."
    start = text.index("|")

    chunks = chunk_text(text, [(start, start + len(table))], _params())

    assert [c.is_table for c in chunks] == [False, True, False]
    assert chunks[1].text.startswith("| Indicator | Value |")


def test_long_table_split_by_rows_with_header_repeated() -> None:
    rows = "".join(f"| District {n} | {n}.0% |\n" for n in range(200))
    table = "| District | Share |\n|---|---|\n" + rows
    params = ChunkParams(prose_tokens=400, overlap_tokens=60, table_max_tokens=150)

    chunks = chunk_text(table, [(0, len(table))], params)

    assert len(chunks) > 3
    assert all(c.text.startswith("| District | Share |\n|---|---|") for c in chunks)
    assert sum(c.text.count("| District ") - 1 for c in chunks) == 200
