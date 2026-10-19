"""The agent's prompts from the tools-and-prompts MCP server (E-15, BD-60).

Read once at start-up and installed with `use_served` (in the composition root), which
refuses any prompt whose version does not match this code's schema, context builder and
safety rules. A run therefore never changes prompts mid-way."""

import re

from mcp_types import TextContent

from app.adapters.mcp.connection import ToolCaller
from app.ports.errors import ProviderUnavailableError

_VERSION = re.compile(r"version=(\S+)")


async def served_prompts(caller: ToolCaller) -> list[tuple[str, str, str]]:
    """`(role, text, prompt_version)` for every prompt the server lists."""
    served = []
    async with caller.session() as client:
        listed = await client.list_prompts()
        for prompt in listed.prompts:
            got = await client.get_prompt(prompt.name)
            match = _VERSION.search(prompt.description or "")
            texts = [m.content.text for m in got.messages if isinstance(m.content, TextContent)]
            if match is None or len(texts) != 1:
                raise ProviderUnavailableError(f"mcp prompt {prompt.name}: unexpected shape")
            served.append((prompt.name, texts[0], match[1]))
    return served
