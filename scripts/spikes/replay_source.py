"""BD-10 check: replay one stored source through the current parser, extractor, quote
matching, geography fit and checker, without touching the web. Costs model calls only:
ask the owner first.

Takes a source an earlier run fetched through the crawl gate, re-parses its stored
snapshot (so parser changes apply), and runs the slot nodes extract -> match_quotes ->
verify -> consistency -> write in a new run for the same city. The source URL and the
city come from the database; nothing city-specific is written to the repository.

    uv run python -m scripts.spikes.replay_source --source-id <src_...> [--slot S04]
"""

import argparse
import asyncio
import gzip
import sys
import time
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from sqlalchemy import text

from app.container import build_container
from app.domain.models import Source
from app.domain.vocab import EventType, ParseOutcome
from app.settings import load_settings
from app.workflow.ids import new_id
from app.workflow.nodes.consistency import consistency
from app.workflow.nodes.extract import extract
from app.workflow.nodes.finish import slot_done, write
from app.workflow.nodes.match_quotes import match_quotes
from app.workflow.nodes.verify import verify
from app.workflow.runner import RunManager, model_versions
from scripts.spikes.thin_slice import capped, report


async def main(source_id: str, slot: str, max_usd: float) -> int:
    load_dotenv(".env", override=False)
    settings = capped(load_settings(), max_usd)
    container = build_container(settings)
    relational = container.relational
    if relational is None or container.parser is None:
        print("needs the relational store and the parser")
        return 1
    try:
        async with relational._engine.connect() as conn:  # type: ignore[attr-defined]
            row = (await conn.execute(text(
                "SELECT s.*, r.city_id, n.content_gz FROM source s JOIN run r USING (run_id)"
                " JOIN snapshot n USING (source_id) WHERE s.source_id = :s"),
                {"s": source_id})).mappings().one()  # fmt: skip
        raw = gzip.decompress(row["content_gz"])
        doc = container.parser.parse_html(raw, row["url"])
        print(f"re-parsed {len(doc.text)} characters, {len(doc.tables)} tables")
        manager = RunManager(container, settings)
        run_id = new_id("run")
        deps = await manager.build_deps(run_id)
        runs = relational.runs
        await runs.create_run(run_id, row["city_id"], deps.ledger.limits.__dict__,
                              model_versions(deps.roles))  # fmt: skip
        await runs.set_status(run_id, "running")
        city = await runs.city_identity(row["city_id"])
        source = Source(
            source_id=new_id("src"), run_id=run_id, url=row["url"],
            url_canonical=row["url_canonical"], domain=row["domain"], kind=row["kind"],
            publisher_class=row["publisher_class"], title=doc.title, language=doc.language,
            published_date=doc.published_date, published_precision=None,
            retrieved_at=datetime.now(UTC), http_status=row["http_status"],
            content_type=row["content_type"], content_sha256=sha256(raw).hexdigest(),
            size_bytes=len(raw), parse_outcome=ParseOutcome.PARSED,
            found_via=f"replay:{source_id}",
        )  # fmt: skip
        await relational.sources.add_source(source, doc.text, None)
        await container.snapshots.put(source.source_id, raw, row["content_type"] or "text/html")  # type: ignore[union-attr]
        config: RunnableConfig = {"configurable": {"deps": deps}}
        state: dict[str, Any] = {"run_id": run_id, "city": city, "slot_id": slot, "round": 0,
                                 "source_ids": [source.source_id], "claim_ids": []}  # fmt: skip
        started = time.monotonic()
        for node in (extract, match_quotes, verify, consistency, write):
            update = await node(state, config)  # type: ignore[arg-type]
            state.update(update)
        reports = slot_done(state)["slot_reports"]  # type: ignore[arg-type]
        summary = {
            "slots": {k: v.model_dump() for k, v in reports.items()},
            "budget": deps.ledger.snapshot(),
        }
        await runs.save_summary(run_id, summary)
        await deps.events.emit(run_id, EventType.RUN_FINISHED,
                               {"status": "completed", "summary": summary})  # fmt: skip
        await runs.set_status(run_id, "completed")
        return await report(relational, run_id, time.monotonic() - started)
    finally:
        await container.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--slot", default="S04")
    parser.add_argument("--max-usd", type=float, default=0.3)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(asyncio.run(main(args.source_id, args.slot, args.max_usd)))
