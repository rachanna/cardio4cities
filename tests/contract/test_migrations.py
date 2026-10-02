import asyncio

import asyncpg
import pytest
from alembic import command

from tests.contract.conftest import _plain, alembic_config

pytestmark = pytest.mark.db

TABLES = {
    "ref_country", "ref_admin1", "ref_place", "ref_slot", "ref_indicator", "ref_source",
    "city", "run", "run_event", "run_seq", "run_summary", "slot_result",
    "search_query", "crawl_decision", "source", "snapshot",
    "claim", "statistic", "entity", "entity_alias", "relation", "verdict", "consistency",
    "contested_pair", "graph_link",
    "answer", "report",
}  # fmt: skip
VIEWS = {"v_fact_evidence", "v_city_facts"}


async def _objects(url: str) -> dict[str, set[str]]:
    conn = await asyncpg.connect(_plain(url))
    try:
        rows = await conn.fetch(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'c4c'"
        )
    finally:
        await conn.close()
    found: dict[str, set[str]] = {"BASE TABLE": set(), "VIEW": set()}
    for row in rows:
        found[row["table_type"]].add(row["table_name"])
    return found


def test_migrations_create_every_table_and_view(migrated: str) -> None:
    found = asyncio.run(_objects(migrated))

    assert found["BASE TABLE"] == TABLES | {"alembic_version"}
    assert found["VIEW"] == VIEWS


def test_migrations_downgrade_to_base_and_upgrade_again(migrated: str) -> None:
    config = alembic_config(migrated)

    command.downgrade(config, "base")
    assert asyncio.run(_objects(migrated)) == {"BASE TABLE": {"alembic_version"}, "VIEW": set()}

    command.upgrade(config, "head")
    assert asyncio.run(_objects(migrated))["VIEW"] == VIEWS
