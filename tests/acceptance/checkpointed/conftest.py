"""Tests that run the LangGraph Postgres checkpointer (BD-14). psycopg's async mode needs
a selector event loop, which Windows does not use by default; Linux (CI, deployment)
runs the default loop."""

import asyncio
import sys
from collections.abc import Callable, Mapping

import pytest


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}
