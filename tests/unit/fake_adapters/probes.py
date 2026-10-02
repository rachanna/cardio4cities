"""Health probe stand-ins; tests set DOWN with monkeypatch."""

from app.settings import Settings

DOWN: set[str] = set()


class FakeProbe:
    def __init__(self, component: str) -> None:
        self.component = component

    async def check(self) -> None:
        if self.component in DOWN:
            raise ConnectionError(f"secret-host.internal:{self.component} refused")

    async def close(self) -> None:
        pass


def make_qdrant(settings: Settings) -> FakeProbe:
    return FakeProbe("qdrant")


def make_neo4j(settings: Settings) -> FakeProbe:
    return FakeProbe("neo4j")
