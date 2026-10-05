"""Health probe stand-ins; tests set DOWN with monkeypatch."""

from app.settings import Settings

DOWN: set[str] = set()
CALLS: list[str] = []  # every check made, by component


class FakeProbe:
    def __init__(self, component: str) -> None:
        self.component = component

    async def check(self) -> None:
        CALLS.append(self.component)
        if self.component in DOWN:
            raise ConnectionError(f"secret-host.internal:{self.component} refused")

    async def close(self) -> None:
        pass


def make_qdrant(settings: Settings) -> FakeProbe:
    return FakeProbe("qdrant")


def make_neo4j(settings: Settings) -> FakeProbe:
    return FakeProbe("neo4j")


def make_anthropic(settings: Settings) -> FakeProbe:
    return FakeProbe("llm_anthropic")


def make_openai(settings: Settings) -> FakeProbe:
    return FakeProbe("llm_openai")


def make_embeddings(settings: Settings, embeddings: object) -> FakeProbe:
    return FakeProbe("embeddings")


def make_search(settings: Settings, search: object) -> FakeProbe:
    return FakeProbe("search")
