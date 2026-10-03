"""match_quotes (LLD-2 §4.1, AT-09): locate each quote exactly in the window the model
read (uniqueness scoped to that window, BD-08), map it to document offsets, then apply
the label rules. Label quotes are located the same way; an unlocated period or
population label is cleared (BD-10). A claim about an area that is neither the city, an
area containing it, nor a place near it is dropped (BD-10). Every drop is recorded with
its reason; no fuzzy matching."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.models import CityIdentity, Claim, GeographyFit, LabelKind, Labels, Statistic
from app.domain.ranking import Candidate, ranked
from app.domain.vocab import (
    USABLE_RELATIONS,
    ClaimFlag,
    ClaimKind,
    ClaimStatus,
    DatePrecision,
    EventType,
    PublisherClass,
)
from app.prompts.extractor.schema import ClaimOut, to_labels
from app.workflow.deps import RunDeps
from app.workflow.nodes._deps import deps
from app.workflow.rules.geography_fit import PlaceCandidate, geography_fit, lookup_names
from app.workflow.rules.label_evidence import clear_labels, locate_label_quotes
from app.workflow.rules.labels import apply_reference_period_rule, derive_flags
from app.workflow.rules.numbers import parse_value
from app.workflow.rules.quotes import QuoteDrop, match_quote
from app.workflow.rules.thresholds import threshold_code
from app.workflow.state import SlotState


async def fit_for(d: RunDeps, city: CityIdentity, labels: Labels) -> GeographyFit:
    rows = await d.relational.reference.places_named(
        lookup_names(labels.geography_name), city.country_iso2
    )
    candidates = [
        PlaceCandidate(str(r["gazetteer_id"]), str(r["name"]), float(r["lat"]), float(r["lon"]))
        for r in rows
    ]
    return geography_fit(
        labels.geography_level, labels.geography_name, city, candidates,
        d.geography.nearby_km,
    )  # fmt: skip


async def match_quotes(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    slot = d.slots[state["slot_id"]]
    texts: dict[str, dict[str, Any]] = {}
    matched: list[Candidate] = []
    for draft in state.get("drafts", []):
        if draft.source_id not in texts:
            texts[draft.source_id] = (
                await d.relational.sources.source_for_extraction(draft.source_id) or {}
            )
        source = texts[draft.source_id]
        text = str(source.get("parsed_text") or "")
        out = ClaimOut.model_validate(draft.output)
        value = out.statistic.value_as_written if out.statistic else None
        window = text[draft.window_start : draft.window_end]
        found = match_quote(out.quote, window, d.quote, value)
        if isinstance(found, QuoteDrop):
            await d.events.emit(
                state["run_id"],
                EventType.CLAIM_DROPPED,
                {
                    "claim_id": draft.claim_id,
                    "reason": found.reason,
                    "statement": out.statement,
                    "quote": out.quote,
                },
            )
            continue
        start, end = draft.window_start + found.span_start, draft.window_start + found.span_end
        labels, period_unparsed = to_labels(
            out.labels, threshold_code(out.labels.case_definition, d.thresholds)
        )
        label_quotes: dict[LabelKind, str | None] = (
            out.label_quotes.model_dump() if out.label_quotes else {}  # type: ignore[assignment]
        )
        evidence = locate_label_quotes(label_quotes, window, draft.window_start, labels, d.quote)
        labels = clear_labels(labels, evidence.cleared)
        fit = await fit_for(d, state["city"], labels)
        if fit.relation not in USABLE_RELATIONS:
            await d.events.emit(
                state["run_id"],
                EventType.CLAIM_DROPPED,
                {
                    "claim_id": draft.claim_id,
                    "reason": f"geography_{fit.relation.value}",
                    "statement": out.statement,
                    "geography_name": labels.geography_name,
                    "place": fit.place_name,
                    "distance_km": fit.distance_km,
                },
            )
            continue
        precision = source.get("published_precision")
        labels = apply_reference_period_rule(
            labels,
            source.get("published_date"),
            DatePrecision(str(precision)) if precision else None,
        )
        parsed = parse_value(value) if value is not None else None
        flags = set(derive_flags(out.kind, labels, out.quote_lang, parsed, d.badge))
        if period_unparsed:
            flags.add(ClaimFlag.PERIOD_NOT_STATED)
        claim = Claim(
            claim_id=draft.claim_id,
            run_id=state["run_id"],
            city_id=state["city"].city_id,
            slot_id=slot.slot_id,
            source_id=draft.source_id,
            kind=out.kind,
            statement=out.statement,
            quote=text[start:end],
            quote_lang=out.quote_lang,
            quote_translation=out.quote_translation,
            span_start=start,
            span_end=end,
            labels=labels,
            flags=frozenset(flags),
            status=ClaimStatus.EXTRACTED,
            extractor_model=draft.extractor_model,
            prompt_version=draft.prompt_version,
            label_spans=evidence.spans,
            geography_fit=fit,
        )
        statistic = None
        if out.kind is ClaimKind.STATISTIC and out.statistic is not None and parsed is not None:
            code = out.statistic.indicator_code
            statistic = Statistic(
                claim_id=claim.claim_id,
                indicator_code=code if code in d.indicators else "OTHER",
                value_as_written=out.statistic.value_as_written,
                value_num=parsed.value_num,
                unit=parsed.unit,
                lower=parsed.lower,
                upper=parsed.upper,
            )
        await d.relational.research.add_claim(claim, statistic)
        matched.append(Candidate(claim, PublisherClass(str(source["publisher_class"]))))
    order = [c.claim.claim_id for c in ranked(matched, slot.accepted_levels)]
    return {"claim_ids": order, "matched_claim_ids": order}


def route_after_match(state: SlotState) -> str:
    return "verify" if state.get("matched_claim_ids") else "slot_done"
