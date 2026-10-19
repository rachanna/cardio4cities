"""The agent's connection to the tools-and-prompts MCP server (E-15, BD-60).

Streamable HTTP with the agent's bearer token. Each call opens its own MCP client over a
shared HTTP client: the 2026-07-28 protocol is stateless, so nothing is lost, and no
client outlives the task that opened it. A transport failure or a tool error becomes
`ProviderUnavailableError`, as for any provider."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent

from app.ports.errors import PortError, ProviderUnavailableError


class ToolCaller(Protocol):
    def session(self) -> Any: ...  # an async context manager yielding an MCP `Client`

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class McpConnection:
    def __init__(self, url: str, token: str, timeout_s: float) -> None:
        self._url = url
        self._timeout_s = timeout_s
        self._http = httpx2.AsyncClient(
            headers={"authorization": f"Bearer {token}"}, timeout=timeout_s
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Client]:
        transport = streamable_http_client(self._url, http_client=self._http)
        async with (
            _as_port_errors(),
            Client(transport, read_timeout_seconds=self._timeout_s) as client,
        ):
            yield client

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self.session() as client:
            result = await client.call_tool(name, arguments)
        return structured(name, result)

    async def close(self) -> None:
        await self._http.aclose()


@asynccontextmanager
async def _as_port_errors() -> AsyncIterator[None]:
    """Any failure to reach or talk to the server (refused token, transport, protocol)
    becomes `ProviderUnavailableError`; a port error raised inside passes through."""
    try:
        yield
    except Exception as exc:
        leaf: BaseException = exc
        while isinstance(leaf, BaseExceptionGroup) and len(leaf.exceptions) == 1:
            leaf = leaf.exceptions[0]
        if isinstance(leaf, PortError):
            raise leaf from None
        raise ProviderUnavailableError(f"mcp: {type(leaf).__name__}") from exc


def structured(name: str, result: CallToolResult) -> dict[str, Any]:
    """The tool's structured result, or the tool's error as a provider failure."""
    if result.is_error or not isinstance(result.structured_content, dict):
        detail = " ".join(c.text for c in result.content if isinstance(c, TextContent))
        raise ProviderUnavailableError(f"mcp {name}: {detail or 'no structured result'}")
    return result.structured_content


class InProcessCaller:
    """A `ToolCaller` over an in-process server (tests): the same MCP protocol, no HTTP."""

    def __init__(self, server: Any) -> None:
        self._server = server

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Client]:
        async with _as_port_errors(), Client(self._server) as client:
            yield client

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self.session() as client:
            result = await client.call_tool(name, arguments)
        return structured(name, result)

    async def close(self) -> None:
        pass
