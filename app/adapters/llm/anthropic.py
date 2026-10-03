"""LLMPort over Claude (official SDK 1.x). Structured output through `messages.parse`
(strict schema), never forced tool calls: Claude Sonnet 5.5 and Opus 5.5 reject them (BD-05).
Effort goes in `output_config`; temperature, which SDK 1.x removed from the call
signature, goes through `extra_body` for the models that accept it (BD-08)."""

from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from app.adapters.llm.prices import cost_micro_usd
from app.ports.errors import LLMOutputValidationError, ProviderUnavailableError
from app.ports.llm import LLMParams, LLMResult
from app.settings import Settings


class AnthropicLLM:
    family = "anthropic"

    def __init__(self, api_key: str, base_url: str | None = None, max_retries: int = 2) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=max_retries
        )

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": params.model,
            "max_tokens": params.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_format": schema,
        }
        if params.effort is not None:
            kwargs["output_config"] = {"effort": params.effort}
        if params.temperature is not None:
            kwargs["extra_body"] = {"temperature": params.temperature}
        try:
            client = (
                self._client.with_options(timeout=params.timeout_s)
                if params.timeout_s is not None
                else self._client
            )
            response = await client.messages.parse(**kwargs)
        except ValidationError as exc:
            raise LLMOutputValidationError(
                f"{role}: output did not fit the schema", str(exc)
            ) from exc
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as exc:
            raise ProviderUnavailableError(f"anthropic: {type(exc).__name__}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in (402, 529):
                raise ProviderUnavailableError(f"anthropic: HTTP {exc.status_code}") from exc
            raise
        raw = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason == "refusal":
            raise ProviderUnavailableError(f"anthropic: {role} request declined")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMOutputValidationError(f"{role}: no structured output", raw)
        usage = response.usage
        return LLMResult(
            parsed=parsed,
            raw_text=raw,
            model_id=response.model,
            family=self.family,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            cost_micro_usd=cost_micro_usd(response.model, usage.input_tokens, usage.output_tokens),
        )


def make(settings: Settings) -> AnthropicLLM:
    provider = settings.config.llm.providers["anthropic"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.anthropic.api_key_env is required")
    return AnthropicLLM(settings.secret(provider.api_key_env))
