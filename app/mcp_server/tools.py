"""The tools-and-prompts MCP server (E-15, BD-60): search links and the agent's prompts,
for this agent and for outside MCP clients.

- `search_links` returns links only (R-58, AT-33): a URL, title, short snippet and rank.
  A snippet ranks a link; it is never evidence. Every page is read through the crawl
  gate, which stays in the agent, so no tool here fetches a page.
- One MCP prompt per model role serves the system prompt the agent runs now, as one
  message. Its description carries the version (`version=<role>@v<n>+<hash>`), which the
  agent checks against its own schema, context builder and safety rules at start-up.

Phase 2 (fetch with the crawl gate, parsing, structured data) is designed separately:
those tools must keep the gate's decision before any content request and the bytes
parsed identical to the bytes stored (BD-60)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.prompts.base import Prompt as McpPrompt
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from app.mcp_server.access import Access, Caller
from app.ports.errors import PortError
from app.ports.search import SearchPort

VERSION_IN_DESCRIPTION = re.compile(r"version=(\S+)")

ROLE_TITLES = {
    "planner": "Plan search queries for one research slot",
    "extractor": "Extract claims with exact quotes from one window of a page",
    "checker": "Check one claim against its passage",
    "classifier": "Understand a City Lead's question",
    "answerer": "Answer from verified evidence only",
    "reporter": "Write the report's prose from verified facts",
}


@dataclass(frozen=True)
class ServedPrompt:
    role: str
    text: str  # the prompt file as its version hashes it
    prompt_version: str


class SearchLink(BaseModel):
    url: str
    title: str
    snippet: str = Field(description="Ranks the link only; never evidence")
    rank: int


class SearchLinks(BaseModel):
    links: list[SearchLink]


def build_server(
    *,
    search: SearchPort | None,
    prompts: Sequence[ServedPrompt],
    access: Access,
    max_query_chars: int,
    max_links: int,
    in_process: Caller | None = None,
    version: str = "",
) -> MCPServer:
    """`in_process`: the caller for a connection without HTTP headers (in-process tests);
    without it such calls are refused, so only token-bearing HTTP callers get through."""
    server = MCPServer(
        name="cardio4cities-tools",
        title="Cardio4Cities tools and prompts",
        version=version,
        instructions=(
            "Search returns links only: a snippet ranks a link and is never evidence; read "
            "pages through your own crawl rules. Prompts are the system prompts the "
            "Cardio4Cities agent runs, each with its version in the description."
        ),
    )

    def caller_of(ctx: Context) -> Caller:
        headers = ctx.headers
        caller = in_process if headers is None else access.identify(headers.get("authorization"))
        if caller is None:
            raise ToolError("not authorised")
        return caller

    if search is not None:

        @server.tool(
            name="search_links",
            title="Search the web for links",
            description=(
                "Web search that returns links only (URL, title, snippet, rank). Snippets "
                "rank links and are never evidence. Read-only; counts against your daily "
                "search quota."
            ),
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True
            ),
        )
        async def search_links(
            query: str, ctx: Context, lang: str = "en", limit: int = 10
        ) -> SearchLinks:
            caller = caller_of(ctx)
            query = query.strip()
            if not query or len(query) > max_query_chars:
                raise ToolError(f"query must be 1 to {max_query_chars} characters")
            if not 1 <= limit <= max_links:
                raise ToolError(f"limit must be 1 to {max_links}")
            if not re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", lang):
                raise ToolError("lang must be a language code such as 'en'")
            if not access.allow_search(caller):
                raise ToolError("daily search quota reached")
            try:
                hits = await search.search(query, lang, limit)
            except PortError as exc:
                raise ToolError("search is unavailable right now") from exc
            return SearchLinks(
                links=[
                    SearchLink(url=h.url, title=h.title, snippet=h.snippet, rank=h.rank)
                    for h in hits
                ]
            )

    for served in sorted(prompts, key=lambda p: p.role):

        def render(text: str = served.text) -> str:
            return text

        server.add_prompt(
            McpPrompt.from_function(
                render,
                name=served.role,
                title=ROLE_TITLES.get(served.role, served.role),
                description=(
                    f"System prompt of the {served.role} role, as one message. "
                    f"version={served.prompt_version}"
                ),
            )
        )
    return server
