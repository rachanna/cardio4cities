"""Crawl decisions and sources (LLD-1 §4.3). One fetch per canonical URL per run (HD-01)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import CrawlDecision, Source


class PostgresSourceRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add_crawl_decision(self, decision: CrawlDecision) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO crawl_decision (decision_id, run_id, url, domain, outcome, rule,"
                    " reason, robots_http_status, decided_at) VALUES (:decision_id, :run_id, :url,"
                    " :domain, :outcome, :rule, :reason, :robots_http_status, :decided_at)"
                    " ON CONFLICT (decision_id) DO NOTHING"
                ),
                decision.model_dump(mode="python") | {"outcome": decision.outcome.value},
            )

    async def add_source(
        self, source: Source, parsed_text: str | None, crawl_decision_id: str | None
    ) -> None:
        values = source.model_dump(mode="python")
        values.update(
            kind=source.kind.value,
            publisher_class=source.publisher_class.value,
            published_precision=source.published_precision.value
            if source.published_precision
            else None,
            parse_outcome=source.parse_outcome.value if source.parse_outcome else None,
            parsed_text=parsed_text,
            crawl_decision_id=crawl_decision_id,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO source (source_id, run_id, url, url_canonical, domain, kind,"
                    " publisher_class, title, language, published_date, published_precision,"
                    " retrieved_at, http_status, content_type, content_sha256, size_bytes,"
                    " parse_outcome, parsed_text, found_via, crawl_decision_id) VALUES"
                    " (:source_id, :run_id, :url, :url_canonical, :domain, :kind,"
                    " :publisher_class, :title, :language, :published_date, :published_precision,"
                    " :retrieved_at, :http_status, :content_type, :content_sha256, :size_bytes,"
                    " :parse_outcome, :parsed_text, :found_via, :crawl_decision_id)"
                    # the source ID, or the run's canonical URL (a converging redirect)
                    " ON CONFLICT DO NOTHING"
                ),
                values,
            )

    async def source_at(self, run_id: str, url_canonical: str) -> tuple[str, bool] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT source_id, parsed_text IS NOT NULL AS parsed FROM source"
                        " WHERE run_id = :r AND url_canonical = :u"
                    ),
                    {"r": run_id, "u": url_canonical},
                )
            ).first()
            return (row.source_id, bool(row.parsed)) if row else None

    async def fetched_urls(self, run_id: str) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT url_canonical FROM source WHERE run_id = :run_id"), {"run_id": run_id}
            )
            return {row.url_canonical for row in rows}

    async def set_parsed_text(self, source_id: str, parsed_text: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE source SET parsed_text = :t WHERE source_id = :s"),
                {"t": parsed_text, "s": source_id},
            )

    async def source_for_extraction(self, source_id: str) -> dict[str, object] | None:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT source_id, url, title, publisher_class, published_date,"
                            " published_precision, language, parsed_text FROM source"
                            " WHERE source_id = :s"
                        ),
                        {"s": source_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def fetched_sources(self, run_id: str) -> dict[str, str | None]:
        """URL -> source ID for the run's stored pages; None when the page gave no text.
        Seeds the fetch cache on resume (BD-14)."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT url, url_canonical, source_id, parse_outcome FROM source"
                    " WHERE run_id = :r AND kind <> 'structured_api'"
                ),
                {"r": run_id},
            )
            found: dict[str, str | None] = {}
            for r in rows:
                held = r.source_id if r.parse_outcome == "parsed" else None
                found.setdefault(r.url_canonical, held)
                found[r.url] = held
            return found

    async def crawl_outcomes(self, decision_ids: list[str]) -> list[str]:
        if not decision_ids:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT outcome FROM crawl_decision WHERE decision_id = ANY(:ids)"),
                {"ids": decision_ids},
            )
            return [r.outcome for r in rows]

    async def outcome_counts(self, run_id: str) -> dict[str, dict[str, int]]:
        """Run summary (AT-38): crawl decisions by outcome, and stored pages by parse
        outcome, counted once per URL."""
        async with self._engine.connect() as conn:
            crawl = await conn.execute(
                text(
                    "SELECT outcome, count(DISTINCT url) AS n FROM crawl_decision"
                    " WHERE run_id = :r GROUP BY outcome"
                ),
                {"r": run_id},
            )
            parse = await conn.execute(
                text(
                    "SELECT coalesce(parse_outcome, 'none') AS outcome, count(*) AS n FROM source"
                    " WHERE run_id = :r AND kind <> 'structured_api' GROUP BY 1"
                ),
                {"r": run_id},
            )
            return {
                "crawl": {r.outcome: int(r.n) for r in crawl},
                "parse": {r.outcome: int(r.n) for r in parse},
            }
