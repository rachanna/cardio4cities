"""LLMPort over Claude (official SDK 1.x). Structured output through `messages.parse`
(strict schema), never forced tool calls: Claude Sonnet 5.5 and Opus 5.5 reject them (BD-05).
Effort goes in `output_config`; temperature, which SDK 1.x removed from the call
signature, goes through `extra_body` for the models that accept it (BD-08)."""

from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from app.domain.prices import cost_micro_usd
from app.ports.errors import LLMOutputValidationError, ProviderUnavailableError
from app.ports.llm import LLMParams, LLMResult, LLMUsage
from app.settings import Settings


class AnthropicLLM:
    family = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        max_retries: int = 2,
        prompt_cache: bool = False,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, max_retries=max_retries
        )
        self._cache = prompt_cache  # llm.prompt_cache (BD-30)

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": params.model,
            "max_tokens": params.max_output_tokens,
            # The system prompt is the same on every call of a role: cached (BD-30). A
            # prefix under the model's minimum is simply not cached
            "system": (
                [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                if self._cache
                else system
            ),
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
                f"{role}: output did not fit the schema", str(exc), truncated=_cut_off(str(exc))
            ) from exc
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as exc:
            raise ProviderUnavailableError(f"anthropic: {type(exc).__name__}") from exc
        except anthropic.APIStatusError as exc:  # 400, 402, 529 and the rest (BD-21)
            raise ProviderUnavailableError(f"anthropic: HTTP {exc.status_code}") from exc
        except anthropic.APIError as exc:
            raise ProviderUnavailableError(f"anthropic: {type(exc).__name__}") from exc
        raw = "".join(b.text for b in response.content if b.type == "text")
        used = _usage(response)
        if response.stop_reason == "refusal":
            error = ProviderUnavailableError(f"anthropic: {role} request declined")
            error.usage = used  # a declined call is still billed (BD-30)
            raise error
        parsed = response.parsed_output
        if parsed is None:
            cut = response.stop_reason == "max_tokens"
            failed = LLMOutputValidationError(f"{role}: no structured output", raw, truncated=cut)
            failed.usage = used
            raise failed
        return LLMResult(parsed=parsed, raw_text=raw, family=self.family, **used.model_dump())


class AnthropicProbe:
    """Health (LLD-4 §7, BD-42): looks up every Claude model the roles use. A model
    lookup is free and spends no tokens; an unknown model ID or a bad key fails it."""

    component = "llm_anthropic"

    def __init__(self, api_key: str, models: list[str], base_url: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=0)
        self._models = models

    async def check(self) -> None:
        for model in self._models:
            await self._client.models.retrieve(model)

    async def close(self) -> None:
        await self._client.close()


def make_probe(settings: Settings) -> AnthropicProbe:
    provider = settings.config.llm.providers["anthropic"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.anthropic.api_key_env is required")
    return AnthropicProbe(settings.secret(provider.api_key_env), settings.models_of("anthropic"))


def make(settings: Settings) -> AnthropicLLM:
    provider = settings.config.llm.providers["anthropic"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.anthropic.api_key_env is required")
    return AnthropicLLM(
        settings.secret(provider.api_key_env), prompt_cache=settings.config.llm.prompt_cache
    )


def _cut_off(detail: str) -> bool:
    """Pydantic's message for JSON that ends early: the output hit the token ceiling."""
    return "EOF while parsing" in detail or "Unterminated string" in detail


def _usage(response: Any) -> LLMUsage:
    """Claude reports uncached input, cache reads and cache writes separately."""
    u = response.usage
    read = getattr(u, "cache_read_input_tokens", None) or 0
    write = getattr(u, "cache_creation_input_tokens", None) or 0
    tokens_in = u.input_tokens + read + write
    return LLMUsage(
        model_id=response.model,
        tokens_in=tokens_in,
        tokens_out=u.output_tokens,
        cost_micro_usd=cost_micro_usd(response.model, tokens_in, u.output_tokens, read, write),
        cached_tokens=read,
        cache_write_tokens=write,
    )
