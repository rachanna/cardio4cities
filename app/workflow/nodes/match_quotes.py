"""match_quotes (LLD-2 §4.1, AT-09): locate each quote exactly in the window the model
read (uniqueness scoped to that window, BD-08), map it to document offsets, then apply
the label rules. Label quotes are located the same way; an unlocated period or
population label is cleared (BD-10). A claim about an area that is neither the city, an
area containing it, nor a place near it is dropped (BD-10). Every drop is recorded with
its reason; no fuzzy matching.

A sub-city claim counts as the city only when the city's own name is in its located
quote or label passage (D2-4). For a relation claim, subject and object are resolved to
entities here (LLD-2 §6), so its relation row is stored with the claim."""

from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.models import (
    CityIdentity,
    Claim,
    GeographyFit,
    LabelKind,
    Labels,
    Relation,
    Statistic,
)
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
from app.prompts.extractor.schema import ClaimOut, RelationOut, parse_partial_date, to_labels
from app.workflow.deps import RunDeps
from app.workflow.nodes._deps import deps
from app.workflow.rules.entity_resolution import acronym_pairs
from app.workflow.rules.geography_fit import (
    PlaceCandidate,
    city_named,
    geography_fit,
    lookup_names,
    region_named,
)
from app.workflow.rules.label_evidence import clear_labels, locate_label_quotes
from app.workflow.rules.labels import apply_reference_period_rule, derive_flags
from app.workflow.rules.numbers import parse_value
from app.workflow.rules.quotes import QuoteDrop, match_quote
from app.workflow.rules.thresholds import threshold_code
from app.workflow.state import SlotState


async def fit_for(
    d: RunDeps, city: CityIdentity, labels: Labels, evidence: list[str], region_in_source: bool
) -> GeographyFit:
    """`evidence`: the located quote and label passages; `region_in_source`: the source
    names the city's own region (`region_named`, BD-17)."""
    rows = await d.relational.reference.places_named(
        lookup_names(labels.geography_name), city.country_iso2
    )
    candidates = [
        PlaceCandidate(
            str(r["gazetteer_id"]),
            str(r["name"]),
            float(r["lat"]),
            float(r["lon"]),
            r["admin1_code"],
            frozenset(r["name_keys"] or ()),
        )
        for r in rows
    ]
    return geography_fit(
        labels.geography_level,
        labels.geography_name,
        city,
        candidates,
        d.geography.nearby_km,
        city_named(city, evidence),
        region_in_source,
    )


async def relation_for(
    d: RunDeps,
    city_id: str,
    claim_id: str,
    rel: RelationOut,
    acronyms: dict[str, str],
    published: date | None,
) -> Relation:
    """Resolve subject and object (LLD-2 §6); a missing start date takes the publication
    date as a flagged proxy (LLD-1 §2.5)."""
    subject = await d.entities.resolve(city_id, rel.subject_name, rel.subject_type, acronyms)
    obj = await d.entities.resolve(city_id, rel.object_name, rel.object_type, acronyms)
    valid_from, _ = parse_partial_date(rel.valid_from, end=False)
    valid_to, _ = parse_partial_date(rel.valid_to, end=True)
    # The publication date stands in for a missing start, unless it falls after the stated
    # end: "until March 2024" in a later report says nothing about when it began.
    proxy = (
        valid_from is None and published is not None and (valid_to is None or published <= valid_to)
    )
    return Relation(
        claim_id=claim_id,
        subject_entity_id=subject,
        relation_type=rel.relation_type,
        object_entity_id=obj,
        valid_from=published if proxy else valid_from,
        valid_to=valid_to,
        valid_from_is_proxy=proxy,
        programme_status=rel.programme_status,
    )


async def match_quotes(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    slot = d.slots[state["slot_id"]]
    texts: dict[str, dict[str, Any]] = {}
    regions: dict[str, bool] = {}  # source -> it names the city's own region (BD-17)
    acronyms: dict[str, dict[str, str]] = {}  # per source (LLD-2 §6 step 3)
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
        located = [text[start:end], *(text[a:b] for a, b in evidence.spans.values())]
        if draft.source_id not in regions:
            regions[draft.source_id] = region_named(state["city"], text)
        fit = await fit_for(d, state["city"], labels, located, regions[draft.source_id])
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
        relation = None
        if out.kind is ClaimKind.RELATION and out.relation is not None:
            if draft.source_id not in acronyms:
                acronyms[draft.source_id] = acronym_pairs(text)
            published = source.get("published_date")
            relation = await relation_for(
                d,
                claim.city_id,
                claim.claim_id,
                out.relation,
                acronyms[draft.source_id],
                published if isinstance(published, date) else None,
            )
        await d.relational.research.add_claim(claim, statistic, relation)
        matched.append(Candidate(claim, PublisherClass(str(source["publisher_class"]))))
    order = [c.claim.claim_id for c in ranked(matched, slot.accepted_levels)]
    return {"claim_ids": order, "matched_claim_ids": order}


def route_after_match(state: SlotState) -> str:
    return "verify" if state.get("matched_claim_ids") else "slot_done"
