"""One way to call a model role (LLD-2 §17, LLD-3 §2.3): reserve budget first, record
tokens and cost after, repair once on invalid output, and for the checker fall back to
the labelled same-family model when the primary fails twice. Each call's timeout is the
time left on the run (BD-15)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.ports.errors import LLMOutputValidationError, PortError, ProviderUnavailableError
from app.ports.llm import LLMParams, LLMUsage
from app.prompts.safety import escape_untrusted
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
HAIKU_EXTRACTOR_CEILING = 8000  # 12 claims need about 3.8k to 5.5k tokens (BD-26, RV-053)
PREVIOUS_OUTPUT_CHARS = 4000  # how much of a failed output a repair shows back


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
    except PortError as exc:
        if exc.usage is not None:  # a failed call the provider billed (BD-30)
            await _record(deps, exc.usage)
        raise
    await _record(deps, result.usage())
    if not isinstance(result.parsed, schema):
        raise LLMOutputValidationError(f"{role}: unexpected output type", result.raw_text)
    return result.parsed, result.model_id


async def _record(deps: RunDeps, usage: LLMUsage) -> None:
    await deps.ledger.record_model(
        usage.model_id, usage.tokens_in, usage.tokens_out, usage.cost_micro_usd,
        usage.cached_tokens, usage.reasoning_tokens, usage.cache_write_tokens,
    )  # fmt: skip


def _repair(user: str, problem: str, previous: str) -> str:
    """The repair request (LLD-3 §2.3): the problem, and the previous output inside an
    escaped tag, since it quotes the page (BD-26; code review RV-059)."""
    return (
        f"{user}\n\n{problem}\n<previous_output>\n"
        f"{escape_untrusted(previous[:PREVIOUS_OUTPUT_CHARS])}\n</previous_output>\n"
        "Return a corrected output only."
    )


async def call_role[T: BaseModel](
    deps: RunDeps,
    role: str,
    system: str,
    user: str,
    schema: type[T],
    problems: Callable[[T], list[str]] = lambda _: [],
    binding: Binding | None = None,
    repair: bool = True,
) -> RoleOutput[T]:
    """Primary call plus one repair attempt when the output fails validation (none when
    `repair` is false: the caller counts attempts itself)."""
    chosen = binding or deps.roles[role].primary
    message = user
    attempts = 2 if repair else 1
    for attempt in range(attempts):
        try:
            parsed, model_id = await _call_once(deps, role, chosen, system, message, schema)
        except LLMOutputValidationError as exc:
            if attempt == attempts - 1:
                raise
            hint = "it was cut off: return fewer, shorter items" if exc.truncated else str(exc)
            message = _repair(user, f"Your previous output was invalid ({hint}).", exc.raw_text)
            continue
        issues = problems(parsed)
        if not issues:
            return RoleOutput(parsed, model_id, chosen.family, False)
        if attempt == attempts - 1:
            raise LLMOutputValidationError(f"{role}: {'; '.join(issues)}", parsed.model_dump_json())
        message = _repair(
            user,
            f"Your previous output had these problems: {'; '.join(issues)}.",
            parsed.model_dump_json(),
        )
    raise AssertionError("unreachable")  # pragma: no cover


async def call_checker[T: BaseModel](
    deps: RunDeps, system: str, user: str, schema: type[T]
) -> RoleOutput[T]:
    """Two calls on the primary checker, then the labelled fallback (LLD-2 §17, R-82).
    Each primary attempt is a single call: a failed attempt is not repaired, it counts."""
    roles = deps.roles["checker"]
    failure: Exception | None = None
    for _ in range(2):
        try:
            return await call_role(
                deps, "checker", system, user, schema, binding=roles.primary, repair=False
            )
        except (ProviderUnavailableError, LLMOutputValidationError) as exc:
            failure = exc
    if roles.fallback is None:
        raise PortError(f"checker failed and no fallback is configured: {failure}")
    out = await call_role(deps, "checker", system, user, schema, binding=roles.fallback)
    return RoleOutput(out.parsed, out.model_id, out.family, True)
