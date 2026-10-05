"""`poe purge CITY` (LLD-1 §8, BD-36, BD-42): remove one city from every store before the
demo, keeping only the named fallback city (D4-7).

    python -m scripts.purge_city --list           # cities, with their IDs and runs
    python -m scripts.purge_city CITY_ID          # what would be deleted (nothing is)
    python -m scripts.purge_city CITY_ID --yes    # delete it

Order: the city's Qdrant points (page chunks and the claim index, by `city_id`), then its
Graphiti partition (`group_id`), then Postgres and the LangGraph checkpoints in one
transaction. A store failure stops the purge before Postgres, so running it again finds
the city and finishes the job. A city with a queued or running run is refused. Runs on
any profile, deployed included: it is how rehearsal cities are removed."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

from dotenv import load_dotenv

from app.adapters.graph.graphiti import make as make_graph
from app.adapters.postgres.relational import PostgresRelational
from app.adapters.vector.qdrant import make as make_vector
from app.ports.graph import GraphPort
from app.ports.vector import VectorPort
from app.settings import load_settings
from app.workflow.deps import chunk_collection, claim_collection


class _NoEmbeddings:
    """Purging embeds nothing; the graph adapter only needs the store's embedding key."""

    def __init__(self, key: str, dimension: int) -> None:
        self.key, self.dimension = key, dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("purge-city embeds nothing")


@dataclass
class Outcome:
    collections: list[str] = field(default_factory=list)  # Qdrant collections cleared
    graph: bool = False
    rows: dict[str, int] = field(default_factory=dict)


class PurgeRefused(Exception):
    pass


async def purge_city(
    city_id: str,
    relational: PostgresRelational,
    vector: VectorPort,
    graph: GraphPort,
    collections: Sequence[str],
) -> Outcome:
    city = await relational.purge.city(city_id)
    if city is None:
        raise PurgeRefused(f"no city {city_id!r}: `--list` shows the cities")
    if city.active_runs:
        raise PurgeRefused(f"{city_id} has a queued or running run: wait for it to finish")
    outcome = Outcome()
    for name in collections:
        if await vector.collection_dimension(name) is not None:
            await vector.delete_by_filter(name, {"city_id": city_id})
            outcome.collections.append(name)
    await graph.delete_group(city_id)
    outcome.graph = True
    outcome.rows = await relational.purge.purge(city_id)
    return outcome


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    relational = PostgresRelational(settings.secret(settings.config.relational.dsn_env))
    try:
        if args.list or not args.city_id:
            for c in await relational.purge.cities():
                active = f", {c.active_runs} active" if c.active_runs else ""
                plural = "" if c.runs == 1 else "s"
                print(f"{c.city_id}  {c.name}, {c.country}  ({c.runs} run{plural}{active})")
            return 0
        city = await relational.purge.city(args.city_id)
        if city is None:
            print(f"no city {args.city_id!r}: `--list` shows the cities", file=sys.stderr)
            return 1
        if not args.yes:
            counts = await relational.purge.counts(args.city_id)
            print(f"would delete {city.name}, {city.country} ({city.city_id}):")
            for table, n in counts.items():
                if n:
                    print(f"  {table}: {n}")
            print("  plus its Qdrant points, its graph partition and its runs' checkpoints")
            print("nothing was deleted; add --yes to delete")
            return 0
        e = settings.config.embeddings
        vector = make_vector(settings)
        graph = make_graph(settings, _NoEmbeddings(e.key, e.dimension))
        try:
            collections = [chunk_collection(e.key), claim_collection(e.key)]
            outcome = await purge_city(args.city_id, relational, vector, graph, collections)
        finally:
            await graph.close()
            await vector.close()
    except PurgeRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        await relational.close()
    rows = sum(outcome.rows.values())
    print(
        f"purged {city.name}, {city.country} ({city.city_id}): {rows} rows, "
        f"Qdrant {', '.join(outcome.collections) or 'no collections'}, graph partition"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(".env", override=False)
    parser = argparse.ArgumentParser(prog="purge_city", description=__doc__.splitlines()[0])
    parser.add_argument("city_id", nargs="?", help="the city's ID, as `--list` shows it")
    parser.add_argument("--list", action="store_true", help="list cities and exit")
    parser.add_argument("--yes", action="store_true", help="delete (otherwise a dry run)")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
