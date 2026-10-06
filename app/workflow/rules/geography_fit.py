"""Geography fit (BD-10, BD-17): how the area a figure describes relates to the researched city.

Figures from the city, from areas containing it, and from places within
`geography.nearby_km` of it may answer for the city (with the Not city-level badge
unless the figure is the city's own); rural and peri-urban populations around a city
depend on its services. Figures from farther places, other states or other countries
never do, and neither do areas whose name cannot be placed: precision over coverage.

Rules for a local area name (BD-17), in order:
1. Qualifiers decide first: in "Halden Bay, Ostland" any segment after the first that is
   not the city's own region, district or country makes the figure not the city's.
2. The full name before the name with area words removed: a gazetteer place called
   "Greater Halden Bay" or "Halden Bay City" is that place, not the city.
3. Several places of the city's name in the country: the figure is the city's only when
   the city's own region is named (as a qualifier, or anywhere in the source) and no
   other place of that name lies in that region. Otherwise it is dropped (owner).
4. When only the name without area words matches, the words removed decide: "city",
   "municipal", "urban" mean the city; "greater", "metropolitan", "district" mean an area
   containing it; "rural", "suburban", "ward" mean neither, and the figure is dropped.
5. A name merely containing the city's name counts only under rule 4: "North Halden Bay"
   is dropped.
6. Places of one name on both sides of `nearby_km` are unresolved.
National and state figures match the country or region name exactly, never by containment.
A national figure may also name the city's own region, since some countries are made of
nations that the gazetteer lists as regions ("England" in the United Kingdom), or the
country by its initials ("UK", "USA") or ISO code (owner, BD-46). Generic: no place data.
A state or region named as the city itself ("Halden Bay", "Halden Bay region") is the city
when it is not the city's own region by name and the source names the city's own region:
a city that is also an administrative region. The guard keeps a namesake state in another
region or country out (owner, BD-47).

Pure: the caller looks up gazetteer places for `lookup_names(...)` and passes them in.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.domain.models import CityIdentity, GeographyFit
from app.domain.place_names import place_key
from app.domain.vocab import GeographyLevel, GeographyRelation

EARTH_RADIUS_KM = 6371.0
# Generic English words for kinds of area. They name no place, so they carry no city
# data. Each class says what a city name followed or preceded by them refers to (rule 4).
SAME_PLACE_WORDS = frozenset(
    ["city", "cities", "town", "municipal", "municipality", "corporation", "urban", "the", "of"]
)
WIDER_WORDS = frozenset(
    [
        "greater", "metropolitan", "metro", "region", "regional", "district", "districts",
        "division", "zone", "area", "areas", "county", "province", "state", "tehsil", "taluk",
        "taluka", "mandal",
    ]
)  # fmt: skip
NOT_CITY_WORDS = frozenset(["rural", "suburban", "suburbs", "ward", "wards", "block", "circle"])
AREA_WORDS = SAME_PLACE_WORDS | WIDER_WORDS | NOT_CITY_WORDS
# Words that only say a figure is national: removed before comparing with the country name
NATIONAL_WORDS = frozenset(["the", "national", "nationwide", "country", "whole", "all", "of"])
_DASHES = chr(0x2013) + chr(0x2014)  # en and em dash
_SEGMENT = re.compile(rf"\s*(?:,|;|\(|\)|/| [-{_DASHES}] )\s*")
WordClass = Literal["same", "wider", "not_city"]


@dataclass(frozen=True)
class PlaceCandidate:
    """A gazetteer place in the city's country whose name matched. `keys`: its stored
    name keys (`ref_place.name_keys`); by default the key of `name`."""

    gazetteer_id: str
    name: str
    lat: float
    lon: float
    admin1_code: str | None = None
    keys: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.keys:
            object.__setattr__(self, "keys", frozenset({place_key(self.name)}))


def _core(text: str) -> str:
    return " ".join(w for w in place_key(text).split() if w not in AREA_WORDS)


SUB_CITY_LEVELS = frozenset({GeographyLevel.SUB_CITY_AREA, GeographyLevel.SUB_CITY_POPULATION})
INSIDE_LEVELS = frozenset({GeographyLevel.CITY_WIDE, *SUB_CITY_LEVELS})


def city_named(city: CityIdentity, texts: Sequence[str]) -> bool:
    """The city's name, ASCII name or a real alternate name (an older spelling), as whole words,
    in any of the texts. Codes and short forms are not used (D2-4; owner, BD-51)."""
    return any(_mentions(t, n) for t in texts for n in city.names)


# Levels whose area must be named in the evidence (owner, BD-22): the city, its metro
# region or a district. Sub-city levels already need the city named (D2-4); a country or
# state is checked by name against the city's own.
NAMED_LEVELS = frozenset(
    {GeographyLevel.CITY_WIDE, GeographyLevel.METRO_REGION, GeographyLevel.DISTRICT}
)


def area_named(geography_name: str, city: CityIdentity, texts: Sequence[str]) -> bool:
    """The labelled area is named, as whole words, in the located quote or a located
    label passage: the label as written, its name without area words ("Halden Bay" for
    "Halden Bay City"), or, for the city itself, the city's name or ASCII name. The city
    in the extractor's context is not evidence (BD-22)."""
    names = [geography_name, _core(geography_name)]
    if any(_same_name(geography_name, n, AREA_WORDS) for n in city.names):
        names += list(city.names)
    return any(_mentions(t, n) for t in texts for n in names if n and n.strip())


def region_named(city: CityIdentity, text: str) -> bool:
    """The city's own region (admin-1) named, as whole words, in `text` (rule 3)."""
    return _mentions(text, city.admin1_name)


def _segments(geography_name: str) -> list[str]:
    return [s for s in _SEGMENT.split(geography_name.strip()) if s.strip()]


def lookup_names(geography_name: str) -> list[str]:
    """Name keys to look up: the leading segment as written and without area words, then
    the whole name likewise ("Port Ostra district" -> "port ostra district", "port ostra")."""
    segments = _segments(geography_name) or [geography_name]
    names: list[str] = []
    for text in (segments[0], geography_name):
        for candidate in (place_key(text), _core(text)):
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
    key, wanted = f" {place_key(name)} ", place_key(part or "")
    return bool(wanted) and f" {wanted} " in key


def _word_class(words: set[str]) -> WordClass | None:
    """Rule 4: what the area words around a city name say; None when a word is not an
    area word (for example "north"), so the name is not the city's."""
    if not words or not words <= AREA_WORDS:
        return "same" if not words else None
    if words & NOT_CITY_WORDS:
        return "not_city"
    return "wider" if words & WIDER_WORDS else "same"


def _city_fit(level: GeographyLevel, words: WordClass | None, city: CityIdentity) -> GeographyFit:
    rel = GeographyRelation
    if words is None or words == "not_city":
        return GeographyFit(relation=rel.UNRESOLVED)
    inside = words == "same" and level in INSIDE_LEVELS
    return GeographyFit(
        relation=rel.CITY if inside else rel.CONTAINS_CITY, place_name=city.name, distance_km=0
    )


def _distance_fit(
    city: CityIdentity, places: Sequence[PlaceCandidate], nearby_km: float
) -> GeographyFit:
    """Rule 6: one name for places both near and far cannot be placed."""
    rel = GeographyRelation
    km = {p.gazetteer_id: distance_km(city.lat, city.lon, p.lat, p.lon) for p in places}
    near = [p for p in places if km[p.gazetteer_id] <= nearby_km]
    if near and len(near) < len(places):
        return GeographyFit(relation=rel.UNRESOLVED)
    nearest = min(places, key=lambda p: km[p.gazetteer_id])
    return GeographyFit(
        relation=rel.NEARBY if near else rel.ELSEWHERE,
        place_name=nearest.name,
        distance_km=round(km[nearest.gazetteer_id]),
    )


def _own_qualifiers(city: CityIdentity) -> set[str]:
    names = (city.name, city.ascii_name, city.admin1_name, city.admin2_name, city.country_name)
    return {k for n in names if n and (k := _core(n))}


def _local_fit(
    level: GeographyLevel,
    geography_name: str,
    city: CityIdentity,
    candidates: Sequence[PlaceCandidate],
    nearby_km: float,
    region_in_source: bool,
    city_named_in_evidence: bool = False,
) -> GeographyFit:
    rel = GeographyRelation
    segments = _segments(geography_name)
    if not segments:
        return GeographyFit(relation=rel.UNRESOLVED)
    head, qualifiers = segments[0], segments[1:]
    own = _own_qualifiers(city)
    region_keys = {k for n in (city.admin1_name, city.admin2_name) if n and (k := _core(n))}
    qualifier_keys = [k for q in qualifiers if (k := _core(q))]
    if any(k not in own for k in qualifier_keys):  # rule 1
        return GeographyFit(relation=rel.UNRESOLVED)
    region_settled = region_in_source or any(k in region_keys for k in qualifier_keys)

    full, core = place_key(head), _core(head)
    hits = [c for c in candidates if full in c.keys]  # rule 2
    removed: set[str] = set()
    if not hits and core:
        hits = [c for c in candidates if core in c.keys]
        removed = set(full.split()) - set(core.split())
    if hits:
        others = [c for c in hits if c.gazetteer_id != city.gazetteer_id]
        if len(others) == len(hits):
            return _distance_fit(city, others, nearby_km)
        if others and (  # rule 3
            not region_settled or any(c.admin1_code == city.admin1_code for c in others)
        ):
            return GeographyFit(relation=rel.UNRESOLVED)
        return _city_fit(level, _word_class(removed), city)
    # Rule 5: nothing in the gazetteer; the city's name inside the label, area words only
    for name in city.names:
        city_words = place_key(name).split()
        if city_words and _mentions(head, name):
            rest = [w for w in full.split()]
            for w in city_words:
                rest.remove(w)
            words = _word_class(set(rest))
            if words is None and city_named_in_evidence and _within_city(full, name):
                # Rule 7 (BD-51): "a community in X", "slums of X city": a group or part
                # of the city, never the whole city
                return GeographyFit(
                    relation=rel.CITY, place_name=city.name, distance_km=0,
                    level=GeographyLevel.SUB_CITY_POPULATION,
                )  # fmt: skip
            return _city_fit(level, words, city)
    return GeographyFit(relation=rel.UNRESOLVED)


WITHIN = ("in", "of", "within", "across")


def _within_city(label_key: str, city_name: str) -> bool:
    """The label ends with "<in|of|within|across> [the] <city> [city]" after other words."""
    key = place_key(city_name)
    for prep in WITHIN:
        for tail in (f"{prep} {key}", f"{prep} the {key}", f"{prep} {key} city"):
            if label_key.endswith(" " + tail) and len(label_key) > len(tail) + 1:
                return True
    return False


_INITIALS_SKIP = frozenset(["of", "the", "and"])


def _initials(name: str) -> str:
    """'United Kingdom' -> 'UK', 'United States of America' -> 'USA'; one word gives ''."""
    words = [w for w in place_key(name).split() if w not in _INITIALS_SKIP]
    return "".join(w[0] for w in words).upper() if len(words) > 1 else ""


def _country_code(label: str, city: CityIdentity) -> bool:
    """The label is the country's initials or ISO-3 code ("U.K.", "UK", "GBR")."""
    words = [w for w in label.split() if w.casefold() != "the"]  # "the UK"
    compact = "".join(ch for ch in "".join(words) if ch.isalnum()).upper()
    codes = {c for c in (_initials(city.country_name), city.country_iso3.upper()) if c}
    return bool(compact) and compact in codes


def _same_name(label: str, name: str | None, ignore: frozenset[str]) -> bool:
    """Exact match after removing generic words, never containment ("South X" is not X)."""
    if not name:
        return False

    def bare(text: str) -> str:
        return " ".join(w for w in place_key(text).split() if w not in ignore)

    wanted = bare(name)
    return bool(wanted) and bare(label) == wanted


# Words that may stand beside a city's name when the city is itself a region (BD-47):
# "Halden Bay region" yes; "Greater Halden Bay" or "Halden Bay county" no, as they
# name a wider area.
CITY_REGION_WORDS = SAME_PLACE_WORDS | frozenset(["region", "regional"])


def _region_is_the_city(geography_name: str, city: CityIdentity) -> bool:
    return any(_same_name(geography_name, name, CITY_REGION_WORDS) for name in city.names)


def geography_fit(
    level: GeographyLevel,
    geography_name: str,
    city: CityIdentity,
    candidates: Sequence[PlaceCandidate],
    nearby_km: float,
    city_named_in_evidence: bool = False,
    region_in_source: bool = False,
) -> GeographyFit:
    """`city_named_in_evidence`: the city's own name is in the located quote or a located
    label passage (`city_named`). A sub-city figure needs it, because a part of a city
    is only the researched city's part when the evidence says so (owner, D2-4).
    `region_in_source`: the source names the city's own region (`region_named`, rule 3)."""
    rel = GeographyRelation
    if level in SUB_CITY_LEVELS:
        if city_named_in_evidence:
            return GeographyFit(relation=rel.CITY, place_name=city.name, distance_km=0)
        return GeographyFit(relation=rel.UNRESOLVED)
    if level is GeographyLevel.GLOBAL:
        return GeographyFit(relation=rel.CONTAINS_CITY)
    if level is GeographyLevel.NATIONAL:
        if _same_name(geography_name, city.country_name, NATIONAL_WORDS) or _country_code(
            geography_name, city
        ):
            return GeographyFit(relation=rel.CONTAINS_CITY, place_name=city.country_name)
        if _same_name(geography_name, city.admin1_name, NATIONAL_WORDS):  # a nation-region
            return GeographyFit(relation=rel.CONTAINS_CITY, place_name=city.admin1_name)
        return GeographyFit(relation=rel.ELSEWHERE)
    if level is GeographyLevel.STATE_PROVINCE:
        if _same_name(geography_name, city.admin1_name, AREA_WORDS):
            return GeographyFit(relation=rel.CONTAINS_CITY, place_name=city.admin1_name)
        if region_in_source and _region_is_the_city(geography_name, city):
            return GeographyFit(relation=rel.CITY, place_name=city.name, distance_km=0)
        return GeographyFit(relation=rel.ELSEWHERE)
    return _local_fit(
        level, geography_name, city, candidates, nearby_km, region_in_source,
        city_named_in_evidence,
    )  # fmt: skip
