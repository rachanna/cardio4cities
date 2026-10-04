"""A RelationalPort stand-in; tests set the module-level values with monkeypatch."""

from typing import Any

from app.settings import Settings

SLOT_IDS: list[str] = [f"S{n:02d}" for n in range(1, 17)]
INDICATOR_CODES: dict[str, str] = {"world_bank.POP_TOTAL": "SP.POP.TOTL"}
FAIL: bool = False
PLACES: list[dict[str, Any]] = []  # search_places rows, best first
RUNS: dict[str, dict[str, Any]] = {}
PLACE_COUNT = 34_152  # a loaded gazetteer; set to 0 to test the start-up check
closed: list[bool] = []


class FakeReference:
    async def slot_ids(self) -> list[str]:
        if FAIL:
            raise ConnectionError("database unreachable")
        return list(SLOT_IDS)

    async def place_count(self) -> int:
        return PLACE_COUNT

    async def indicator_codes(self) -> dict[str, str]:
        return dict(INDICATOR_CODES)

    async def search_places(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return PLACES[:limit]


class FakeRuns:
    async def run_row(self, run_id: str) -> dict[str, Any] | None:
        return RUNS.get(run_id)

    async def stranded_runs(self) -> list[dict[str, Any]]:
        return []  # nothing left behind: start-up resumes nothing

    async def heartbeat(self, owner: str) -> None:
        pass


class FakeRelational:
    def __init__(self) -> None:
        self._reference = FakeReference()
        self.runs = FakeRuns()

    @property
    def reference(self) -> FakeReference:
        return self._reference

    async def ping(self) -> None:
        if FAIL:
            raise ConnectionError("database unreachable")

    async def close(self) -> None:
        closed.append(True)


def make(settings: Settings) -> FakeRelational:
    return FakeRelational()
