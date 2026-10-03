"""One normal form for place names (BD-17), used both to store gazetteer names
(`ref_place.name_keys`) and to look up the names written in claims, so the two always meet:
"St. Ostra" and "st ostra" are the same key; "Halden Bay's" is "halden bay".

Unicode NFKC, case folded, typographic apostrophes unified, a possessive "'s" dropped, and
only the words kept (letters and digits, with an apostrophe, full stop or hyphen allowed
between letters)."""

import re
import unicodedata

_APOSTROPHES = "'" + chr(0x2019)  # straight and typographic
_POSSESSIVE = re.compile(rf"[{_APOSTROPHES}]s\b")
_WORD = re.compile(rf"[^\W_]+(?:[{_APOSTROPHES}.-][^\W_]+)*")


def place_key(text: str) -> str:
    plain = _POSSESSIVE.sub("", unicodedata.normalize("NFKC", text).casefold())
    return " ".join(_WORD.findall(plain))


def place_keys(*names: str | None) -> list[str]:
    """The distinct, non-empty keys of several names (a place's name, ASCII name and
    alternate names), sorted."""
    return sorted({k for n in names if n and (k := place_key(n))})
