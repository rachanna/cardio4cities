"""GeoNames parsing and download (LLD-1 §3.1). Parsing is pure; see reference/geonames/README.md.

GeoNames data is licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).
"""

import io
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

GEONAMES_DIR = Path(__file__).resolve().parents[2] / "reference" / "geonames"
BASE_URL = "https://download.geonames.org/export/dump/"
FILES = ("cities15000.zip", "admin1CodesASCII.txt", "countryInfo.txt")
USER_AGENT = "CARDIO4CitiesResearchBot/0.1 (+https://github.com/rachanna/cardio4cities)"

Country = tuple[str, str, str, list[str]]  # iso2, iso3, name, languages
Admin1 = tuple[str, str, str]  # country_iso2, admin1_code, name
Place = tuple[
    str, str, str, list[str], str, str | None, str | None, int | None, float, float, str | None
]


@dataclass(frozen=True)
class Gazetteer:
    countries: list[Country]
    admin1: list[Admin1]
    places: list[Place]
    skipped_admin1: int  # rows whose country is not in countryInfo
    skipped_places: int


def download(directory: Path = GEONAMES_DIR, force: bool = False) -> list[Path]:
    """Fetch the dump files that are missing (or all, with force). Writes atomically."""
    directory.mkdir(parents=True, exist_ok=True)
    fetched = []
    for name in FILES:
        target = directory / name
        if target.exists() and not force:
            continue
        url = BASE_URL + name  # fixed https URL
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            data = response.read()
        partial = target.with_suffix(target.suffix + ".part")
        partial.write_bytes(data)
        partial.replace(target)
        fetched.append(target)
    return fetched


def read_cities_text(directory: Path = GEONAMES_DIR) -> str:
    with zipfile.ZipFile(directory / "cities15000.zip") as archive:
        return archive.read("cities15000.txt").decode("utf-8")


def iso639_1(languages: str) -> list[str]:
    """'en-US,es-US,haw,fr' -> ['en', 'es', 'fr']: two-letter codes, first occurrence order."""
    seen: list[str] = []
    for item in languages.split(","):
        code = item.strip().split("-")[0].lower()
        if len(code) == 2 and code.isalpha() and code not in seen:
            seen.append(code)
    return seen


def parse_countries(text: str) -> list[Country]:
    rows = []
    for line in _lines(text):
        f = line.split("\t")
        rows.append((f[0], f[1], f[4], iso639_1(f[15]) if len(f) > 15 else []))
    return rows


def parse_admin1(text: str) -> list[Admin1]:
    rows = []
    for line in _lines(text):
        code, name = line.split("\t")[:2]
        country, _, admin1_code = code.partition(".")
        rows.append((country, admin1_code, name))
    return rows


def parse_places(text: str) -> list[Place]:
    rows = []
    for line in _lines(text):
        f = line.split("\t")
        rows.append(
            (
                f[0],
                f[1],
                f[2],
                [n for n in f[3].split(",") if n],
                f[8],
                f[10] or None,
                f[11] or None,
                int(f[14]) if f[14] else None,
                float(f[4]),
                float(f[5]),
                f[17] or None,
            )
        )
    return rows


def build_gazetteer(countries_text: str, admin1_text: str, cities_text: str) -> Gazetteer:
    """Parse all three files; drop admin1 and place rows whose country is unknown."""
    countries = parse_countries(countries_text)
    known = {c[0] for c in countries}
    admin1 = parse_admin1(admin1_text)
    places = parse_places(cities_text)
    kept_admin1 = [a for a in admin1 if a[0] in known]
    kept_places = [p for p in places if p[4] in known]
    return Gazetteer(
        countries=countries,
        admin1=kept_admin1,
        places=kept_places,
        skipped_admin1=len(admin1) - len(kept_admin1),
        skipped_places=len(places) - len(kept_places),
    )


def read_gazetteer(directory: Path = GEONAMES_DIR) -> Gazetteer:
    return build_gazetteer(
        (directory / "countryInfo.txt").read_text(encoding="utf-8"),
        (directory / "admin1CodesASCII.txt").read_text(encoding="utf-8"),
        read_cities_text(directory),
    )


def large_place_names(cities_text: str, min_population: int) -> set[str]:
    """Name and ASCII name of every place with at least `min_population` (for AT-02)."""
    names: set[str] = set()
    for place in parse_places(cities_text):
        if place[7] is not None and place[7] >= min_population:
            names.update(n for n in (place[1], place[2]) if n)
    return names


def zip_text(name: str, text: str) -> bytes:
    """A zip holding one text file, as GeoNames publishes cities15000 (used by tests)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def _lines(text: str) -> Iterator[str]:
    lines: Iterable[str] = text.splitlines()
    return (ln for ln in lines if ln.strip() and not ln.startswith("#"))
