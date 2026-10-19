"""SearchPort through the tools-and-prompts MCP server (E-15, BD-60): the same links-only
contract as the in-process adapters (R-58, AT-33), so the workflow cannot tell them apart.
The run's budget ledger still reserves before every search, in the workflow."""

from app.adapters.mcp.connection import McpConnection, ToolCaller
from app.adapters.search._common import SearchProbe
from app.ports.errors import ProviderUnavailableError
from app.ports.search import SearchHit
from app.settings import Settings


class McpSearch:
    def __init__(self, caller: ToolCaller) -> None:
        self._caller = caller

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        data = await self._caller.call_tool(
            "search_links", {"query": query, "lang": lang, "limit": limit}
        )
        try:
            return [SearchHit.model_validate(link) for link in data["links"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError("mcp search_links: unexpected result") from exc

    async def close(self) -> None:
        await self._caller.close()


def connection(settings: Settings) -> McpConnection:
    mcp = settings.config.mcp
    agent = mcp.client(mcp.agent_client)
    if agent is None:
        raise ValueError("mcp.agent_client is not one of mcp.clients")
    return McpConnection(mcp.url, settings.secret(agent.token_env), mcp.timeout_s)


def make(settings: Settings) -> McpSearch:
    return McpSearch(connection(settings))


def make_probe(settings: Settings, search: McpSearch) -> SearchProbe:
    return SearchProbe(search)  # one search through the server, so the server is checked too
