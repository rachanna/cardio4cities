"""One model call for question answering (LLD-3 §2.3): reserve on the question's ledger
first, time-boxed by what is left of it, usage recorded, one repair on invalid output.
(The workflow's `call_role` serves runs; `app/query` may not import the workflow.)"""

import asyncio

from pydantic import BaseModel

from app.ports.errors import LLMOutputValidationError, PortError, ProviderUnavailableError
from app.ports.llm import LLMUsage
from app.prompts.safety import escape_untrusted
from app.query.types import AskDeps

PREVIOUS_OUTPUT_CHARS = 4000


async def _record(deps: AskDeps, usage: LLMUsage) -> None:
    await deps.ledger.record_model(
        usage.model_id, usage.tokens_in, usage.tokens_out, usage.cost_micro_usd,
        usage.cached_tokens, usage.reasoning_tokens, usage.cache_write_tokens,
    )  # fmt: skip


async def _once[T: BaseModel](
    deps: AskDeps, role: str, system: str, user: str, schema: type[T]
) -> tuple[T, str]:
    binding = deps.roles[role]
    await deps.ledger.reserve("model")
    left = deps.ledger.time_left_s()
    params = binding.params.model_copy(update={"timeout_s": left})
    try:
        result = await asyncio.wait_for(
            deps.llm[binding.provider].complete(role, system, user, schema, params), left
        )
    except TimeoutError as exc:
        raise ProviderUnavailableError(f"{role}: the question's time ran out") from exc
    except PortError as exc:
        if exc.usage is not None:  # a failed call the provider billed (BD-30)
            await _record(deps, exc.usage)
        raise
    await _record(deps, result.usage())
    if not isinstance(result.parsed, schema):
        raise LLMOutputValidationError(f"{role}: unexpected output type", result.raw_text)
    return result.parsed, result.model_id


async def call[T: BaseModel](
    deps: AskDeps, role: str, system: str, user: str, schema: type[T]
) -> tuple[T, str]:
    """(parsed output, model ID); one repair when the output fails validation."""
    try:
        return await _once(deps, role, system, user, schema)
    except LLMOutputValidationError as exc:
        hint = "it was cut off: return less" if exc.truncated else str(exc)
        previous = escape_untrusted(exc.raw_text[:PREVIOUS_OUTPUT_CHARS])
        repair = (
            f"{user}\n\nYour previous output was invalid ({hint}).\n"
            f"<previous_output>\n{previous}\n</previous_output>\n"
            "Return a corrected output only."
        )
        return await _once(deps, role, system, repair, schema)
