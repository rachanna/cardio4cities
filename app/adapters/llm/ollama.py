"""Ollama adapter (E-01, BD-54): an open-weight model hosted on this machine.

It calls Ollama's native chat API, not its OpenAI-compatible endpoint, because only the
native API takes the context window per request. Ollama's default window is small, and a
longer prompt loses its beginning without any error; extraction prompts are long. So the
window is always sent (`llm.providers.ollama.num_ctx`), and a call whose prompt and output
filled it is refused, because the prompt may have been cut. A local model costs nothing,
which the adapter states explicitly: unknown models are otherwise priced at the highest
listed rate (`domain/prices.py`).
"""

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.ports.errors import LLMOutputValidationError, ProviderUnavailableError
from app.ports.llm import LLMParams, LLMResult, LLMUsage
from app.settings import Settings

# Used only when the run gives no time left (params.timeout_s is None)
DEFAULT_TIMEOUT_S = 300.0


class OllamaLLM:
    family = "ollama"  # the run labels verdicts with the binding's declared family

    def __init__(
        self,
        base_url: str,
        num_ctx: int,
        keep_alive: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._num_ctx = num_ctx
        self._keep_alive = keep_alive
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport)

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        options: dict[str, Any] = {
            "num_ctx": self._num_ctx,
            "num_predict": params.max_output_tokens,
        }
        if params.temperature is not None:
            options["temperature"] = params.temperature
        body: dict[str, Any] = {
            "model": params.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema.model_json_schema(),  # constrained to the role's schema
            "stream": False,
            # BD-55: `effort` switches a reasoning model's thinking on. Ollama returns the
            # thinking apart from the answer, so the answer still fits the schema. A model
            # that cannot think is bound without effort.
            "think": params.effort not in (None, "none"),
            "options": options,
        }
        if self._keep_alive is not None:
            body["keep_alive"] = self._keep_alive
        timeout = params.timeout_s if params.timeout_s is not None else DEFAULT_TIMEOUT_S
        try:
            response = await self._client.post("/api/chat", json=body, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("ollama: timed out") from exc
        except httpx.HTTPError as exc:  # not running, connection refused, reset
            raise ProviderUnavailableError(f"ollama: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError(f"ollama: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError("ollama: response is not JSON") from exc

        raw = str((data.get("message") or {}).get("content") or "")
        used = _usage(data, params.model)
        cut = data.get("done_reason") == "length"
        if used.tokens_in + used.tokens_out >= self._num_ctx:
            failed = LLMOutputValidationError(
                f"{role}: prompt and output filled the context window ({self._num_ctx} "
                f"tokens), so the prompt may have been cut; raise llm.providers.ollama."
                f"num_ctx or send less",
                raw,
                truncated=cut,
            )
            failed.usage = used  # a failed call still used tokens (BD-30)
            raise failed
        try:
            parsed = schema.model_validate_json(raw)
        except ValidationError as exc:
            failed = LLMOutputValidationError(
                f"{role}: output did not fit the schema", raw, truncated=cut
            )
            failed.usage = used
            raise failed from exc
        return LLMResult(parsed=parsed, raw_text=raw, family=self.family, **used.model_dump())

    async def close(self) -> None:
        await self._client.aclose()


class OllamaProbe:
    """Health (LLD-4 §7, BD-42): asks Ollama which models it has. Free; fails when Ollama
    is not running or a model the roles use has not been pulled."""

    def __init__(
        self,
        component: str,
        base_url: str,
        models: list[str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.component = component
        self._models = models
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport)

    async def check(self) -> None:
        response = await self._client.get("/api/tags", timeout=5.0)
        response.raise_for_status()
        pulled = {m.get("name") for m in response.json().get("models", [])}
        missing = [m for m in self._models if m not in pulled and f"{m}:latest" not in pulled]
        if missing:
            raise ProviderUnavailableError(f"ollama: not pulled: {', '.join(missing)}")

    async def close(self) -> None:
        await self._client.aclose()


def _usage(data: dict[str, Any], model: str) -> LLMUsage:
    """Ollama reports prompt tokens as `prompt_eval_count` and output as `eval_count`.
    A local model costs nothing."""
    return LLMUsage(
        model_id=str(data.get("model") or model),
        tokens_in=int(data.get("prompt_eval_count") or 0),
        tokens_out=int(data.get("eval_count") or 0),
        cost_micro_usd=0,
    )


def _base_url(settings: Settings) -> str:
    provider = settings.config.llm.providers["ollama"]
    if provider.base_url:
        return provider.base_url
    if provider.base_url_env:
        return settings.secret(provider.base_url_env)
    raise ValueError("llm.providers.ollama needs base_url or base_url_env")


def make(settings: Settings) -> OllamaLLM:
    provider = settings.config.llm.providers["ollama"]
    if provider.num_ctx is None:  # also refused when the config loads
        raise ValueError("llm.providers.ollama.num_ctx is required")
    return OllamaLLM(_base_url(settings), provider.num_ctx, keep_alive=provider.keep_alive)


def make_probe(settings: Settings) -> OllamaProbe:
    return OllamaProbe("llm_ollama", _base_url(settings), settings.models_of("ollama"))
