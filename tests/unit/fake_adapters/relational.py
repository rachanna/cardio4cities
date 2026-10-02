"""A RelationalPort stand-in; tests set the module-level values with monkeypatch."""

from app.settings import Settings

SLOT_IDS: list[str] = [f"S{n:02d}" for n in range(1, 17)]
INDICATOR_CODES: dict[str, str] = {"world_bank.POP_TOTAL": "SP.POP.TOTL"}
FAIL: bool = False
closed: list[bool] = []


class FakeReference:
    async def slot_ids(self) -> list[str]:
        if FAIL:
            raise ConnectionError("database unreachable")
        return list(SLOT_IDS)

    async def indicator_codes(self) -> dict[str, str]:
        return dict(INDICATOR_CODES)


class FakeRelational:
    def __init__(self) -> None:
        self._reference = FakeReference()

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
