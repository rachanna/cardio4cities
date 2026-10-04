"""AT-02: no city-specific facts or per-city URL lists anywhere in the repository (R-01, A-09).

Scans every text file git tracks or would track (BD-35): code, tests, fixtures, scripts
(spike summaries included), config, reference data, prompts and deploy files are strict;
`docs/` may name a real place only through ALLOWLIST, one reviewed entry per name with a
reason, because decision rows may name the countries or cities a spike tested.

Looks for the name or ASCII name of every gazetteer place with population of at least
MIN_POPULATION and at least MIN_NAME_LENGTH characters: whole words and case-sensitive in
text; inside URLs as a whole token, ignoring case, built from ASCII names only (an accented
name folded to ASCII leaves fragments that match ordinary URLs). COMMON_WORDS are place
names that are also ordinary words or identifiers. An allow-list entry that no longer
matches anything fails the test.

Places below the threshold that were used in spikes or rehearsals can be listed, one per
line, in EXTRA_NAMES: it is git-ignored, so the names never enter the repository, and the
scan looks for them too wherever the file exists.
"""

import re
import shutil
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from scripts.reference.geonames import GEONAMES_DIR, large_place_names, read_cities_text

ROOT = Path(__file__).resolve().parents[2]
MIN_POPULATION = 50_000
MIN_NAME_LENGTH = 4
# Place names that are also English words or code identifiers; never a city in this repo
COMMON_WORDS = frozenset({"Date", "Independence", "Most", "Reading", "Split", "Union", "Upland"})
ALLOWLIST = ROOT / "docs" / "no_seeding_allowlist.yaml"
ALLOWED_PREFIX = "docs/"  # only documents may be allow-listed; everything else is strict
EXTRA_NAMES = ROOT / "spike_results" / "scan_names.txt"  # git-ignored, optional
# The gazetteer itself (git-ignored dumps), and npm's lock file: registry URLs and
# platform names of third-party packages, written by npm (BD-41)
SKIPPED = ("reference/geonames/", "web/package-lock.json")
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
            if not name.isascii():
                continue
            words = re.findall(r"[a-z0-9]+", name.lower())
            for joiner in ("-", "_", ""):
                if words and len(joiner.join(words)) >= MIN_NAME_LENGTH:
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


def git(*args: str) -> subprocess.CompletedProcess[str]:
    """git with fixed arguments from this module, never from input."""
    executable = shutil.which("git")
    assert executable, "AT-02 lists the repository's files with git"
    return subprocess.run(  # noqa: S603 - fixed arguments, resolved executable
        [executable, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )


def repository_files() -> list[str]:
    """Tracked files plus new files git would track: what a commit would carry."""
    listed = git("ls-files", "--cached", "--others", "--exclude-standard")
    assert listed.returncode == 0, listed.stderr
    return sorted(
        {
            p
            for p in listed.stdout.splitlines()
            if (ROOT / p).is_file() and not p.startswith(SKIPPED)
        }
    )


def read_text(path: str) -> str | None:
    """The file's text, or None for a binary file."""
    data = (ROOT / path).read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scanned_files() -> dict[str, str]:
    texts = {
        p: read_text(p) for p in repository_files() if p != ALLOWLIST.relative_to(ROOT).as_posix()
    }
    return {p: t for p, t in texts.items() if t is not None}


def load_allowlist() -> set[tuple[str, str]]:
    entries = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or []
    allowed = set()
    for entry in entries:
        assert entry.get("reason", "").strip(), f"allow-list entry needs a reason: {entry}"
        for path in entry["paths"]:
            assert path.startswith(ALLOWED_PREFIX), f"only documents may be allow-listed: {path}"
            allowed.add((path, entry["name"]))
    return allowed


@pytest.fixture(scope="module")
def scanner() -> PlaceScanner:
    if not (GEONAMES_DIR / "cities15000.zip").exists():
        pytest.fail("AT-02 needs the gazetteer: run `uv run poe geonames` (downloads, no database)")
    large = large_place_names(read_cities_text(GEONAMES_DIR), MIN_POPULATION)
    names = [n for n in large if len(n) >= MIN_NAME_LENGTH and n not in COMMON_WORDS]
    return PlaceScanner([*names, *extra_names()])


def extra_names() -> list[str]:
    """Spike and rehearsal places from the git-ignored EXTRA_NAMES, when it exists."""
    if not EXTRA_NAMES.exists():
        return []
    lines = EXTRA_NAMES.read_text(encoding="utf-8").splitlines()
    return [n.strip() for n in lines if n.strip() and not n.lstrip().startswith("#")]


def test_no_city_names_or_city_urls_in_the_repository(scanner: PlaceScanner) -> None:
    """AT-02: no file names a real city, except reviewed mentions in the documents."""
    allowed = load_allowlist()
    hits = [hit for path, text in scanned_files().items() for hit in scanner.scan(path, text)]
    unexplained = sorted(h for h in hits if (h.path, h.name) not in allowed)
    stale = allowed - {(h.path, h.name) for h in hits}

    assert not unexplained, (
        "city names found (remove; in docs/ only, allow-list with a reason):\n"
        + "\n".join(
            f"  {h.path}:{h.line}: {h.name!r}{' in a URL' if h.in_url else ''}" for h in unexplained
        )
    )
    assert not stale, f"allow-list entries that no longer match anything: {sorted(stale)}"


def test_scan_covers_the_whole_repository() -> None:
    """AT-02: code, tests, scripts, config, reference data, prompts and deploy files are
    scanned; the gazetteer dumps are not."""
    scanned = set(scanned_files())

    assert {
        "reference/slots.yaml", "config/local.yaml", "render.yaml", "README.md",
        "app/prompts/safety.py", "app/workflow/graph.py", "tests/support/gazetteer.py",
        "scripts/reference/geonames.py", "docs/DECISIONS.md", "Dockerfile",
    } <= scanned  # fmt: skip
    assert not any(p.startswith(SKIPPED) for p in scanned)


def test_the_extra_names_file_is_never_committed() -> None:
    """The spike and rehearsal list names real places: it must stay git-ignored."""
    assert git("check-ignore", "-q", EXTRA_NAMES.relative_to(ROOT).as_posix()).returncode == 0


# --- the scanner itself, on a fictional gazetteer ---------------------------


@pytest.fixture
def fictional() -> PlaceScanner:
    return PlaceScanner(["Halden Bay", "Port Ostra", "Hålby", "Vik"])


def test_whole_word_case_sensitive_match(fictional: PlaceScanner) -> None:
    hits = fictional.scan("f.md", "Clinics in Halden Bay.\nhalden bay\nHalden Bayfront\n")

    assert [(h.name, h.line) for h in hits] == [("Halden Bay", 1)]


def test_city_in_url_matched_as_token(fictional: PlaceScanner) -> None:
    text = "see https://www.halden-bay.gov.example/health and https://example.org/portostra/x\n"

    assert {(h.name, h.in_url) for h in fictional.scan("f.yaml", text)} == {
        ("Halden Bay", True),
        ("Port Ostra", True),
    }


def test_url_substring_is_not_a_match(fictional: PlaceScanner) -> None:
    assert fictional.scan("f.yaml", "https://example.org/haldenbayside/\n") == []


def test_url_forms_come_from_ascii_names_of_four_or_more_letters(fictional: PlaceScanner) -> None:
    """A folded accented name ("hlby") or a short one ("vik") is not looked for in URLs;
    both are still found as words in text."""
    assert fictional.scan("f.md", "https://example.org/hlby/vik/\n") == []
    assert {h.name for h in fictional.scan("f.md", "Hålby and Vik\n")} == {"Hålby", "Vik"}
