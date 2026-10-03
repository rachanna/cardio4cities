"""wave0 (LLD-2 §13, R-85, BD-13): national figures from official APIs before any search.

For each registry provider and indicator: one API call through the collector's API path
(address checks, pinning, an `api_terms:<provider>` decision); the raw response stored as
a `structured_api` source and snapshot; the latest record for both sexes and the
registry's age group rendered as one canonical line; a statistic claim quoting that line;
and code verification against the re-read snapshot (`code:record_match`, family `code`).
Wave 0 claims never reach the model checker. A Wave 0 failure never stops the run.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.models import (
    CityIdentity,
    Claim,
    GeographyFit,
    Labels,
    Source,
    SourceIndicator,
    SourceProvider,
    Statistic,
    Verdict,
)
from app.domain.vocab import (
    ClaimKind,
    ClaimStatus,
    DatePrecision,
    EventType,
    GeographyRelation,
    ParseOutcome,
    PeriodType,
    Representativeness,
    Sex,
    SourceKind,
    VerdictLabel,
)
from app.ports.structured import StructuredDataPort, StructuredRecord
from app.workflow.budget import BudgetExhaustedError
from app.workflow.claim_index import set_status
from app.workflow.deps import RunDeps
from app.workflow.graph_writes import write_graph
from app.workflow.ids import stable_id
from app.workflow.nodes._deps import deps
from app.workflow.nodes.crawl_gate import record_decision
from app.workflow.rules.labels import derive_flags
from app.workflow.rules.thresholds import threshold_code
from app.workflow.rules.wave0 import (
    CODE_FAMILY,
    CODE_VERIFIER,
    canonical_line,
    code_check,
    record_value,
    select_record,
)
from app.workflow.state import RunState

log = logging.getLogger(__name__)
PROMPT_VERSION = "code:wave0@v1"  # no model is involved; recorded where a prompt would be


@dataclass(frozen=True)
class Fetched:
    source_id: str
    raw: bytes
    records: list[StructuredRecord]


async def wave0(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    claim_ids: list[str] = []
    try:
        for provider in await d.relational.reference.sources():
            adapter = d.structured.get(provider.provider)
            if adapter is None:
                continue
            for key, indicator in provider.indicators.items():
                try:
                    claim_id = await _indicator(d, state, provider, adapter, key, indicator)
                except BudgetExhaustedError:
                    return {"wave0_claim_ids": claim_ids}
                except Exception as exc:  # one indicator's failure never stops the others
                    log.warning(
                        "wave0 %s.%s skipped (%s)", provider.provider, key, type(exc).__name__
                    )
                    continue
                if claim_id:
                    claim_ids.append(claim_id)
    except Exception as exc:  # Wave 0 never stops the run (LLD-2 §3.3)
        log.warning("wave0 stopped early (%s)", type(exc).__name__)
    return {"wave0_claim_ids": claim_ids}


async def _fetch(
    d: RunDeps,
    run_id: str,
    provider: SourceProvider,
    adapter: StructuredDataPort,
    indicator: SourceIndicator,
    url: str,
) -> Fetched | None:
    fetched = await d.collector.fetch_api(url, provider.provider)
    decision_ids = [await record_decision(d, run_id, x) for x in fetched.decisions]
    if fetched.result is None:
        return None
    raw = fetched.result.content
    records = adapter.parse(indicator.code, raw)
    final = fetched.decisions[-1]
    source = Source(
        source_id=stable_id("src", run_id, url),
        run_id=run_id,
        url=url,
        url_canonical=final.url,
        domain=final.domain,
        kind=SourceKind.STRUCTURED_API,
        publisher_class=provider.publisher_class,
        title=f"{provider.publisher_name}: {indicator.label or indicator.code}",
        language="en",
        published_date=None,
        published_precision=None,
        retrieved_at=datetime.now(UTC),
        http_status=fetched.result.status,
        content_type=fetched.result.content_type,
        content_sha256=sha256(raw).hexdigest(),
        size_bytes=len(raw),
        parse_outcome=ParseOutcome.PARSED,
        found_via=f"wave0:{provider.provider}",
    )
    # parsed_text is set once the record is chosen (its canonical line); stored below
    await d.relational.sources.add_source(source, None, decision_ids[-1] if decision_ids else None)
    await d.snapshots.put(source.source_id, raw, fetched.result.content_type or "application/json")
    return Fetched(source.source_id, raw, records)


async def _indicator(
    d: RunDeps,
    state: RunState,
    provider: SourceProvider,
    adapter: StructuredDataPort,
    key: str,
    indicator: SourceIndicator,
) -> str | None:
    city: CityIdentity = state["city"]
    run_id = state["run_id"]
    for url in adapter.request_urls(indicator.code, city.country_iso3, {}):
        fetched = await _fetch(d, run_id, provider, adapter, indicator, url)
        if fetched is None:
            continue
        record = select_record(fetched.records, indicator, city.country_iso3)
        if record is None:
            continue
        line = canonical_line(record, indicator)
        await d.relational.sources.set_parsed_text(fetched.source_id, line)
        if indicator.slot is None:  # stored for sanity checks only (e.g. population)
            return None
        return await _claim(d, state, provider, adapter, key, indicator, fetched, record, line)
    return None


async def _claim(
    d: RunDeps,
    state: RunState,
    provider: SourceProvider,
    adapter: StructuredDataPort,
    key: str,
    indicator: SourceIndicator,
    fetched: Fetched,
    record: StructuredRecord,
    line: str,
) -> str:
    city: CityIdentity = state["city"]
    labels = _labels(d, provider, indicator, city, record.year)
    parsed = record_value(record.value_as_written, indicator.unit)
    unit = indicator.unit or ""
    note = f" ({provider.note})" if provider.note else ""
    claim = Claim(
        claim_id=stable_id("clm", state["run_id"], fetched.source_id, key),
        run_id=state["run_id"],
        city_id=city.city_id,
        slot_id=str(indicator.slot),
        source_id=fetched.source_id,
        kind=ClaimKind.STATISTIC,
        statement=f"{indicator.label} in {city.country_name}: {record.value_as_written}{unit} "
        f"in {record.year}{note}.",
        quote=line,
        quote_lang="en",
        quote_translation=None,
        span_start=0,
        span_end=len(line),
        labels=labels,
        flags=derive_flags(ClaimKind.STATISTIC, labels, "en", parsed, d.badge),
        status=ClaimStatus.EXTRACTED,
        extractor_model="code:wave0",
        prompt_version=PROMPT_VERSION,
        geography_fit=GeographyFit(
            relation=GeographyRelation.CONTAINS_CITY, place_name=city.country_name
        ),
    )
    statistic = Statistic(
        claim_id=claim.claim_id,
        indicator_code=key if key in d.indicators else "OTHER",
        value_as_written=record.value_as_written,
        value_num=parsed.value_num,
        unit=parsed.unit,  # in the parser's words, so figures compare (BD-19)
        lower=parsed.lower,
        upper=parsed.upper,
    )
    await d.relational.research.add_claim(claim, statistic)
    # Code verification: re-read the snapshot, re-parse it, require the same record
    stored, _ = await d.snapshots.get(fetched.source_id)
    check = code_check(
        line,
        record.value_as_written,
        adapter.parse(indicator.code, stored),
        indicator,
        city.country_iso3,
    )
    label = VerdictLabel.SUPPORTED if check.matched else VerdictLabel.INSUFFICIENT
    await d.relational.research.add_verdict(
        Verdict(
            claim_id=claim.claim_id,
            label=label,
            rationale=check.reason[:400],
            scope_verified=check.matched,
            period_verified=check.matched,
            verifier_model=CODE_VERIFIER,
            verifier_family=CODE_FAMILY,
            prompt_version=PROMPT_VERSION,
        )
    )
    status = ClaimStatus.SUPPORTED if check.matched else ClaimStatus.INSUFFICIENT
    await set_status(d, claim.claim_id, status)
    graph_edge = await write_graph(d, claim.claim_id) if check.matched else False
    await d.events.emit(
        state["run_id"],
        EventType.WAVE0_FINDING,
        {
            "claim_id": claim.claim_id,
            "provider": provider.provider,
            "indicator": key,
            "slot_id": indicator.slot,
            "value": record.value_as_written,
            "year": record.year,
            "status": status.value,
            "graph_edge": graph_edge,
        },
    )
    return claim.claim_id


def _labels(
    d: RunDeps, provider: SourceProvider, indicator: SourceIndicator, city: CityIdentity, year: int
) -> Labels:
    low, high = indicator.age if indicator.age else (None, None)
    return Labels(
        geography_level=provider.geography,
        geography_name=city.country_name,
        measure_type=indicator.measure,
        reference_start=date(year, 1, 1),
        reference_end=date(year, 12, 31),
        reference_precision=DatePrecision.YEAR,
        period_type=PeriodType.PERIOD,
        population_age_min=low,
        population_age_max=high,
        population_sex=Sex.ALL,
        case_definition=indicator.case_definition,
        threshold_code=threshold_code(indicator.case_definition, d.thresholds),
        method=provider.method,
        representativeness=provider.representativeness or Representativeness.NOT_APPLICABLE,
        denominator_text=indicator.denominator,
        denominator_stated=bool(indicator.denominator),
    )
