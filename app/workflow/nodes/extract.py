"""extract (LLD-2 §3.3, LLD-3 §4): one model call per source window; repair once, escalate
once when configured, else skip the window. Drafts wait in the slot state until their
quotes are located (BD-09)."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.ports.errors import PortError
from app.prompts.extractor import context
from app.prompts.extractor.schema import (
    MAX_CLAIMS,
    ClaimOut,
    ExtractorOutput,
    keep_claim,
    repair_problems,
)
from app.prompts.loader import load_prompt
from app.workflow.budget import BudgetExhaustedError
from app.workflow.deps import RunDeps
from app.workflow.ids import stable_id
from app.workflow.llm import call_role
from app.workflow.nodes._deps import deps
from app.workflow.nodes.fetch_parse import table_keywords
from app.workflow.problems import step_failed
from app.workflow.rules.chunking import pick_windows, windows
from app.workflow.rules.quotes import normalise_text
from app.workflow.state import Draft, SlotState

log = logging.getLogger(__name__)


async def extract(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    """Every chosen window of every source side by side, under the model gate (BD-29).
    Drafts are kept in source and window order, whatever order the calls finish in."""
    d = deps(config)
    slot = d.slots[state["slot_id"]]
    jobs: list[Window] = []
    for source_id in state.get("source_ids", []):
        if (slot.slot_id, source_id) in d.extracted:
            continue  # this slot read it in an earlier round: same claims, pure cost
        source = await d.relational.sources.source_for_extraction(source_id)
        text = str(source["parsed_text"] or "") if source else ""
        if not source or not text:
            continue
        d.extracted.add((slot.slot_id, source_id))
        spans = windows(text, d.window.window_tokens, d.window.overlap_tokens)
        terms = [state["city"].name, state["city"].ascii_name, *table_keywords(d, slot.slot_id)]
        chosen = pick_windows(text, spans, terms, d.window.max_windows_per_source)
        jobs += [Window(source_id, source, text, n, len(spans), a, b) for n, a, b in chosen]
    results = await asyncio.gather(*(_extract_window(d, state, job) for job in jobs))
    drafts: list[Draft] = []
    skipped = [r for r in results if isinstance(r, str)]
    seen_quotes: set[str] = set()
    prompt = load_prompt("extractor")
    for job, result in zip(jobs, results, strict=True):
        if result is None or isinstance(result, str):
            continue
        model_id, claims = result
        for claim in claims[:MAX_CLAIMS]:  # the most relevant first (BD-26)
            key = normalise_text(claim.quote)
            if not keep_claim(claim, {slot.slot_id}) or key in seen_quotes:
                continue  # invalid, or the same quote from an overlapping window
            seen_quotes.add(key)
            draft = Draft(
                claim_id=stable_id("clm", state["run_id"], job.source_id, slot.slot_id, key),
                source_id=job.source_id,
                window_start=job.start,
                window_end=job.end,
                output=claim.model_dump(mode="json"),
                extractor_model=model_id,
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


@dataclass(frozen=True)
class Window:
    source_id: str
    source: dict[str, Any]
    text: str
    number: int
    count: int
    start: int
    end: int


async def _extract_window(
    d: RunDeps, state: SlotState, job: Window
) -> tuple[str, list[ClaimOut]] | str | None:
    """(model, claims), an error type when the window was skipped, or None when the run
    is out of budget or too close to its end for a new window (owner, BD-29)."""
    if d.ledger.time_left_s() < d.window.stop_windows_below_s:
        return None  # its drafts could not be located and checked in time
    slot = d.slots[state["slot_id"]]
    indicators = [d.indicators[c] for c in slot.indicator_codes if c in d.indicators]
    prompt = load_prompt("extractor")
    roles = d.roles["extractor"]
    user = context.build_user_message(
        state["city"],
        [slot],
        indicators,
        job.source_id,
        job.source.get("title"),
        str(job.source["publisher_class"]),
        job.source.get("published_date"),
        str(job.source["url"]),
        job.text[job.start : job.end],
        job.number,
        job.count,
    )
    where = f"{job.source_id}#{job.number}"
    try:
        out = await call_role(
            d, "extractor", prompt.system, user, ExtractorOutput, problems=repair_problems
        )
    except BudgetExhaustedError:
        return None
    except PortError as exc:
        if roles.escalate_to is None:
            await step_failed(d, state, "extract", where, exc)
            return _skip(job.source_id, job.number, exc)  # skip the window (LLD-2 §17)
        try:
            out = await call_role(
                d, "extractor", prompt.system, user, ExtractorOutput,
                problems=repair_problems, binding=roles.escalate_to,
            )  # fmt: skip
        except BudgetExhaustedError:
            return None
        except PortError as exc:
            await step_failed(d, state, "extract", where, exc)
            return _skip(job.source_id, job.number, exc)
    return out.model_id, list(out.parsed.claims)


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
