"""Source selection (LLD-2 §14, R-41, R-59): canonicalise and de-duplicate candidate
URLs across the run, drop denied domains, classify the publisher, rank by tier then
search rank, and keep the top N not already fetched.

Only the URL of a search hit is used: snippets never become evidence (AT-06).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.ranking import SOURCE_TIER
from app.domain.vocab import PublisherClass
from app.workflow.rules.crawl_gate import canonicalise, host_of


@dataclass(frozen=True)
class PublisherTable:
    deny: frozenset[str]
    domains: dict[str, PublisherClass]  # exact domain or parent domain
    suffixes: tuple[tuple[str, PublisherClass], ...]  # last label, e.g. 'gov', 'edu'
    second_level: tuple[tuple[str, PublisherClass], ...]  # label before a country code


def publisher_table(raw: Mapping[str, Any]) -> PublisherTable:
    """Build from the parsed `reference/publishers.yaml`."""
    domains: dict[str, PublisherClass] = {}
    suffixes: list[tuple[str, PublisherClass]] = []
    second: list[tuple[str, PublisherClass]] = []
    for name, spec in raw["classes"].items():
        cls = PublisherClass(name)
        for domain in spec.get("domains", []):
            domains[domain.lower()] = cls
        suffixes += [(s.lower(), cls) for s in spec.get("suffixes", [])]
        second += [(s.lower(), cls) for s in spec.get("second_level", [])]
    deny = frozenset(d.lower() for d in raw["deny"]["domains"])
    return PublisherTable(deny, domains, tuple(suffixes), tuple(second))


def _parents(host: str) -> list[str]:
    labels = host.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


def is_denied(host: str, table: PublisherTable) -> bool:
    return any(p in table.deny for p in _parents(host))


def classify(host: str, table: PublisherTable) -> PublisherClass:
    host = host.lower().rstrip(".")
    labels = host.split(".")
    for parent in _parents(host):
        if parent in table.domains:
            return table.domains[parent]
    for suffix, cls in table.suffixes:
        if labels[-1] == suffix:
            return cls
    if len(labels) >= 3 and len(labels[-1]) == 2:  # e.g. health.gov.xx, uni.ac.xx
        for label, cls in table.second_level:
            if labels[-2] == label:
                return cls
    if labels[-1] == "org":
        return PublisherClass.NGO
    return PublisherClass.OTHER


@dataclass(frozen=True)
class Candidate:
    url: str  # canonical
    domain: str
    publisher_class: PublisherClass
    search_rank: int


def select_urls(
    hits: Sequence[tuple[str, int]],
    already_fetched: Iterable[str],
    table: PublisherTable,
    max_new: int,
) -> list[Candidate]:
    """`hits`: (url, search rank) from every search of this slot round."""
    fetched = set(already_fetched)
    best: dict[str, Candidate] = {}
    for url, rank in hits:
        canonical = canonicalise(url)
        if canonical is None or canonical in fetched:
            continue
        host = host_of(canonical)
        if not host or is_denied(host, table):
            continue
        candidate = Candidate(canonical, host, classify(host, table), rank)
        if canonical not in best or rank < best[canonical].search_rank:
            best[canonical] = candidate
    ranked = sorted(
        best.values(), key=lambda c: (SOURCE_TIER[c.publisher_class], c.search_rank, c.url)
    )
    return ranked[:max_new]


def government_sites(table: PublisherTable, country_iso2: str) -> list[str]:
    """`site:` patterns for the planner (prompt v2, BD-14): the generic government
    second-level labels under the country's code, e.g. `site:gov.xx`. Names no site."""
    code = country_iso2.lower()
    return [
        f"site:{label}.{code}"
        for label, cls in table.second_level
        if cls is PublisherClass.GOVERNMENT
    ]
