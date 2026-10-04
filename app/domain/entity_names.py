"""Entity name keys (LLD-2 §6, BD-24): normalised keys and acronyms. Pure; shared by
entity resolution in the workflow and entity lookup in question answering (moved from
`workflow/rules/entity_resolution.py`, BD-38)."""

import re
import unicodedata

from app.domain.text import normalise_text

LEADING_THE = re.compile(r"^the\s+")
NON_WORD = re.compile(r"[^\w]+")
SMALL_WORDS = frozenset(["of", "and", "for", "the", "on", "in", "de", "du", "des", "la", "le", "&"])


def strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalized_key(surface: str) -> str:
    """casefold, no diacritics, no leading "the", punctuation removed, words joined by -."""
    text = strip_diacritics(normalise_text(surface)).casefold().strip()
    text = LEADING_THE.sub("", text)
    return "-".join(w for w in NON_WORD.split(text) if w)


def is_acronym(surface: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2,8}", surface.strip()))


def initials(long_name: str) -> tuple[str, str]:
    words = re.findall(r"[^\W\d_][\w'.-]*", long_name)
    significant = "".join(w[0] for w in words if w.casefold() not in SMALL_WORDS)
    every = "".join(w[0] for w in words)
    return significant.upper(), every.upper()


def acronym_fits(long_name: str, acronym: str) -> bool:
    """The acronym is the initials of the long name's words: a pair the text did not
    state as initials is not trusted (precision first)."""
    return acronym in initials(long_name)
