"""LLMPort over OpenAI (Responses API, official SDK). Structured output through
`responses.parse`; reasoning models take `reasoning.effort` (BD-05). Running out of
credit is reported as ProviderUnavailableError, so the checker's labelled fallback
takes over instead of the run failing."""

from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from app.adapters.llm.prices import cost_micro_usd
from app.ports.errors import LLMOutputValidationError, ProviderUnavailableError
from app.ports.llm import LLMParams, LLMResult
from app.settings import Settings


class OpenAILLM:
    family = "openai"

    def __init__(self, api_key: str, base_url: str | None = None, max_retries: int = 2) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=max_retries
        )

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": params.model,
            "instructions": system,
            "input": user,
            "text_format": schema,
            "max_output_tokens": params.max_output_tokens,
            "store": False,
        }
        if params.effort is not None:
            kwargs["reasoning"] = {"effort": params.effort}
        if params.temperature is not None:
            kwargs["temperature"] = params.temperature
        try:
            response = await self._client.responses.parse(**kwargs)
        except ValidationError as exc:
            raise LLMOutputValidationError(
                f"{role}: output did not fit the schema", str(exc)
            ) from exc
        except openai.RateLimitError as exc:  # includes insufficient_quota (no credit left)
            raise ProviderUnavailableError(
                f"openai: {getattr(exc, 'code', None) or 'rate limited'}"
            ) from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            raise ProviderUnavailableError(f"openai: {type(exc).__name__}") from exc
        parsed = response.output_parsed
        raw = response.output_text or ""
        if parsed is None:
            raise LLMOutputValidationError(f"{role}: no structured output", raw)
        usage = response.usage
        tokens_in = usage.input_tokens if usage else 0
        tokens_out = usage.output_tokens if usage else 0
        return LLMResult(
            parsed=parsed,
            raw_text=raw,
            model_id=response.model,
            family=self.family,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_micro_usd=cost_micro_usd(response.model, tokens_in, tokens_out),
        )


def make(settings: Settings) -> OpenAILLM:
    provider = settings.config.llm.providers["openai"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.openai.api_key_env is required")
    return OpenAILLM(settings.secret(provider.api_key_env))
