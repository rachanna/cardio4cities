"""One way to call a model role (LLD-2 §17, LLD-3 §2.3): reserve budget first, record
tokens and cost after, repair once on invalid output, and for the checker fall back to
the labelled same-family model when the primary fails twice. Each call's timeout is the
time left on the run (BD-15)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.ports.errors import LLMOutputValidationError, PortError, ProviderUnavailableError
from app.ports.llm import LLMParams
from app.workflow.deps import Binding, RunDeps

# API output ceilings (LLD-3 §2.3, BD-04): they also cover thinking or reasoning tokens;
# the visible output is limited by each role's schema validation.
OUTPUT_CEILING = {
    "planner": 16000,
    "extractor": 16000,
    "checker": 8000,
    "classifier": 400,
    "answerer": 16000,
    "reporter": 16000,
}
HAIKU_EXTRACTOR_CEILING = 4000


@dataclass(frozen=True)
class RoleOutput[T]:
    parsed: T
    model_id: str
    family: str
    fallback_used: bool


def _params(role: str, binding: Binding) -> LLMParams:
    ceiling = OUTPUT_CEILING[role]
    if role == "extractor" and binding.model.startswith("claude-haiku"):
        ceiling = HAIKU_EXTRACTOR_CEILING
    return LLMParams(
        model=binding.model,
        max_output_tokens=ceiling,
        effort=binding.effort,
        temperature=binding.temperature,
    )


async def _call_once[T: BaseModel](
    deps: RunDeps, role: str, binding: Binding, system: str, user: str, schema: type[T]
) -> tuple[T, str]:
    await deps.ledger.reserve("model")
    # A call never outlives the run's wall clock (BD-15): its timeout is the time left
    left = deps.ledger.time_left_s()
    params = _params(role, binding).model_copy(update={"timeout_s": left})
    try:
        result = await asyncio.wait_for(
            deps.llm[binding.provider].complete(role, system, user, schema, params), left
        )
    except TimeoutError as exc:
        raise ProviderUnavailableError(f"{role}: the run's time ran out") from exc
    await deps.ledger.record_model(
        result.model_id, result.tokens_in, result.tokens_out, result.cost_micro_usd
    )
    if not isinstance(result.parsed, schema):
        raise LLMOutputValidationError(f"{role}: unexpected output type", result.raw_text)
    return result.parsed, result.model_id


async def call_role[T: BaseModel](
    deps: RunDeps,
    role: str,
    system: str,
    user: str,
    schema: type[T],
    problems: Callable[[T], list[str]] = lambda _: [],
    binding: Binding | None = None,
) -> RoleOutput[T]:
    """Primary call plus one repair attempt when the output fails validation."""
    chosen = binding or deps.roles[role].primary
    message = user
    for attempt in range(2):
        try:
            parsed, model_id = await _call_once(deps, role, chosen, system, message, schema)
        except LLMOutputValidationError as exc:
            if attempt == 1:
                raise
            message = (
                f"{user}\n\nYour previous output was invalid: {exc}. "
                "Return a corrected output only."
            )
            continue
        issues = problems(parsed)
        if not issues:
            return RoleOutput(parsed, model_id, chosen.family, False)
        if attempt == 1:
            raise LLMOutputValidationError(f"{role}: {'; '.join(issues)}", parsed.model_dump_json())
        message = (
            f"{user}\n\nYour previous output had these problems: {'; '.join(issues)}. "
            f"Previous output: {parsed.model_dump_json()}\nReturn a corrected output only."
        )
    raise AssertionError("unreachable")  # pragma: no cover


async def call_checker[T: BaseModel](
    deps: RunDeps, system: str, user: str, schema: type[T]
) -> RoleOutput[T]:
    """Retry the primary checker twice, then the labelled fallback (LLD-2 §17, R-82)."""
    roles = deps.roles["checker"]
    failure: Exception | None = None
    for _ in range(2):
        try:
            return await call_role(deps, "checker", system, user, schema, binding=roles.primary)
        except (ProviderUnavailableError, LLMOutputValidationError) as exc:
            failure = exc
    if roles.fallback is None:
        raise PortError(f"checker failed and no fallback is configured: {failure}")
    out = await call_role(deps, "checker", system, user, schema, binding=roles.fallback)
    return RoleOutput(out.parsed, out.model_id, out.family, True)
