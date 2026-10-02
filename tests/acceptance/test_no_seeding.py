"""AT-02: no city-specific facts or per-city URL lists in runtime prompts, config,
reference data, seed scripts or fixtures (R-01, A-09).

Looks for the name or ASCII name of every gazetteer place with population of at
least MIN_POPULATION: whole words and case-sensitive in text; inside URLs as a
whole token, ignoring case. Justified exceptions go in no_seeding_allowlist.yaml
with a reason; an entry that no longer matches anything fails the test.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from scripts.reference.geonames import GEONAMES_DIR, large_place_names, read_cities_text

ROOT = Path(__file__).resolve().parents[2]
MIN_POPULATION = 300_000
SCAN_DIRS = ("app/prompts", "config", "tests/fixtures", "scripts/reference")
SCAN_GLOBS = ("reference/*.yaml",)  # never reference/geonames/: that is the gazetteer itself
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".txt", ".j2", ".html", ".csv", ".toml"}
ALLOWLIST = Path(__file__).with_name("no_seeding_allowlist.yaml")
URL = re.compile(r"https?://[^\s\"'<>)\]]+")


@dataclass(frozen=True, order=True)
class Hit:
    path: str
    name: str
    line: int
    in_url: bool


class PlaceScanner:
    def __init__(self, names: Iterable[str]) -> None:
        ordered = sorted({n for n in names if n.strip()}, key=len, reverse=True)
        self._text = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, ordered)) + r")(?!\w)")
        self._url_forms: dict[str, str] = {}
        for name in ordered:
            words = re.findall(r"[a-z0-9]+", name.lower())
            for joiner in ("-", "_", ""):
                if words:
                    self._url_forms.setdefault(joiner.join(words), name)
        self._url = re.compile(
            r"(?<![a-z0-9])("
            + "|".join(map(re.escape, sorted(self._url_forms, key=len, reverse=True)))
            + r")(?![a-z0-9])"
        )

    def scan(self, path: str, text: str) -> list[Hit]:
        hits = []
        for number, line in enumerate(text.splitlines(), start=1):
            for url in URL.findall(line):
                hits += [
                    Hit(path, self._url_forms[m.group(1)], number, True)
                    for m in self._url.finditer(url.lower())
                ]
            without_urls = URL.sub(" ", line)
            hits += [
                Hit(path, m.group(1), number, False) for m in self._text.finditer(without_urls)
            ]
        return hits


def scanned_files() -> list[Path]:
    files = [p for d in SCAN_DIRS for p in (ROOT / d).rglob("*") if p.is_file()]
    files += [p for g in SCAN_GLOBS for p in ROOT.glob(g)]
    return sorted(p for p in files if p.suffix in TEXT_SUFFIXES and "__pycache__" not in p.parts)


def load_allowlist() -> set[tuple[str, str]]:
    entries = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or []
    for entry in entries:
        assert entry.get("reason", "").strip(), f"allow-list entry needs a reason: {entry}"
    return {(e["path"], e["name"]) for e in entries}


@pytest.fixture(scope="module")
def scanner() -> PlaceScanner:
    if not (GEONAMES_DIR / "cities15000.zip").exists():
        pytest.fail("AT-02 needs the gazetteer: run `uv run poe geonames` (downloads, no database)")
    return PlaceScanner(large_place_names(read_cities_text(GEONAMES_DIR), MIN_POPULATION))


def test_no_city_names_or_city_urls_in_seeded_content(scanner: PlaceScanner) -> None:
    """AT-02: prompts, config, reference YAML, seed scripts and fixtures name no real city."""
    allowed = load_allowlist()
    hits = [
        hit
        for path in scanned_files()
        for hit in scanner.scan(
            path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8", errors="replace")
        )
    ]
    unexplained = sorted(h for h in hits if (h.path, h.name) not in allowed)
    stale = allowed - {(h.path, h.name) for h in hits}

    assert not unexplained, "city names found (fix, or allow-list with a reason):\n" + "\n".join(
        f"  {h.path}:{h.line}: {h.name!r}{' in a URL' if h.in_url else ''}" for h in unexplained
    )
    assert not stale, f"allow-list entries that no longer match anything: {sorted(stale)}"


def test_scan_covers_the_seeded_content() -> None:
    """AT-02: the scan reaches the reference YAML and config, and skips the gazetteer dumps."""
    scanned = {p.relative_to(ROOT).as_posix() for p in scanned_files()}

    assert {"reference/slots.yaml", "reference/sources.yaml", "config/local.yaml"} <= scanned
    assert not any(p.startswith("reference/geonames/") for p in scanned)


# --- the scanner itself, on a fictional gazetteer ---------------------------


@pytest.fixture
def fictional() -> PlaceScanner:
    return PlaceScanner(["Halden Bay", "Port Ostra"])


def test_whole_word_case_sensitive_match(fictional: PlaceScanner) -> None:
    hits = fictional.scan("f.md", "Clinics in Halden Bay.\nhalden bay\nHalden Bayside\n")

    assert [(h.name, h.line) for h in hits] == [("Halden Bay", 1)]


def test_city_in_url_matched_as_token(fictional: PlaceScanner) -> None:
    text = "see https://www.halden-bay.gov.example/health and https://example.org/portostra/x\n"

    assert {(h.name, h.in_url) for h in fictional.scan("f.yaml", text)} == {
        ("Halden Bay", True),
        ("Port Ostra", True),
    }


def test_url_substring_is_not_a_match(fictional: PlaceScanner) -> None:
    assert fictional.scan("f.yaml", "https://example.org/haldenbayside/\n") == []
