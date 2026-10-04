"""fetch_parse (LLD-2 §3.3, §9.3-9.4): fetch through the gate, store the source and its
snapshot, chunk and embed parsed text into Qdrant.

One fetch per URL per run (BD-14): the first slot to reach a URL fetches it; another slot
that wants it waits for that fetch, or reuses the stored source, and extracts it for its
own question."""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.ids import chunk_point_id
from app.domain.models import Source
from app.domain.vocab import EventType, ParseOutcome, PublisherClass
from app.ports.vector import VectorPoint
from app.workflow.budget import BudgetExhaustedError
from app.workflow.deps import RunDeps
from app.workflow.ids import stable_id
from app.workflow.nodes._deps import deps
from app.workflow.nodes.crawl_gate import record_decision
from app.workflow.nodes.select_sources import seed_fetch_cache
from app.workflow.problems import step_failed
from app.workflow.rules.chunking import chunk_text
from app.workflow.state import Candidate, SlotState


def table_keywords(d: RunDeps, slot_id: str) -> list[str]:
    """Words that mark a PDF page worth table extraction, from the slot's indicators."""
    slot = d.slots[slot_id]
    words = {w.lower() for w in slot.short_label.split() if len(w) > 3}
    for code in slot.indicator_codes:
        if code in d.indicators:
            words |= {w.lower() for w in d.indicators[code].name.split() if len(w) > 3}
    return sorted(words)


async def _index(
    d: RunDeps,
    run_id: str,
    city_id: str,
    slot_id: str,
    source: Source,
    text: str,
    tables: list[tuple[int, int]],
) -> None:
    chunks = chunk_text(text, tables, d.chunk)
    if not chunks:
        return
    await d.ledger.reserve("model")
    vectors = await d.embeddings.embed([c.text for c in chunks])
    points = [
        VectorPoint(
            id=chunk_point_id(source.source_id, c.index),
            vector=v,
            payload={
                "city_id": city_id,
                "run_id": run_id,
                "source_id": source.source_id,
                "slot_ids": [slot_id],
                "chunk_index": c.index,
                "char_start": c.start,
                "char_end": c.end,
                "text": c.text,
                "lang": source.language or "",
                "publisher_class": source.publisher_class.value,
                "is_table": c.is_table,
                **(
                    {"published_date": source.published_date.isoformat()}
                    if source.published_date
                    else {}
                ),
            },
        )
        for c, v in zip(chunks, vectors, strict=True)
    ]
    await d.vector.upsert(d.collection, points)


async def _one(d: RunDeps, state: SlotState, candidate: Candidate) -> tuple[str | None, list[str]]:
    run_id = state["run_id"]
    collected = await d.collector.collect(candidate.url, table_keywords(d, state["slot_id"]))
    extra = list(collected.decisions[1:])  # redirect hops and post-fetch outcomes
    first = collected.decisions[0]
    decision_ids = [await record_decision(d, run_id, x) for x in extra]
    if first.outcome.value != "allowed" and not extra:
        decision_ids.append(await record_decision(d, run_id, first))
    if collected.outcome == "http_error":
        # No source row (LLD-2 §9.3), but the stream shows why the page gave nothing
        await d.events.emit(
            run_id,
            EventType.SOURCE_UNREADABLE,
            {
                "source_id": None,
                "url": candidate.url,
                "parse_outcome": None,
                "http_status": collected.http_status,
            },
        )
    if collected.outcome != "fetched" or collected.final_url is None:
        return None, decision_ids
    doc = collected.document
    source = Source(
        source_id=stable_id("src", run_id, candidate.url),
        run_id=run_id,
        url=candidate.url,
        url_canonical=collected.final_url,
        domain=collected.final_decision.domain,
        kind=collected.kind or "web_html",
        publisher_class=PublisherClass(candidate.publisher_class),
        title=doc.title if doc else None,
        language=doc.language if doc else None,
        published_date=doc.published_date if doc else None,
        published_precision=doc.published_precision if doc else None,
        retrieved_at=datetime.now(UTC),
        http_status=collected.http_status,
        content_type=collected.content_type,
        content_sha256=None,
        size_bytes=len(collected.raw) or None,
        parse_outcome=collected.parse_outcome,
        found_via=f"search:{candidate.query_id}",
    )
    parsed = collected.parse_outcome is ParseOutcome.PARSED and doc is not None
    if collected.raw:
        source = source.model_copy(update={"content_sha256": sha256(collected.raw).hexdigest()})
    await d.relational.sources.add_source(source, doc.text if parsed and doc else None, None)
    held = await d.relational.sources.source_at(run_id, collected.final_url)
    if held is not None and held[0] != source.source_id:
        # Another candidate redirected to the same page and stored it: that source is
        # this one (BD-21). Nothing is stored twice.
        held_id = held[0] if held[1] else None
        d.fetch_cache.remember(collected.final_url, held_id)
        return held_id, decision_ids
    # The snapshot row references the source row, so it is written after it.
    if collected.raw:
        await d.snapshots.put(
            source.source_id, collected.raw, collected.content_type or "application/octet-stream"
        )
    ready = source.source_id if parsed else None
    d.fetch_cache.resolve(candidate.url, ready)  # stored: a waiting slot can use it now
    d.fetch_cache.remember(collected.final_url, ready)
    if parsed and doc is not None:
        try:
            await _index(d, run_id, state["city"].city_id, state["slot_id"], source, doc.text,
                         list(doc.tables))  # fmt: skip
        except BudgetExhaustedError:
            raise
        except Exception as exc:  # the text is in Postgres: extraction still works (BD-21)
            await step_failed(d, state, "index_chunks", source.source_id, exc)
        await d.events.emit(
            run_id,
            EventType.SOURCE_FETCHED,
            {
                "source_id": source.source_id,
                "url": source.url,
                "publisher_class": source.publisher_class.value,
                "kind": source.kind.value,
            },
        )
        return source.source_id, decision_ids
    await d.events.emit(
        run_id,
        EventType.SOURCE_UNREADABLE,
        {
            "source_id": source.source_id,
            "url": source.url,
            "parse_outcome": source.parse_outcome.value if source.parse_outcome else None,
        },
    )
    return None, decision_ids


async def _owned(
    d: RunDeps, state: SlotState, candidate: Candidate
) -> tuple[str | None, list[str]]:
    """Fetch a URL this slot owns, and tell any slot waiting for it what came of it."""
    source_id: str | None = None
    try:
        source_id, ids = await _one(d, state, candidate)
    finally:  # also on failure: a waiting slot must never hang
        d.fetch_cache.resolve(candidate.url, source_id)
    return source_id, ids


async def fetch_parse(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    """The slot's pages side by side (BD-27): the collector's global and per-domain
    limits pace them, so nothing waits on one slow page."""
    d = deps(config)
    await seed_fetch_cache(d, state["run_id"])  # a slot may resume here (BD-27)
    candidates = [*state.get("reused", []), *state.get("allowed", [])]
    results = await asyncio.gather(*(_candidate(d, state, c) for c in candidates))
    source_ids: list[str] = []
    decision_ids: list[str] = []
    for source_id, ids in results:  # in candidate order
        decision_ids += ids
        if source_id and source_id not in source_ids:  # two URLs, one page (BD-21)
            source_ids.append(source_id)
    return {"source_ids": source_ids, "crawl_decision_ids": decision_ids}


async def _candidate(
    d: RunDeps, state: SlotState, candidate: Candidate
) -> tuple[str | None, list[str]]:
    pending = d.fetch_cache.claim(candidate.url)
    if pending is not None:  # fetched, or being fetched, by another slot or candidate
        return await pending, []
    try:
        return await _owned(d, state, candidate)
    except BudgetExhaustedError:
        return None, []
    except Exception as exc:  # one page never costs the slot its round (BD-21)
        await step_failed(d, state, "fetch_parse", candidate.url, exc)
        return None, []
