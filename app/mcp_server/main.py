"""Composition root of the tools-and-prompts MCP server (E-15, BD-60): `uv run poe mcp`.

Builds the profile's search adapter and the current prompts, wraps the Streamable HTTP
endpoint in the access gate, and serves it on loopback. Refused with APP_ENV=deployed:
a remote server needs OAuth first (BD-60)."""

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp

from app.container import ADAPTERS, AdapterRegistry
from app.logs import setup_logging
from app.main import APP_VERSION
from app.mcp_server.access import Access, AccessGate, Caller
from app.mcp_server.tools import ServedPrompt, build_server
from app.prompts.loader import CURRENT, load_prompt, prompt_text
from app.settings import ConfigError, Settings, load_settings

log = logging.getLogger(__name__)


def current_prompts() -> list[ServedPrompt]:
    return [
        ServedPrompt(role, prompt_text(role, n), load_prompt(role).prompt_version)
        for role, n in sorted(CURRENT.items())
    ]


def callers(settings: Settings, env: dict[str, str]) -> dict[str, Caller]:
    """Each configured client whose token is set; one without a token cannot connect."""
    found: dict[str, Caller] = {}
    for c in settings.config.mcp.clients:
        token = env.get(c.token_env, "").strip()
        if token:
            found[token] = Caller(c.name, c.calls_per_minute, c.searches_per_day)
        else:
            log.warning("mcp: %s has no token (%s), so it cannot connect", c.name, c.token_env)
    return found


def _search(settings: Settings, registry: AdapterRegistry) -> Any:
    target = registry["search"].get(settings.config.search.provider)
    if target is None:
        return None
    module_name, _, attr = target.partition(":")
    return getattr(importlib.import_module(module_name), attr)(settings)


def build_app(
    settings: Settings, env: dict[str, str], registry: AdapterRegistry = ADAPTERS
) -> ASGIApp:
    if settings.env == "deployed":
        raise ConfigError(["the tools-and-prompts server is local only until it has OAuth (BD-60)"])
    mcp = settings.config.mcp
    tokens = callers(settings, env)
    if not tokens:
        raise ConfigError(
            [f"no mcp.clients token is set ({', '.join(c.token_env for c in mcp.clients)})"]
        )
    access = Access(tokens)
    server = build_server(
        search=_search(settings, registry),
        prompts=current_prompts(),
        access=access,
        max_query_chars=mcp.max_query_chars,
        max_links=mcp.max_links,
        version=APP_VERSION,
    )
    hosts = [f"{mcp.host}:{mcp.port}", f"localhost:{mcp.port}", f"127.0.0.1:{mcp.port}"]
    app = server.streamable_http_app(
        streamable_http_path=mcp.path,
        stateless_http=True,  # 2026-07-28: no sessions; every request stands alone
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[f"http://{h}" for h in hosts],
        ),
        host=mcp.host,
    )
    return AccessGate(app, access)


def main() -> int:
    env_file = Path(".env")
    if env_file.exists():
        load_dotenv(env_file, override=False)  # never overrides real environment variables
    try:
        settings = load_settings()
        setup_logging(settings.config.logging.level, settings.config.logging.format)
        app = build_app(settings, dict(os.environ))
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    import uvicorn

    mcp = settings.config.mcp
    log.info("tools-and-prompts server on %s", mcp.url)
    uvicorn.run(app, host=mcp.host, port=mcp.port, log_level="warning")
    return 0
