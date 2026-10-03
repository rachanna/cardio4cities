"""extract (LLD-2 §3.3, LLD-3 §4): one model call per source window; repair once, escalate
once when configured, else skip the window. Drafts wait in the slot state until their
quotes are located (BD-09)."""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.ports.errors import PortError
from app.prompts.extractor import context
from app.prompts.extractor.schema import ExtractorOutput, keep_claim, repair_problems
from app.prompts.loader import load_prompt
from app.workflow.budget import BudgetExhaustedError
from app.workflow.ids import stable_id
from app.workflow.llm import call_role
from app.workflow.nodes._deps import deps
from app.workflow.problems import step_failed
from app.workflow.rules.chunking import windows
from app.workflow.rules.quotes import normalise_text
from app.workflow.state import Draft, SlotState

log = logging.getLogger(__name__)


async def extract(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    slot = d.slots[state["slot_id"]]
    indicators = [d.indicators[c] for c in slot.indicator_codes if c in d.indicators]
    prompt = load_prompt("extractor")
    roles = d.roles["extractor"]
    drafts: list[Draft] = []
    skipped: list[str] = []
    seen_quotes: set[str] = set()
    for source_id in state.get("source_ids", []):
        source = await d.relational.sources.source_for_extraction(source_id)
        text = str(source["parsed_text"] or "") if source else ""
        if not source or not text:
            continue
        spans = windows(text, d.window.window_tokens, d.window.overlap_tokens)
        for n, (start, end) in enumerate(spans, 1):
            user = context.build_user_message(
                state["city"],
                [slot],
                indicators,
                source_id,
                source.get("title"),  # type: ignore[arg-type]
                str(source["publisher_class"]),
                source.get("published_date"),  # type: ignore[arg-type]
                str(source["url"]),
                text[start:end],
                n,
                len(spans),
            )
            try:
                out = await call_role(
                    d, "extractor", prompt.system, user, ExtractorOutput, problems=repair_problems
                )
            except BudgetExhaustedError:
                return {"drafts": drafts, **_skipped(skipped)}
            except PortError as exc:
                if roles.escalate_to is None:
                    skipped.append(_skip(source_id, n, exc))
                    await step_failed(d, state, "extract", f"{source_id}#{n}", exc)
                    continue  # skip the window (LLD-2 §17)
                try:
                    out = await call_role(
                        d,
                        "extractor",
                        prompt.system,
                        user,
                        ExtractorOutput,
                        problems=repair_problems,
                        binding=roles.escalate_to,
                    )
                except BudgetExhaustedError:
                    return {"drafts": drafts, **_skipped(skipped)}
                except PortError as exc:
                    skipped.append(_skip(source_id, n, exc))
                    await step_failed(d, state, "extract", f"{source_id}#{n}", exc)
                    continue
            for claim in out.parsed.claims:
                key = normalise_text(claim.quote)
                if not keep_claim(claim, {slot.slot_id}) or key in seen_quotes:
                    continue  # invalid, or the same quote from an overlapping window
                seen_quotes.add(key)
                draft = Draft(
                    claim_id=stable_id("clm", state["run_id"], source_id, slot.slot_id, key),
                    source_id=source_id,
                    window_start=start,
                    window_end=end,
                    output=claim.model_dump(mode="json"),
                    extractor_model=out.model_id,
                    prompt_version=prompt.prompt_version,
                )
                drafts.append(draft)
                await d.events.emit(
                    state["run_id"],
                    EventType.CLAIM_EXTRACTED,
                    {
                        "claim_id": draft.claim_id,
                        "slot_id": slot.slot_id,
                        "kind": claim.kind.value,
                        "statement": claim.statement,
                    },
                )
    return {"drafts": drafts, **_skipped(skipped)}


def _skip(source_id: str, window: int, exc: Exception) -> str:
    """The error type only: messages can carry fetched text, which is never logged."""
    log.warning("extract: skipped %s window %d (%s)", source_id, window, type(exc).__name__)
    return type(exc).__name__


def _skipped(skipped: list[str]) -> dict[str, Any]:
    return (
        {"error": f"extract: {len(skipped)} window(s) skipped ({', '.join(sorted(set(skipped)))})"}
        if skipped
        else {}
    )
