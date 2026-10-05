"""LLMPort over OpenAI (Responses API, official SDK). Structured output through
`responses.parse`; reasoning models take `reasoning.effort` (BD-05). Running out of
credit is reported as ProviderUnavailableError, so the checker's labelled fallback
takes over instead of the run failing."""

from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from app.domain.prices import cost_micro_usd
from app.ports.errors import LLMOutputValidationError, ProviderUnavailableError
from app.ports.llm import LLMParams, LLMResult, LLMUsage
from app.settings import Settings


class OpenAILLM:
    family = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        max_retries: int = 2,
        prompt_cache: bool = False,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=max_retries
        )
        self._cache = prompt_cache  # llm.prompt_cache (BD-30)

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
        if self._cache:  # OpenAI caches long prefixes itself; one key per role helps it hit
            kwargs["prompt_cache_key"] = f"c4c-{role}"
        try:
            client = (
                self._client.with_options(timeout=params.timeout_s)
                if params.timeout_s is not None
                else self._client
            )
            response = await client.responses.parse(**kwargs)
        except ValidationError as exc:
            raise LLMOutputValidationError(
                f"{role}: output did not fit the schema", str(exc), truncated=_cut_off(str(exc))
            ) from exc
        except openai.RateLimitError as exc:  # includes insufficient_quota (no credit left)
            raise ProviderUnavailableError(
                f"openai: {getattr(exc, 'code', None) or 'rate limited'}"
            ) from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            raise ProviderUnavailableError(f"openai: {type(exc).__name__}") from exc
        except openai.APIStatusError as exc:  # 400 and the rest (BD-21)
            raise ProviderUnavailableError(f"openai: HTTP {exc.status_code}") from exc
        except openai.APIError as exc:
            raise ProviderUnavailableError(f"openai: {type(exc).__name__}") from exc
        parsed = response.output_parsed
        raw = response.output_text or ""
        used = _usage(response)
        if parsed is None:
            cut = getattr(response, "status", None) == "incomplete"
            failed = LLMOutputValidationError(f"{role}: no structured output", raw, truncated=cut)
            failed.usage = used  # a cut-off call is still billed (BD-30)
            raise failed
        return LLMResult(parsed=parsed, raw_text=raw, family=self.family, **used.model_dump())


class OpenAIProbe:
    """Health (LLD-4 §7, BD-42): looks up each OpenAI model the roles use (or the
    embedding model). A model lookup is free; an unknown model or a bad key fails it."""

    def __init__(
        self, component: str, api_key: str, models: list[str], base_url: str | None = None
    ) -> None:
        self.component = component
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self._models = models

    async def check(self) -> None:
        for model in self._models:
            await self._client.models.retrieve(model)

    async def close(self) -> None:
        await self._client.close()


def make_probe(settings: Settings) -> OpenAIProbe:
    provider = settings.config.llm.providers["openai"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.openai.api_key_env is required")
    key = settings.secret(provider.api_key_env)
    return OpenAIProbe("llm_openai", key, settings.models_of("openai"))


def make(settings: Settings) -> OpenAILLM:
    provider = settings.config.llm.providers["openai"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.openai.api_key_env is required")
    return OpenAILLM(
        settings.secret(provider.api_key_env), prompt_cache=settings.config.llm.prompt_cache
    )


def _cut_off(detail: str) -> bool:
    """Pydantic's message for JSON that ends early: the output hit the token ceiling."""
    return "EOF while parsing" in detail or "Unterminated string" in detail


def _usage(response: Any) -> LLMUsage:
    """OpenAI counts cached tokens inside `input_tokens` and reasoning inside output."""
    u = response.usage
    tokens_in = u.input_tokens if u else 0
    tokens_out = u.output_tokens if u else 0
    details_in = getattr(u, "input_tokens_details", None)
    details_out = getattr(u, "output_tokens_details", None)
    cached = (getattr(details_in, "cached_tokens", None) or 0) if details_in else 0
    reasoning = (getattr(details_out, "reasoning_tokens", None) or 0) if details_out else 0
    return LLMUsage(
        model_id=response.model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_micro_usd=cost_micro_usd(response.model, tokens_in, tokens_out, cached),
        cached_tokens=cached,
        reasoning_tokens=reasoning,
    )
