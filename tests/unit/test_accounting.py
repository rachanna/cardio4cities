"""Cost accounting (BD-30; code review RV-049): failed calls that the provider billed are
counted, embeddings count apart from model calls, and cached and reasoning tokens are
kept per model. Fakes only."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.prices import cost_micro_usd, embedding_cost_micro_usd
from app.ports.errors import LLMOutputValidationError
from app.ports.llm import LLMUsage
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.deps import Binding
from app.workflow.limits import LimitedEmbeddings
from app.workflow.llm import _call_once


def ledger() -> BudgetLedger:
    return BudgetLedger(BudgetLimits(420, 64, 60, 1_500_000, 3_000_000, 0.85))


async def test_embeddings_count_apart_from_model_calls() -> None:
    """The ledger showed 130-147 model calls against 58-82 per model: embeddings
    reserved as model calls."""
    book = ledger()
    await book.reserve("embedding")
    await book.record_embedding("text-embedding-3-small", 10_000, 200)
    assert book.model_calls == 0
    assert book.cost_micro_usd == 200
    assert book.by_model["embeddings:text-embedding-3-small"]["tokens_in"] == 10_000


async def test_cached_and_reasoning_tokens_are_kept_per_model() -> None:
    book = ledger()
    await book.record_model("gpt-6-luna", 1_000, 300, 250, cached_tokens=700, reasoning_tokens=200)
    row = book.by_model["gpt-6-luna"]
    assert (row["cached_tokens"], row["reasoning_tokens"], row["calls"]) == (700, 200, 1)


def test_prices_follow_the_cache_rates() -> None:
    assert cost_micro_usd("claude-haiku-4-5-20251001", 1_000, 0, cached_tokens=1_000) == 100
    assert cost_micro_usd("claude-haiku-4-5-20251001", 1_000, 0, cache_write_tokens=1_000) == 1250
    assert cost_micro_usd("gpt-6-luna", 1_000, 0, cached_tokens=1_000) == 100  # full rate
    assert embedding_cost_micro_usd("text-embedding-3-small", 1_000_000) == 20_000
    assert embedding_cost_micro_usd("paraphrase-multilingual-MiniLM-L12-v2", 1_000_000) == 0


async def test_limited_embeddings_record_their_estimated_tokens() -> None:
    recorded: list[int] = []

    class Inner:
        dimension, key = 2, "k"

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0, 1.0] for _ in texts]

    async def record(tokens: int) -> None:
        recorded.append(tokens)

    wrapped = LimitedEmbeddings(Inner(), asyncio.Semaphore(1), record)
    await wrapped.embed(["a" * 400, "b" * 400])
    assert recorded == [200]


class Schema(BaseModel):
    x: int


async def test_a_failed_call_the_provider_billed_is_recorded() -> None:
    """RV-049: usage was recorded only after a successful parse."""
    book = ledger()

    class Failing:
        async def complete(self, *_: Any) -> Any:
            error = LLMOutputValidationError("checker: no structured output", "", truncated=True)
            error.usage = LLMUsage(model_id="gpt-6-luna", tokens_in=900, tokens_out=8000,
                                   cost_micro_usd=4090)  # fmt: skip
            raise error

    deps: Any = type("D", (), {"ledger": book, "llm": {"openai": Failing()}})()
    binding = Binding(provider="openai", model="gpt-6-luna", family="openai", effort="low",
                      temperature=None)  # fmt: skip
    with pytest.raises(LLMOutputValidationError):
        await _call_once(deps, "checker", binding, "s", "u", Schema)
    assert book.cost_micro_usd == 4090
    assert book.by_model["gpt-6-luna"]["calls"] == 1
