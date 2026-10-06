"""Other-place rule for source selection (BD-15): a search hit whose title, snippet or URL
names another city or town of the country (a gazetteer place of at least
`select.other_place_min_population` people) and names neither the target city (any of its
gazetteer names), its admin-1 region nor its country is ranked after the others. It is
never excluded, and a national or state document, which names the country or the
region, is unaffected. Search text only ranks candidates; it never becomes evidence (R-58).

Matching is whole-word: as written in the title and snippet, case-insensitive on the
words of the URL (names of four letters or more there, to keep short words out).

`names_city` (BD-50): the hit names the city itself (its gazetteer names, not its region
or country), for local-first selection."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.models import CityIdentity

URL_MIN_CHARS = 4


def _pattern(names: Iterable[str], flags: int = 0) -> re.Pattern[str] | None:
    ordered = sorted({n for n in names if n}, key=len, reverse=True)
    if not ordered:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, ordered)) + r")(?!\w)", flags)


def _url_words(url: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", " ", url.split("://", 1)[-1])


@dataclass(frozen=True)
class PlaceMatcher:
    own_text: re.Pattern[str] | None
    own_url: re.Pattern[str] | None
    other_text: re.Pattern[str] | None
    other_url: re.Pattern[str] | None
    city_text: re.Pattern[str] | None = None
    city_url: re.Pattern[str] | None = None

    def names_city(self, title: str, snippet: str, url: str) -> bool:
        """The hit's title, snippet or URL names the city itself (BD-50)."""
        return bool(
            (self.city_text is not None and self.city_text.search(f"{title}\n{snippet}"))
            or (self.city_url is not None and self.city_url.search(_url_words(url)))
        )

    def names_other_place(self, title: str, snippet: str, url: str) -> bool:
        text, words = f"{title}\n{snippet}", _url_words(url)

        def hit(text_p: re.Pattern[str] | None, url_p: re.Pattern[str] | None) -> bool:
            return bool(
                (text_p is not None and text_p.search(text))
                or (url_p is not None and url_p.search(words))
            )

        return not hit(self.own_text, self.own_url) and hit(self.other_text, self.other_url)


def place_matcher(city: CityIdentity, places: Iterable[Mapping[str, Any]]) -> PlaceMatcher:
    """`places`: the country's gazetteer rows (name, ascii_name, alternate_names)."""
    rows = list(places)
    names = {city.name, city.ascii_name}
    for row in rows:
        if str(row["gazetteer_id"]) == city.gazetteer_id:
            names |= {a for a in row.get("alternate_names") or [] if len(a) >= 3}
    own = names | {city.admin1_name or "", city.country_name}
    own_folded = {n.casefold() for n in own if n}
    others = {
        n
        for row in rows
        if str(row["gazetteer_id"]) != city.gazetteer_id
        for n in (row["name"], row["ascii_name"])
        if n and n.casefold() not in own_folded
    }

    def long(names: set[str]) -> set[str]:
        return {n for n in names if len(n) >= URL_MIN_CHARS}

    return PlaceMatcher(
        own_text=_pattern(own, re.IGNORECASE),  # the city's own names in any case (BD-17)
        own_url=_pattern(long(own), re.IGNORECASE),
        other_text=_pattern(others),
        other_url=_pattern(long(others), re.IGNORECASE),
        city_text=_pattern(names, re.IGNORECASE),
        city_url=_pattern(long(names), re.IGNORECASE),
    )
