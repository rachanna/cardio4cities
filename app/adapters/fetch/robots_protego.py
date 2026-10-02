"""RobotsParser over Protego (RFC 9309), behaviour pinned by tests/contract/test_parsers.py."""

from protego import Protego

from app.settings import Settings


class _ProtegoRules:
    def __init__(self, parsed: Protego) -> None:
        self._parsed = parsed

    def can_fetch(self, url: str, user_agent: str) -> bool:
        return bool(self._parsed.can_fetch(url, user_agent))

    def crawl_delay(self, user_agent: str) -> float | None:
        delay = self._parsed.crawl_delay(user_agent)
        return float(delay) if delay is not None else None


class ProtegoRobotsParser:
    def parse(self, text: str) -> _ProtegoRules:
        return _ProtegoRules(Protego.parse(text))


def make(settings: Settings) -> ProtegoRobotsParser:
    return ProtegoRobotsParser()
