from typing import Protocol

from pydantic import BaseModel, ConfigDict


class LLMParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    temperature: float
    max_output_tokens: int


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
