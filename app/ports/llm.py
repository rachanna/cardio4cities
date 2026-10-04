from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

# Union of what Claude (`output_config.effort`) and OpenAI (`reasoning.effort`) accept;
# each model accepts a subset, confirmed per binding (BD-05).
Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class LLMParams(BaseModel):
    """Per-call parameters (LLD-3 §2.3, BD-04).

    `temperature` is sent only when set: Claude Sonnet 5.5 and Opus 5.5 reject it,
    so those roles leave it unset and use `effort`. `max_output_tokens` is the API
    ceiling, which also covers thinking or reasoning tokens; the visible output
    limit is enforced by the role's schema.
    """

    model_config = ConfigDict(frozen=True)

    model: str
    max_output_tokens: int
    temperature: float | None = None
    effort: Effort | None = None
    timeout_s: float | None = None  # the run's time left (BD-15); None: the SDK default


class LLMUsage(BaseModel):
    """What one call used and cost (BD-30). `tokens_in` counts every input token, cached
    ones included; `cached_tokens` were read from the provider's prompt cache and
    `cache_write_tokens` written to it; `reasoning_tokens` are part of `tokens_out`."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    tokens_in: int
    tokens_out: int
    cost_micro_usd: int
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0


class LLMResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    parsed: BaseModel
    raw_text: str
    model_id: str
    family: str
    tokens_in: int
    tokens_out: int
    cost_micro_usd: int
    cached_tokens: int = 0  # BD-30
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def usage(self) -> LLMUsage:
        return LLMUsage(
            model_id=self.model_id, tokens_in=self.tokens_in, tokens_out=self.tokens_out,
            cost_micro_usd=self.cost_micro_usd, cached_tokens=self.cached_tokens,
            cache_write_tokens=self.cache_write_tokens, reasoning_tokens=self.reasoning_tokens,
        )  # fmt: skip


class LLMPort(Protocol):
    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        """Return output parsed into `schema`; raise LLMOutputValidationError if it does not fit."""
        ...
