"""robots.txt parsing (LLD-2 §9.1 steps 5-6). The adapter wraps an RFC 9309 parser;
Content-Usage lines are parsed by our own code (app/workflow/rules/content_usage.py)."""

from typing import Protocol


class RobotsRules(Protocol):
    def can_fetch(self, url: str, user_agent: str) -> bool: ...

    def crawl_delay(self, user_agent: str) -> float | None: ...


class RobotsParser(Protocol):
    def parse(self, text: str) -> RobotsRules: ...
