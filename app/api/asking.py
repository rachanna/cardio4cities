"""Builds what one question needs (D3-2, LLD-5): the stores, the model bindings, and a
budget ledger of its own (owner, BD-38: `retrieval.wall_clock_s` and
`retrieval.max_cost_micro_usd`). `app/query` stays independent of the workflow; this
composition is where the two meet."""

from collections.abc import Sequence
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import yaml
from fastapi import Request

from app.api import reading
from app.api.errors import dependency_unavailable
from app.domain.params import BadgeParams, ConfidenceParams
from app.ports.llm import LLMParams
from app.query.types import AskDeps, AskParams, ModelRole
from app.settings import Settings
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.deps import chunk_collection, claim_collection
from app.workflow.llm import OUTPUT_CEILING
from app.workflow.runner import REFERENCE_DIR, role_bindings

ROLES = ("classifier", "answerer")


@cache
def stopwords(directory: Path = REFERENCE_DIR) -> frozenset[str]:
    raw = yaml.safe_load((directory / "keyword_stopwords.yaml").read_text(encoding="utf-8"))
    return frozenset(str(w).casefold() for w in raw["words"])


def question_ledger(wall_clock_s: float, max_cost_micro_usd: int) -> BudgetLedger:
    """One question's own ledger: model calls and embeddings only (searches and fetches
    are never made while answering, so their limits are 1 and never reached)."""
    return BudgetLedger(
        BudgetLimits(
            wall_clock_s=wall_clock_s,
            searches=1,
            fetches=1,
            tokens=0,
            cost_micro_usd=max_cost_micro_usd,
            wind_down_at=1.0,
        )
    )


def roles_for(settings: Settings, names: Sequence[str] = ROLES) -> dict[str, ModelRole]:
    """Model bindings of the profile: the classifier and answerer by default (also used by
    the golden set), the reporter for the report (BD-40)."""
    bindings = role_bindings(settings)
    roles = {}
    for role in names:
        binding = bindings[role].primary
        roles[role] = ModelRole(
            provider=binding.provider,
            family=binding.family,
            params=LLMParams(
                model=binding.model,
                max_output_tokens=OUTPUT_CEILING[role],
                effort=binding.effort,
                temperature=binding.temperature,
            ),
        )
    return roles


async def ask_deps(request: Request, city_row: dict[str, object], graph_on: bool) -> AskDeps:
    container = request.app.state.container
    settings = container.settings
    cfg = settings.config
    store = reading.relational(request)
    roles = roles_for(settings)
    if any(role.provider not in container.llm for role in roles.values()):
        raise dependency_unavailable("llm", "Question answering is not available right now.")
    r = cfg.retrieval
    city_id = str(city_row["city_id"])
    # Collections are named after the embeddings adapter's key, as a run names them
    key = container.embeddings.key if container.embeddings else cfg.embeddings.key
    return AskDeps(
        relational=store,
        vector=container.vector,
        graph=container.graph,
        embeddings=container.embeddings,
        embedding_model=cfg.embeddings.model,
        llm=container.llm,
        roles=roles,
        ledger=question_ledger(r.wall_clock_s, r.max_cost_micro_usd),
        params=AskParams(
            rrf_k=r.rrf_k,
            r2_top=r.r2_top,
            r2_trigram_min=r.r2_trigram_min,
            r3_top=r.r3_top,
            r3_mentions_top=r.r3_mentions_top,
            max_facts=r.max_facts,
            max_mentions=r.max_mentions,
            max_per_slot=r.max_per_slot,
            mentions_only_if_facts_below=r.mentions_only_if_facts_below,
        ),
        badge=BadgeParams(**cfg.badge.model_dump()),
        confidence=ConfidenceParams(**cfg.confidence.model_dump()),
        stopwords=stopwords(),
        slots={s.slot_id: s for s in await store.reference.slots()},
        indicators={i.code: i for i in await store.reference.indicators()},
        city=await store.runs.city_identity(city_id),
        city_id=city_id,
        run_id=str(city_row["latest_run_id"]),
        claim_collection=claim_collection(key),
        chunk_collection=chunk_collection(key),
        today=datetime.now(UTC).date(),
        graph_on=graph_on,
    )
