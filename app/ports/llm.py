from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


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


class LLMResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    parsed: BaseModel
    raw_text: str
    model_id: str
    family: str
    tokens_in: int
    tokens_out: int
    cost_micro_usd: int


class LLMPort(Protocol):
    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        """Return output parsed into `schema`; raise LLMOutputValidationError if it does not fit."""
        ...
