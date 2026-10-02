from app.ports.search import SearchHit
from app.settings import Settings


class FakeSearch:
    def __init__(self, base_url: str | None) -> None:
        self.base_url = base_url

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        return []


def make(settings: Settings) -> FakeSearch:
    return FakeSearch(settings.config.search.base_url)
