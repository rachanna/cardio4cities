"""Run ownership across processes (BD-25; code review RV-067, RV-035): a live owner keeps
its run, a quiet one is taken over exactly once, the database allows one active run, and
a resume that fails before the claim does not spend the run's one resume. Fictional data."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters.postgres.relational import PostgresRelational
from app.settings import load_settings
from app.workflow.runner import RunManager

pytestmark = pytest.mark.db


async def _seed(relational: PostgresRelational, quiet_s: float, owner: str = "proc_old") -> None:
    """A run owned by `owner`, whose last heartbeat was `quiet_s` seconds ago."""
    async with relational._engine.begin() as conn:
        for sql in (
            "INSERT INTO ref_country (iso2, iso3, name) VALUES ('XN', 'XNV', 'Norvania')",
            "INSERT INTO ref_place (gazetteer_id, name, ascii_name, country_iso2, lat, lon)"
            " VALUES ('9000001', 'Halden Bay', 'Halden Bay', 'XN', 60.1, 5.2)",
            "INSERT INTO city (city_id, gazetteer_id, identity)"
            " VALUES ('city_hb', '9000001', '{}')",
        ):
            await conn.execute(text(sql))
        await conn.execute(
            text(
                "INSERT INTO run (run_id, city_id, status, budget, versions, owner, heartbeat_at)"
                " VALUES ('run_1', 'city_hb', 'running', '{}', '{}', :o,"
                " now() - make_interval(secs => :quiet))"
            ),
            {"o": owner, "quiet": quiet_s},
        )


async def _attempts(relational: PostgresRelational) -> int:
    row = await relational.runs.run_row("run_1")
    assert row is not None
    return int(row["resume_attempts"])


async def test_a_live_owner_keeps_its_run(relational: PostgresRelational) -> None:
    await _seed(relational, 0)
    assert not await relational.runs.claim_stale("run_1", "proc_new", 45)
    assert await _attempts(relational) == 0


async def test_a_quiet_run_is_taken_over_exactly_once(relational: PostgresRelational) -> None:
    """Two new processes race for it: one atomic update, one winner."""
    await _seed(relational, 120)
    first = await relational.runs.claim_stale("run_1", "proc_a", 45)
    second = await relational.runs.claim_stale("run_1", "proc_b", 45)
    assert (first, second) == (True, False)
    assert await _attempts(relational) == 1
    row = await relational.runs.run_row("run_1")
    assert row is not None
    assert row["owner"] == "proc_a"


async def test_the_database_allows_one_active_run(relational: PostgresRelational) -> None:
    await _seed(relational, 0)
    with pytest.raises(IntegrityError):
        async with relational._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO run (run_id, city_id, status, budget, versions)"
                    " VALUES ('run_2', 'city_hb', 'queued', '{}', '{}')"
                )
            )


class Saver:
    async def aget_tuple(self, config: dict[str, Any]) -> object:
        return object()  # a checkpoint exists


class Checkpointer:
    async def saver(self) -> Saver:
        return Saver()


async def test_a_resume_that_fails_before_the_claim_is_not_spent(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> None:
    """RV-035: the resume was counted before the steps that can fail on a store, so one
    outage at start-up spent it and the next boot failed the run."""
    await _seed(relational, 120)
    ports = type("Ports", (), {"relational": relational, "checkpointer": Checkpointer(),
                               "search": None, "graph": None})()  # fmt: skip
    manager = RunManager(ports, load_settings({**valid_env, "DATABASE_URL": migrated}))
    assert await manager.resume_stranded() == []  # building its dependencies fails
    assert await _attempts(relational) == 0
    row = await relational.runs.run_row("run_1")
    assert row is not None
    assert row["status"] == "running"  # still resumable
