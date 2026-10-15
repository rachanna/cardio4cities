"""Chunk points for `source_chunks` (LLD-1 §5.1). One builder for a run's `fetch_parse`
and for `poe reindex` (E-05, BD-56), so the two can never write different payloads."""

from collections.abc import Mapping, Sequence
from datetime import date

from app.domain.ids import chunk_point_id
from app.domain.models import IndicatorDef, SlotDef
from app.ports.vector import VectorPoint
from app.workflow.rules.chunking import Chunk


def chunk_points(
    chunks: Sequence[Chunk],
    vectors: Sequence[list[float]],
    *,
    city_id: str,
    run_id: str,
    source_id: str,
    slot_ids: Sequence[str],
    lang: str,
    publisher_class: str,
    published_date: date | None,
) -> list[VectorPoint]:
    """One point per chunk; its text lives in the payload, tied to `source.parsed_text`
    by `source_id` and character offsets."""
    return [
        VectorPoint(
            id=chunk_point_id(source_id, c.index),
            vector=v,
            payload={
                "city_id": city_id,
                "run_id": run_id,
                "source_id": source_id,
                "slot_ids": list(slot_ids),
                "chunk_index": c.index,
                "char_start": c.start,
                "char_end": c.end,
                "text": c.text,
                "lang": lang,
                "publisher_class": publisher_class,
                "is_table": c.is_table,
                **({"published_date": published_date.isoformat()} if published_date else {}),
            },
        )
        for c, v in zip(chunks, vectors, strict=True)
    ]


def slot_table_keywords(slot: SlotDef, indicators: Mapping[str, IndicatorDef]) -> list[str]:
    """Words that mark a PDF page worth table extraction, from the slot's indicators."""
    words = {w.lower() for w in slot.short_label.split() if len(w) > 3}
    for code in slot.indicator_codes:
        if code in indicators:
            words |= {w.lower() for w in indicators[code].name.split() if len(w) > 3}
    return sorted(words)
