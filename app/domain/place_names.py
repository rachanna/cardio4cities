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


MIN_ALTERNATE_CHARS = 5  # shorter alternates are codes or short forms
_NAME_CHARS = frozenset(" -'." + chr(0x2019))


def real_alternate_names(alternates: list[str], *own: str) -> list[str]:
    """The gazetteer's alternate names that are names (BD-51): letters with spaces,
    hyphens, apostrophes or full stops, at least MIN_ALTERNATE_CHARS long, starting with
    a capital but not written in capitals (codes), and not the city's own name again.
    Older or other forms of the name then count as the city in the evidence; codes and
    short forms, the reason D2-4 left them out, still do not."""
    seen = {place_key(n) for n in own if n}
    kept: list[str] = []
    for name in alternates:
        name = name.strip()
        key = place_key(name)
        if (
            len(name) >= MIN_ALTERNATE_CHARS
            and all(ch.isalpha() or ch in _NAME_CHARS for ch in name)
            and name[0].isupper()  # a proper name, not a lower-case romanisation
            and not name.isupper()
            and key
            and key not in seen
        ):
            seen.add(key)
            kept.append(name)
    return kept


def place_keys(*names: str | None) -> list[str]:
    """The distinct, non-empty keys of several names (a place's name, ASCII name and
    alternate names), sorted."""
    return sorted({k for n in names if n and (k := place_key(n))})
