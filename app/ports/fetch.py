from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class FetchLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_bytes: int
    connect_timeout_s: float
    read_timeout_s: float
    max_redirects: int
    user_agent: str


class FetchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    final_url: str
    status: int
    headers: dict[str, str]
    content: bytes
    content_type: str | None
    redirect_chain: list[str]
    truncated: bool


RobotsOutcome = Literal["ok", "unavailable", "unreachable_network", "unreachable_server_error"]


class RobotsResult(BaseModel):
    """robots.txt as fetched, with RFC 9309 status handling (LLD-2 §9.2)."""

    model_config = ConfigDict(frozen=True)

    outcome: RobotsOutcome
    status: int | None
    body: str
    final_url: str | None


class FetchPort(Protocol):
    async def fetch(self, url: str, pinned_ip: str, limits: FetchLimits) -> FetchResult: ...

    async def fetch_robots(self, origin: str) -> RobotsResult: ...
