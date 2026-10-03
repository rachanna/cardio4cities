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
from app.prompts.loader import load_prompt
from app.workflow.budget import BudgetExhaustedError
from app.workflow.llm import call_checker
from app.workflow.nodes._deps import deps
from app.workflow.state import SlotState

LABEL_ORDER = ("period", "geography", "population")
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
        claim, statistic = await d.relational.research.claim_with_statistic(claim_id)
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
        except (PortError, BudgetExhaustedError):
            continue  # stays `extracted`: never a fact without a verdict
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
        await d.relational.research.set_claim_status(claim_id, STATUS_FOR[label].value)
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
        if label is VerdictLabel.SUPPORTED:
            supported.append(claim_id)
    return {"supported_claim_ids": supported}


def route_after_verify(state: SlotState) -> str:
    return "consistency" if state.get("supported_claim_ids") else "record_unsupported"
