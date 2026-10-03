"""Geography fit (BD-10): how the area a figure describes relates to the researched city.

Figures from the city, from areas containing it, and from places within
`geography.nearby_km` of it may answer for the city (with the Not city-level badge
unless the figure is the city's own); rural and peri-urban populations around a city
depend on its services. Figures from farther places, other states or other countries
never do, and neither do areas whose name cannot be placed: precision over coverage.

Pure: the caller looks up gazetteer places for `lookup_names(...)` and passes them in.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import CityIdentity, GeographyFit
from app.domain.vocab import GeographyLevel, GeographyRelation
from app.workflow.rules.quotes import normalise_text

EARTH_RADIUS_KM = 6371.0
# Generic English words for kinds of area, stripped before a name is looked up. They name
# no place, so they carry no city data.
AREA_WORDS = frozenset(
    [
        "district",
        "districts",
        "city",
        "cities",
        "town",
        "municipal",
        "municipality",
        "corporation",
        "metropolitan",
        "metro",
        "region",
        "regional",
        "area",
        "areas",
        "urban",
        "rural",
        "suburban",
        "suburbs",
        "greater",
        "province",
        "state",
        "county",
        "division",
        "zone",
        "ward",
        "wards",
        "block",
        "tehsil",
        "taluk",
        "taluka",
        "mandal",
        "circle",
        "the",
        "of",
    ]
)
_DASHES = chr(0x2013) + chr(0x2014)  # en and em dash
_APOSTROPHES = "'" + chr(0x2019)  # straight and typographic
_SEGMENT = re.compile(rf"\s*(?:,|;|\(|\)|/| [-{_DASHES}] )\s*")
_WORD = re.compile(rf"[^\W_]+(?:[{_APOSTROPHES}.-][^\W_]+)*")


@dataclass(frozen=True)
class PlaceCandidate:
    """A gazetteer place in the city's country whose name matched."""

    gazetteer_id: str
    name: str
    lat: float
    lon: float


_POSSESSIVE = re.compile(rf"[{_APOSTROPHES}]s\b")


def _key(text: str) -> str:
    plain = _POSSESSIVE.sub("", normalise_text(text).casefold())
    return " ".join(_WORD.findall(plain))


def _core(text: str) -> str:
    return " ".join(w for w in _key(text).split() if w not in AREA_WORDS)


SUB_CITY_LEVELS = frozenset({GeographyLevel.SUB_CITY_AREA, GeographyLevel.SUB_CITY_POPULATION})


def city_named(city: CityIdentity, texts: Sequence[str]) -> bool:
    """The city's name or ASCII name, as whole words, in any of the texts. Gazetteer
    alternate names are not used: they include codes and short forms (owner, D2-4)."""
    return any(_mentions(t, n) for t in texts for n in (city.name, city.ascii_name))


def lookup_names(geography_name: str) -> list[str]:
    """Lower-case names to look up: the leading segment without area words, then the
    whole name without area words ("Port Ostra district" -> "port ostra")."""
    names: list[str] = []
    first = _SEGMENT.split(geography_name.strip(), maxsplit=1)[0]
    for candidate in (_core(first), _core(geography_name)):
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _mentions(name: str, part: str | None) -> bool:
    """`part` appears in `name` as whole words."""
    key, wanted = f" {_key(name)} ", _key(part or "")
    return bool(wanted) and f" {wanted} " in key


def geography_fit(
    level: GeographyLevel,
    geography_name: str,
    city: CityIdentity,
    candidates: Sequence[PlaceCandidate],
    nearby_km: float,
    city_named_in_evidence: bool = False,
) -> GeographyFit:
    """`city_named_in_evidence`: the city's own name is in the located quote or a located
    label passage (`city_named`). A sub-city figure needs it, because a part of a city
    is only the researched city's part when the evidence says so (owner, D2-4)."""
    rel = GeographyRelation
    if level in SUB_CITY_LEVELS:
        if city_named_in_evidence:
            return GeographyFit(relation=rel.CITY, place_name=city.name, distance_km=0)
        return GeographyFit(relation=rel.UNRESOLVED)
    if level is GeographyLevel.GLOBAL:
        return GeographyFit(relation=rel.CONTAINS_CITY)
    if level is GeographyLevel.NATIONAL:
        same = _mentions(geography_name, city.country_name)
        return GeographyFit(
            relation=rel.CONTAINS_CITY if same else rel.ELSEWHERE,
            place_name=city.country_name if same else None,
        )
    if level is GeographyLevel.STATE_PROVINCE:
        same = _mentions(geography_name, city.admin1_name)
        return GeographyFit(
            relation=rel.CONTAINS_CITY if same else rel.ELSEWHERE,
            place_name=city.admin1_name if same else None,
        )
    # The gazetteer decides first: a distinct place whose name contains the city's (a
    # satellite town) is that place, not the city. The city's name inside the label
    # counts only when nothing in the gazetteer matched ("X Metropolitan Region").
    is_city = any(c.gazetteer_id == city.gazetteer_id for c in candidates) or (
        not candidates and any(_mentions(geography_name, n) for n in (city.name, city.ascii_name))
    )
    if is_city:
        inside = level in (
            GeographyLevel.CITY_WIDE,
            GeographyLevel.SUB_CITY_AREA,
            GeographyLevel.SUB_CITY_POPULATION,
        )
        return GeographyFit(
            relation=rel.CITY if inside else rel.CONTAINS_CITY, place_name=city.name, distance_km=0
        )
    if not candidates:
        return GeographyFit(relation=rel.UNRESOLVED)
    nearest = min(candidates, key=lambda c: distance_km(city.lat, city.lon, c.lat, c.lon))
    km = distance_km(city.lat, city.lon, nearest.lat, nearest.lon)
    return GeographyFit(
        relation=rel.NEARBY if km <= nearby_km else rel.ELSEWHERE,
        place_name=nearest.name,
        distance_km=round(km),
    )
