"""Source and crawl-decision rows, and gzip snapshots (LLD-1 §4.3). Fictional city."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.adapters.postgres.relational import PostgresRelational
from app.adapters.snapshots.postgres import PostgresSnapshots, SnapshotTooLargeError
from app.domain.models import CrawlDecision, Source
from app.domain.vocab import CrawlOutcome, ParseOutcome, PublisherClass, SourceKind

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


async def _seed_run(relational: PostgresRelational) -> None:
    async with relational._engine.begin() as conn:
        for sql in (
            "INSERT INTO ref_country (iso2, iso3, name) VALUES ('XN', 'XNV', 'Norvania')",
            "INSERT INTO ref_place (gazetteer_id, name, ascii_name, country_iso2, lat, lon)"
            " VALUES ('9000001', 'Halden Bay', 'Halden Bay', 'XN', 60.1, 5.2)",
            "INSERT INTO city (city_id, gazetteer_id, identity)"
            " VALUES ('city_hb', '9000001', '{}')",
            "INSERT INTO run (run_id, city_id, status, budget, versions)"
            " VALUES ('run_1', 'city_hb', 'running', '{}', '{}')",
        ):
            await conn.execute(text(sql))


def _decision(outcome: CrawlOutcome = CrawlOutcome.ALLOWED) -> CrawlDecision:
    return CrawlDecision(
        decision_id="cd_1",
        run_id="run_1",
        url="https://health.halden-bay.test/report",
        domain="health.halden-bay.test",
        outcome=outcome,
        rule=None,
        reason="allowed by robots.txt",
        robots_http_status=200,
        decided_at=NOW,
    )


def _source() -> Source:
    return Source(
        source_id="src_1",
        run_id="run_1",
        url="https://health.halden-bay.test/report",
        url_canonical="https://health.halden-bay.test/report",
        domain="health.halden-bay.test",
        kind=SourceKind.WEB_HTML,
        publisher_class=PublisherClass.GOVERNMENT,
        title="Report",
        language="en",
        published_date=None,
        published_precision=None,
        retrieved_at=NOW,
        http_status=200,
        content_type="text/html",
        content_sha256=None,
        size_bytes=1200,
        parse_outcome=ParseOutcome.PARSED,
        found_via="search:sq_1",
    )


async def test_decision_and_source_rows_and_fetch_cache(relational: PostgresRelational) -> None:
    await _seed_run(relational)

    await relational.sources.add_crawl_decision(_decision())
    await relational.sources.add_source(_source(), "In Halden Bay, 31.2% of adults...", "cd_1")

    assert await relational.sources.fetched_urls("run_1") == {
        "https://health.halden-bay.test/report"
    }


async def test_same_canonical_url_twice_in_a_run_keeps_one_source(
    relational: PostgresRelational,
) -> None:
    """One source per URL per run (HD-01): the table enforces it, and a second page that
    redirected to the same URL finds the stored one instead of failing (BD-21)."""
    await _seed_run(relational)
    await relational.sources.add_source(_source(), "Parsed text.", None)

    await relational.sources.add_source(
        _source().model_copy(update={"source_id": "src_2"}), None, None
    )

    held = await relational.sources.source_at(_source().run_id, _source().url_canonical)
    assert held == ("src_1", True)


async def test_snapshot_round_trip_is_byte_exact(
    migrated: str, relational: PostgresRelational
) -> None:
    await _seed_run(relational)
    await relational.sources.add_source(_source(), None, None)
    snapshots = PostgresSnapshots(migrated, max_bytes=10_485_760)
    raw = b"<html>" + "Halden Bay – 31,2 %".encode() + b"</html>"

    try:
        ref = await snapshots.put("src_1", raw, "text/html")
        again = await snapshots.put("src_1", raw, "text/html")  # idempotent
        content, content_type = await snapshots.get("src_1")
    finally:
        await snapshots.close()

    assert (content, content_type) == (raw, "text/html")
    assert ref == again
    assert ref.size_bytes == len(raw)


async def test_snapshot_over_the_limit_is_refused(migrated: str) -> None:
    snapshots = PostgresSnapshots(migrated, max_bytes=10)
    try:
        with pytest.raises(SnapshotTooLargeError):
            await snapshots.put("src_1", b"x" * 11, "text/plain")
    finally:
        await snapshots.close()
