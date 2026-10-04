"""Entity resolution rules (LLD-2 §6, R-43, AT-26). Pure: the resolver
(`app/workflow/entities.py`) does the lookups and writes.

Steps, in order (BD-24): an acronym the source defines resolves through its long form;
alias hit; normalised key; the same significant words in any order (organisations,
programmes and policies); otherwise a new entity. Embedding similarity never merges: a
close pair is only logged for review. A name made only of generic words joins only
within its own source.
"""

import math
import re
import unicodedata
from collections.abc import Sequence

from app.domain.params import EntityParams
from app.workflow.rules.quotes import normalise_text

_LEADING_THE = re.compile(r"^the\s+")
_LEADING_THE_ANY_CASE = re.compile(r"^the\s+", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w]+")
# "Long Name (ACR)" and "ACR (Long Name)": ACR is 2 to 8 capital letters (LLD-2 §6 step 3).
# Text is normalised first (typographic quotes become ASCII), so only ' is matched.
_LONG_THEN_ACR = re.compile(
    r"((?:[A-Z][\w'&.-]*\s+)(?:(?:of|and|for|the|on|in|de|du|des|la|le|&)\s+|[A-Z][\w'&.-]*\s+)*"
    r"[A-Z][\w'&.-]*)\s*\(([A-Z]{2,8})\)"
)
_ACR_THEN_LONG = re.compile(r"\b([A-Z]{2,8})\s*\(([A-Z][^()]{3,80})\)")
_SMALL_WORDS = frozenset(
    ["of", "and", "for", "the", "on", "in", "de", "du", "des", "la", "le", "&"]
)


def _strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalized_key(surface: str) -> str:
    """casefold, no diacritics, no leading "the", punctuation removed, words joined by -."""
    text = _strip_diacritics(normalise_text(surface)).casefold().strip()
    text = _LEADING_THE.sub("", text)
    return "-".join(w for w in _NON_WORD.split(text) if w)


def is_acronym(surface: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2,8}", surface.strip()))


def _initials(long_name: str) -> tuple[str, str]:
    words = re.findall(r"[^\W\d_][\w'.-]*", long_name)
    significant = "".join(w[0] for w in words if w.casefold() not in _SMALL_WORDS)
    every = "".join(w[0] for w in words)
    return significant.upper(), every.upper()


def acronym_fits(long_name: str, acronym: str) -> bool:
    """The acronym is the initials of the long name's words: a pair the text did not
    state as initials is not trusted (precision first)."""
    return acronym in _initials(long_name)


def acronym_pairs(text: str) -> dict[str, str]:
    """ACR -> long name, for every "Long Name (ACR)" or "ACR (Long Name)" whose initials
    fit. An acronym defined two different ways in one source is not trusted."""
    found: dict[str, set[str]] = {}
    plain = normalise_text(text)
    for long_name, acr in _LONG_THEN_ACR.findall(plain):
        found.setdefault(acr, set()).add(long_name.strip())
    for acr, long_name in _ACR_THEN_LONG.findall(plain):
        found.setdefault(acr, set()).add(long_name.strip())
    pairs = {}
    for acr, names in found.items():
        fitting = {n for n in names if acronym_fits(n, acr)} or set()
        trimmed = {_trim_to_acronym(n, acr) for n in names} - {None}
        candidates = fitting | {t for t in trimmed if t}
        keys = {normalized_key(n) for n in candidates}
        if len(keys) == 1:
            pairs[acr] = _LEADING_THE_ANY_CASE.sub("", min(candidates, key=len))
    return pairs


def _trim_to_acronym(long_name: str, acr: str) -> str | None:
    """ "In 2024 the Norvania Health Directorate (NHD)": drop leading words until the
    initials fit."""
    words = long_name.split()
    for start in range(len(words)):
        tail = " ".join(words[start:])
        if acronym_fits(tail, acr) and tail[:1].isupper():
            return tail
    return None


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def is_candidate(score: float, params: EntityParams) -> bool:
    """A pair close enough to log for review; it never merges (owner, BD-24): "City
    Council" and "District Council" score 0.95 with the local model."""
    return score >= params.candidate_threshold


def _significant_words(name: str) -> list[str]:
    text = _strip_diacritics(normalise_text(name)).casefold()
    return [w for w in _NON_WORD.split(text) if w and w not in _SMALL_WORDS]


def word_set_key(name: str) -> str:
    """The significant words in any order: "Health Directorate of Norvania" and
    "Norvania Health Directorate" meet; "Halden Bay City Council" and "Halden Bay
    District Council" do not (owner, BD-24)."""
    return "-".join(sorted(set(_significant_words(name))))


# Words that name a kind of body, not a particular one (BD-24). A name made only of
# these ("Department of Health", "City Council") could be any city's, state's or
# country's body, so it joins only within its own source.
GENERIC_WORDS = frozenset(
    {
        "affairs",
        "agency",
        "authority",
        "board",
        "branch",
        "bureau",
        "cardiovascular",
        "care",
        "center",
        "central",
        "centre",
        "city",
        "clinic",
        "clinics",
        "commission",
        "committee",
        "community",
        "control",
        "council",
        "county",
        "department",
        "development",
        "directorate",
        "disease",
        "diseases",
        "district",
        "division",
        "family",
        "general",
        "government",
        "health",
        "healthcare",
        "heart",
        "hospital",
        "hospitals",
        "hypertension",
        "local",
        "medical",
        "metropolitan",
        "ministry",
        "municipal",
        "municipality",
        "national",
        "ncd",
        "ncds",
        "noncommunicable",
        "office",
        "officer",
        "prevention",
        "primary",
        "program",
        "programme",
        "province",
        "provincial",
        "public",
        "region",
        "regional",
        "screening",
        "secretariat",
        "service",
        "services",
        "social",
        "state",
        "team",
        "town",
        "unit",
        "welfare",
    }
)


def is_generic(name: str) -> bool:
    words = _significant_words(name)
    return bool(words) and all(w in GENERIC_WORDS for w in words)
