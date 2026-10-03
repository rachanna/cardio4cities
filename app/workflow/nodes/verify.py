"""verify (LLD-2 §5.3, LLD-3 §5, AT-07, AT-08): the top matched claims go to the
independent checker with the restricted slice only. Refuted or insufficient claims never
become facts; `supported` with any issue counts as insufficient (PD-03)."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.models import Verdict
from app.domain.vocab import ClaimStatus, EventType, VerdictLabel
from app.ports.errors import PortError
from app.prompts.checker import context
from app.prompts.checker.schema import CheckerOutput, final_label, rationale
from app.prompts.loader import Prompt, load_prompt
from app.workflow.budget import BudgetExhaustedError
from app.workflow.claim_index import set_status
from app.workflow.deps import RunDeps
from app.workflow.llm import call_checker
from app.workflow.nodes._deps import deps
from app.workflow.problems import step_failed
from app.workflow.state import SlotState

LABEL_ORDER = ("period", "geography", "population")
# A resumed run meets claims the checker already judged (BD-14): their verdict stands.
PASSED_CHECKER = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED, ClaimStatus.SUPERSEDED})
STATUS_FOR = {
    VerdictLabel.SUPPORTED: ClaimStatus.SUPPORTED,
    VerdictLabel.REFUTED: ClaimStatus.REFUTED,
    VerdictLabel.INSUFFICIENT: ClaimStatus.INSUFFICIENT,
}


async def verify(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    prompt = load_prompt("checker")
    supported: list[str] = []
    for claim_id in state.get("matched_claim_ids", [])[: d.verify.max_claims_per_slot]:
        try:
            passed = await _check(d, state, prompt, claim_id)
        except BudgetExhaustedError:
            continue  # stays `extracted`; a stored verdict later in the list still applies
        except Exception as exc:  # one claim's failure never costs the others (BD-21)
            await step_failed(d, state, "verify", claim_id, exc)
            claim, _ = await d.relational.research.claim_with_statistic(claim_id)
            passed = claim.status in PASSED_CHECKER  # supported before it failed: kept
        if passed:
            supported.append(claim_id)
    return {"supported_claim_ids": supported}


async def _check(d: RunDeps, state: SlotState, prompt: Prompt, claim_id: str) -> bool:
    """Judge one claim; True when it passed the checker, now or before a resume."""
    claim, statistic = await d.relational.research.claim_with_statistic(claim_id)
    if claim.status is not ClaimStatus.EXTRACTED:
        return claim.status in PASSED_CHECKER
    stored = await d.relational.research.stored_verdict(claim_id)
    if stored is not None:
        # A resumed run: the verdict was stored before the stop, the status was not.
        # The stored verdict stands; the checker is never asked twice (BD-18).
        label = VerdictLabel(stored["label"])
        await set_status(d, claim_id, STATUS_FOR[label])
        await d.events.emit(
            state["run_id"],
            EventType.CLAIM_VERDICT,
            {
                "claim_id": claim_id,
                "label": label.value,
                "verifier_model": stored["verifier_model"],
                "fallback_used": stored["fallback_used"],
                "from_stored_verdict": True,
            },
        )
        return label is VerdictLabel.SUPPORTED
    source = await d.relational.sources.source_for_extraction(claim.source_id) or {}
    text = str(source.get("parsed_text") or "")
    user = context.build_user_message(
        claim.statement,
        statistic.value_as_written if statistic else None,
        claim.labels,
        claim.source_id,
        str(source.get("publisher_class")),
        source.get("published_date"),  # type: ignore[arg-type]
        context.passage(text, claim.span_start, claim.span_end),
        [
            (kind, context.passage(text, *claim.label_spans[kind], d.verify.label_margin_chars))
            for kind in LABEL_ORDER
            if kind in claim.label_spans
        ],
    )
    try:
        out = await call_checker(d, prompt.system, user, CheckerOutput)
    except PortError as exc:  # stays `extracted`: never a fact without a verdict
        await step_failed(d, state, "check", claim_id, exc)
        return False
    label = final_label(out.parsed)
    await d.relational.research.add_verdict(
        Verdict(
            claim_id=claim_id,
            label=label,
            rationale=rationale(out.parsed),
            scope_verified=out.parsed.scope_verified,
            period_verified=out.parsed.period_verified,
            verifier_model=out.model_id,
            verifier_family=out.family,
            fallback_used=out.fallback_used,
            prompt_version=prompt.prompt_version,
        )
    )
    await set_status(d, claim_id, STATUS_FOR[label])  # Postgres, then both indexes
    await d.events.emit(
        state["run_id"],
        EventType.CLAIM_VERDICT,
        {
            "claim_id": claim_id,
            "label": label.value,
            "model_label": out.parsed.label.value,  # before the PD-03 issue rule
            "issues": [i.value for i in out.parsed.issues],
            "verifier_model": out.model_id,
            "fallback_used": out.fallback_used,
        },
    )
    return label is VerdictLabel.SUPPORTED


def route_after_verify(state: SlotState) -> str:
    return "consistency" if state.get("supported_claim_ids") else "record_unsupported"
