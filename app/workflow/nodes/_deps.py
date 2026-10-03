"""Nodes receive their dependencies through the LangGraph run config."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.workflow.deps import RunDeps


def deps(config: RunnableConfig) -> RunDeps:
    configurable: dict[str, Any] = config.get("configurable") or {}
    found = configurable.get("deps")
    if not isinstance(found, RunDeps):
        raise RuntimeError("run config carries no RunDeps")
    return found
