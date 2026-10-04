"""R2 keyword (LLD-5 §4.1, BD-36): Postgres full text over claims, the question's words
ORed; plus the claims of entities the question names, found by lookup only."""

import re
from collections.abc import Sequence

from app.domain.entity_names import acronym_fits, is_acronym, normalized_key
from app.query.routes import timed
from app.query.types import AskDeps, RouteResult, Understanding

_WORD = re.compile(r"\w+")


def keywords(question: str, stopwords: frozenset[str], city_names: Sequence[str]) -> list[str]:
    """The question's words for the keyword route (LLD-5 §4.1, BD-36): lower-cased,
    without stop words and without the city's own name, in order, once each."""
    own = {w for name in city_names for w in _WORD.findall(name.casefold())}
    words = [w for w in _WORD.findall(question.casefold()) if w not in stopwords and w not in own]
    return list(dict.fromkeys(words))


def acronyms_in(question: str, u: Understanding) -> list[str]:
    found = [m.text.strip() for m in u.entity_mentions if is_acronym(m.text)]
    found += [w for w in _WORD.findall(question) if is_acronym(w)]
    return list(dict.fromkeys(found))


async def mentioned_entities(deps: AskDeps, question: str, u: Understanding) -> list[str]:
    """Entity IDs the question names, by lookup only: alias, key, trigram similarity, or
    an acronym that is the initials of an entity's name (AT-42)."""
    texts = [m.text.strip() for m in u.entity_mentions if m.text.strip()]
    entities = deps.relational.entities
    found = await entities.match_names(
        deps.city_id, texts, [normalized_key(t) for t in texts], deps.params.r2_trigram_min
    )
    acronyms = acronyms_in(question, u)
    if acronyms:
        for entity_id, name in await entities.names(deps.city_id):
            if any(acronym_fits(name, a) for a in acronyms):
                found.append(entity_id)
    return list(dict.fromkeys(found))


async def r2(deps: AskDeps, question: str, u: Understanding, entity_ids: list[str]) -> RouteResult:
    async def work(route: RouteResult) -> None:
        names = [deps.city.name, deps.city.ascii_name]
        words = keywords(question, deps.stopwords, names)
        found = await deps.relational.research.keyword_claims(
            deps.city_id, deps.run_id, words, deps.params.r2_top
        )
        named = await deps.relational.research.entity_claims(deps.run_id, entity_ids)
        route.candidates = list(dict.fromkeys([*found, *named]))
        if not words and not entity_ids:
            route.status, route.note = "skipped", "no searchable word"

    return await timed(RouteResult("R2"), work)
