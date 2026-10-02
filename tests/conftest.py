"""Shared fixtures. Values are obviously fake; no real secrets or city data."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.settings import CONFIG_DIR

ConfigWriter = Callable[..., Path]


@pytest.fixture
def valid_env() -> dict[str, str]:
    return {
        "APP_ENV": "local",
        "ACCESS_CODE": "test-access-code-123",
        "ADMIN_CODE": "test-admin-code-456",
        "SESSION_SECRET": "test-session-secret",
        "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
        "QDRANT_URL": "http://localhost:6333",
        "QDRANT_API_KEY": "test-qdrant-key",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "test-neo4j-password",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "OPENAI_API_KEY": "test-openai-key",
        "BRAVE_API_KEY": "test-brave-key",
        "LANGSMITH_API_KEY": "test-langsmith-key",
    }


@pytest.fixture
def write_config(tmp_path: Path) -> ConfigWriter:
    """Copy a real config file into tmp_path, optionally changed, and return the directory."""

    def write(env: str = "local", change: Callable[[dict[str, Any]], None] | None = None) -> Path:
        raw = yaml.safe_load((CONFIG_DIR / f"{env}.yaml").read_text(encoding="utf-8"))
        if change is not None:
            change(raw)
        (tmp_path / f"{env}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
        return tmp_path

    return write
