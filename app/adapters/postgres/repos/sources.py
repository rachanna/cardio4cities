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
                ),
                values,
            )

    async def fetched_urls(self, run_id: str) -> set[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT url_canonical FROM source WHERE run_id = :run_id"), {"run_id": run_id}
            )
            return {row.url_canonical for row in rows}

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
