"""Entity resolution at run time (LLD-2 §6, R-43, AT-26): our resolver assigns entity IDs
before any graph write (HD-06). One entity per real-world thing per city, across
sources and runs; an uncertain match never merges.

Order (BD-24): an acronym defined in the source resolves through its long form, before
any alias another source registered; alias hit; normalised key; the same significant
words in any order (organisations, programmes, policies); otherwise a new entity.
Embedding similarity never merges, it only logs a pair for review. A generic name
("Department of Health") joins only within its own source and registers no city-wide
alias. Every other form seen becomes an alias.
"""

import logging
from dataclasses import dataclass, field

from app.domain.ids import graph_uuid
from app.domain.models import CityIdentity, Entity
from app.domain.params import EntityParams
from app.domain.vocab import EntityType, GeographyLevel
from app.ports.embeddings import EmbeddingsPort
from app.ports.errors import PortError
from app.ports.repos import EntityRepo
from app.workflow.budget import BudgetExhaustedError, BudgetLedger
from app.workflow.ids import new_id
from app.workflow.rules.entity_resolution import (
    cosine,
    is_acronym,
    is_candidate,
    is_generic,
    normalized_key,
    word_set_key,
)

WORD_SET_TYPES = frozenset({EntityType.ORGANIZATION, EntityType.PROGRAMME, EntityType.POLICY})

log = logging.getLogger(__name__)


@dataclass
class EntityResolver:
    repo: EntityRepo
    embeddings: EmbeddingsPort
    ledger: BudgetLedger
    params: EntityParams
    candidates: list[tuple[str, str, float]] = field(default_factory=list)  # for review
    _vectors: dict[str, list[float]] = field(default_factory=dict)  # entity_id -> name vector

    async def ensure_city(self, city: CityIdentity) -> str:
        """The city is one Place entity, so every edge into it meets at one node."""
        entity_id = await self._create(
            city.city_id,
            city.name,
            EntityType.PLACE,
            {"gazetteer_id": city.gazetteer_id, "level": GeographyLevel.CITY_WIDE.value},
        )
        for form in {city.name, city.ascii_name}:
            await self.repo.add_alias(city.city_id, form, entity_id, "exact", None)
        return entity_id

    async def ensure_indicator(self, city_id: str, code: str, name: str) -> str:
        key = normalized_key(code)
        found = await self.repo.by_key(city_id, EntityType.INDICATOR.value, key)
        if found:
            return found
        entity = Entity(
            entity_id=new_id("ent"),
            city_id=city_id,
            entity_type=EntityType.INDICATOR,
            canonical_name=name,
            normalized_key=key,
            graph_uuid="",
            attributes={"indicator_code": code},
        )
        entity = entity.model_copy(update={"graph_uuid": graph_uuid(entity.entity_id)})
        return await self.repo.add_entity(entity)

    async def resolve(
        self,
        city_id: str,
        surface: str,
        entity_type: EntityType,
        acronyms: dict[str, str] | None = None,
        source_id: str | None = None,
    ) -> str:
        """`acronyms`: ACR -> long name defined in the claim's source (LLD-2 §6 step 3).
        `source_id`: the claim's source, the scope of a generic name (BD-24)."""
        surface = " ".join(surface.split())
        acronyms = acronyms or {}
        defined = is_acronym(surface) and surface in acronyms
        # 1. alias hit, when it names an entity of this type. An acronym this source
        # defines means what this source says, not what another source's alias says.
        if not defined:
            hit = await self.repo.alias(city_id, surface)
            if hit and await self._is_type(hit, entity_type):
                return hit
        name, method = (acronyms[surface], "acronym") if defined else (surface, "normalized")
        generic = entity_type in WORD_SET_TYPES and is_generic(name)
        key = normalized_key(name)
        if generic:  # any city's, state's or country's body: one per source (BD-24)
            key = f"{key}@{source_id or 'unknown'}"
        # 2. normalised key
        entity_id = await self.repo.by_key(city_id, entity_type.value, key)
        # 3. the same significant words in any order
        if entity_id is None and entity_type in WORD_SET_TYPES and not generic:
            entity_id = await self._word_set_match(city_id, name, entity_type)
        if entity_id is None and entity_type is not EntityType.PERSON:
            await self._log_candidate(city_id, name, entity_type)  # never a merge
        if entity_id is None:
            entity_id = await self._create(city_id, name, entity_type, {}, key)
            method = "exact" if method != "acronym" else method
        if generic:
            return entity_id  # no city-wide alias: another source's name is not this one
        await self.repo.add_alias(city_id, surface, entity_id, method, None)
        if name != surface:
            await self.repo.add_alias(city_id, name, entity_id, "normalized", None)
        for acr, long_name in acronyms.items():  # the long form's acronym joins the same entity
            if normalized_key(long_name) == normalized_key(name) and acr != surface:
                await self.repo.add_alias(city_id, acr, entity_id, "acronym", None)
        return entity_id

    async def _word_set_match(self, city_id: str, name: str, entity_type: EntityType) -> str | None:
        wanted = word_set_key(name)
        for entity in await self.repo.entities(city_id, entity_type.value):
            if "@" not in entity.normalized_key and word_set_key(entity.canonical_name) == wanted:
                return entity.entity_id
        return None

    async def _is_type(self, entity_id: str, entity_type: EntityType) -> bool:
        found = (await self.repo.get([entity_id])).get(entity_id)
        return found is not None and found.entity_type is entity_type

    async def _create(
        self,
        city_id: str,
        name: str,
        entity_type: EntityType,
        attributes: dict[str, object],
        key: str | None = None,
    ) -> str:
        entity_id = new_id("ent")
        entity = Entity(
            entity_id=entity_id,
            city_id=city_id,
            entity_type=entity_type,
            canonical_name=name,
            normalized_key=key or normalized_key(name),
            graph_uuid=graph_uuid(entity_id),
            attributes=attributes,
        )
        return await self.repo.add_entity(entity)

    async def _log_candidate(self, city_id: str, name: str, entity_type: EntityType) -> None:
        """A close pair is logged for review and never merged (owner, BD-24). A failed or
        unaffordable embedding skips the log: nothing depends on it."""
        existing = await self.repo.entities(city_id, entity_type.value)
        if not existing:
            return
        try:
            missing = [e for e in existing if e.entity_id not in self._vectors]
            texts = [name, *(e.canonical_name for e in missing)]
            await self.ledger.reserve("model")
            vectors = await self.embeddings.embed(texts)
        except (PortError, BudgetExhaustedError) as exc:
            log.warning("entity embedding skipped (%s)", type(exc).__name__)
            return
        for entity, vector in zip(missing, vectors[1:], strict=True):
            self._vectors[entity.entity_id] = vector
        best = max(existing, key=lambda e: cosine(vectors[0], self._vectors[e.entity_id]))
        score = cosine(vectors[0], self._vectors[best.entity_id])
        if is_candidate(score, self.params):  # IDs and score only: names come from fetched text
            self.candidates.append((best.entity_id, city_id, round(score, 4)))
            log.info("entity candidate pair for review: %s score %.3f", best.entity_id, score)
