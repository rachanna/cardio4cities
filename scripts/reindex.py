"""`poe reindex`: rebuild the derived stores from Postgres for the configured embedding
model (E-05, BD-56).

Postgres has the final word (RD-04): it holds every source's parsed text and every claim.
Qdrant's two collections and the graph's embeddings are derived from it, so they can be
rebuilt for any embedding model, and rebuilding repairs index drift (a missed upsert, a
stale chunk). What is rebuilt:

- `claim_index__{key}`: every supported or contested claim, by the same builder a run uses.
- `source_chunks__{key}`: every parsed source, cut by its stored table spans; a source
  stored before spans were kept is re-parsed from its snapshot, and the spans are used
  (and backfilled) only when the re-parsed text is identical to the stored text, so every
  claim's offsets stay true; otherwise it is cut as prose and counted.
- The graph: entity names and edge facts re-embedded in place with Graphiti's own Neo4j
  procedures; the embedding marker is switched last, so a stopped reindex leaves the old
  marker and runs keep refusing the graph until a reindex completes.

Local only: refuses APP_ENV=deployed and a graph that is not on this machine.

    uv run poe reindex [--dry-run] [--recreate] [--only claims|chunks|graph ...]
"""

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from app.adapters.embeddings.sentence_transformers import make as make_local_embeddings
from app.adapters.graph.graphiti import make as make_graph
from app.adapters.parse.documents import make as make_parser
from app.adapters.snapshots.postgres import make as make_snapshots
from app.adapters.vector.qdrant import make as make_vector
from app.ports.embeddings import EmbeddingsPort
from app.ports.parse import ParsedDocument
from app.settings import Settings, load_settings
from app.workflow.chunk_index import chunk_points, slot_table_keywords
from app.workflow.claim_index import claim_point, row_text
from app.workflow.collection import GENERIC_TYPES, parse_body
from app.workflow.deps import chunk_collection, claim_collection
from app.workflow.rules.chunking import ChunkParams, chunk_text
from scripts.purge_graph import is_local
from scripts.reference._db import relational_from_env

PARTS = ("claims", "chunks", "graph")


@dataclass
class Report:
    key: str = ""
    claims: int = 0
    sources: int = 0
    chunks: int = 0
    spans: dict[str, int] = field(default_factory=lambda: {"stored": 0, "reparsed": 0, "prose": 0})
    names: int = 0
    facts: int = 0
    marker: tuple[str | None, str | None] = (None, None)
    seconds: dict[str, float] = field(default_factory=dict)


def choose_spans(
    stored: Sequence[Sequence[int]] | None, parsed_text: str, reparsed: ParsedDocument | None
) -> tuple[list[tuple[int, int]], str]:
    """Table spans for a source, and where they came from. Re-parsed spans count only
    when the re-parsed text is the stored text, character for character: claim offsets
    refer to that text."""
    if stored is not None:
        return [(int(a), int(b)) for a, b in stored], "stored"
    if reparsed is not None and reparsed.text == parsed_text:
        return list(reparsed.tables), "reparsed"
    return [], "prose"


def mime_of(content_type: str | None, content: bytes) -> str:
    """The media type as the collector decides it, a PDF served generically included."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in GENERIC_TYPES and content.startswith(b"%PDF-"):
        return "application/pdf"
    return mime


def batches[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def embeddings_for(settings: Settings) -> EmbeddingsPort:
    """The configured model; hosted embeddings are refused here, so a reindex costs
    nothing (owner, BD-55: free development)."""
    if settings.config.embeddings.provider != "sentence_transformers":
        raise SystemExit(
            "reindex embeds with the local model only; set APP_ENV to a profile whose "
            "embeddings provider is sentence_transformers (for example local-free)"
        )
    return make_local_embeddings(settings)


async def reindex(
    settings: Settings, parts: Sequence[str], dry_run: bool, recreate: bool, batch: int
) -> Report:
    report = Report()
    embeddings = embeddings_for(settings)
    report.key = embeddings.key
    relational = relational_from_env()
    vector = make_vector(settings)
    graph = make_graph(settings, embeddings)
    snapshots = make_snapshots(settings)
    parser = make_parser(settings)
    claims_name, chunks_name = claim_collection(report.key), chunk_collection(report.key)
    try:
        if not dry_run:
            for name, part in ((claims_name, "claims"), (chunks_name, "chunks")):
                if part in parts:
                    if recreate:
                        await vector.drop_collection(name)
                    await vector.ensure_collection(name, embeddings.dimension)

        if "claims" in parts:
            start = time.perf_counter()
            research = relational.research
            ids = await research.indexed_claim_ids()
            rows = [r for r in [await research.claim_index_row(c) for c in ids] if r]
            report.claims = len(rows)
            if not dry_run:
                for claim_rows in batches(rows, batch):
                    claim_vectors = await embeddings.embed([row_text(r) for r in claim_rows])
                    await vector.upsert(
                        claims_name,
                        [
                            claim_point(r["claim_id"], r, v)
                            for r, v in zip(claim_rows, claim_vectors, strict=True)
                        ],
                    )
            report.seconds["claims"] = time.perf_counter() - start

        if "chunks" in parts:
            start = time.perf_counter()
            reference = relational.reference
            slots = {s.slot_id: s for s in await reference.slots()}
            indicators = {i.code: i for i in await reference.indicators()}
            params = ChunkParams(**settings.config.chunk.model_dump())
            for row in await relational.sources.sources_to_index():
                report.sources += 1
                text: str = row["parsed_text"]
                reparsed: ParsedDocument | None = None
                if row["table_spans"] is None:
                    try:
                        content, content_type = await snapshots.get(row["source_id"])
                    except Exception:  # no snapshot: cut as prose
                        content, content_type = b"", None
                    if content:
                        keywords = sorted(
                            {
                                w
                                for s in row["slot_ids"] or []
                                if s in slots
                                for w in slot_table_keywords(slots[s], indicators)
                            }
                        )
                        reparsed = parse_body(
                            parser,
                            content,
                            mime_of(content_type or row["content_type"], content),
                            row["url_canonical"],
                            content_type or row["content_type"],
                            keywords,
                        )
                spans, origin = choose_spans(row["table_spans"], text, reparsed)
                report.spans[origin] += 1
                chunks = chunk_text(text, spans, params)
                report.chunks += len(chunks)
                if dry_run or not chunks:
                    continue
                if origin == "reparsed":
                    await relational.sources.set_table_spans(row["source_id"], spans)
                for chunk_group in batches(chunks, batch):
                    chunk_vectors = await embeddings.embed([c.text for c in chunk_group])
                    await vector.upsert(
                        chunks_name,
                        chunk_points(
                            chunk_group,
                            chunk_vectors,
                            city_id=row["city_id"],
                            run_id=row["run_id"],
                            source_id=row["source_id"],
                            slot_ids=list(row["slot_ids"] or []),
                            lang=row["language"] or "",
                            publisher_class=row["publisher_class"],
                            published_date=row["published_date"],
                        ),
                    )
            report.seconds["chunks"] = time.perf_counter() - start

        if "graph" in parts:
            start = time.perf_counter()
            before = await graph.embedding_marker()
            names, facts = await graph.embedding_texts()
            report.names, report.facts = len(names), len(facts)
            report.marker = (before, before if dry_run else report.key)
            if not dry_run:
                flat = [t.replace("\n", " ") for _, t in [*names, *facts]]  # as graph writes embed
                vectors: list[list[float]] = []
                for group in batches(flat, batch):
                    vectors += await embeddings.embed(list(group))
                await graph.set_embeddings(
                    [(u, v) for (u, _), v in zip(names, vectors[: len(names)], strict=True)],
                    [(u, v) for (u, _), v in zip(facts, vectors[len(names) :], strict=True)],
                )
                await graph.set_embedding_marker(report.key)  # last: see the module docstring
            report.seconds["graph"] = time.perf_counter() - start
    finally:
        await graph.close()
        await vector.close()
        await relational.close()
    return report


def _print(report: Report, dry_run: bool) -> None:
    verb = "would rebuild" if dry_run else "rebuilt"
    print(f"reindex ({'dry run' if dry_run else 'done'}) for embedding key {report.key!r}")
    if "claims" in report.seconds:
        print(f"  claim_index: {verb} {report.claims} claims ({report.seconds['claims']:.1f} s)")
    if "chunks" in report.seconds:
        s = report.spans
        print(
            f"  source_chunks: {verb} {report.chunks} chunks from {report.sources} sources; "
            f"table spans stored {s['stored']}, from an exact re-parse {s['reparsed']}, "
            f"prose only {s['prose']} ({report.seconds['chunks']:.1f} s)"
        )
    if "graph" in report.seconds:
        print(
            f"  graph: {verb} {report.names} name and {report.facts} fact embeddings; "
            f"marker {report.marker[0]!r} -> {report.marker[1]!r} ({report.seconds['graph']:.1f} s)"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="count, change nothing")
    parser.add_argument(
        "--recreate", action="store_true", help="drop each collection first (clears stale points)"
    )
    parser.add_argument("--only", action="append", choices=PARTS, help="rebuild only these parts")
    parser.add_argument("--batch", type=int, default=64, help="texts per embedding call")
    args = parser.parse_args(argv)
    load_dotenv(".env", override=False)
    if os.environ.get("APP_ENV", "local") == "deployed":
        print("reindex refuses to run with APP_ENV=deployed", file=sys.stderr)
        return 2
    settings = load_settings()
    uri = settings.secret(settings.config.graph.uri_env)
    if not is_local(uri):
        print("reindex refuses a graph that is not on this machine", file=sys.stderr)
        return 2
    parts: list[Any] = args.only or list(PARTS)
    report = asyncio.run(reindex(settings, parts, args.dry_run, args.recreate, args.batch))
    _print(report, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
