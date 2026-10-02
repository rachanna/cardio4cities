import sys

from app.container import build_container
from app.settings import load_settings
from tests.unit.fake_adapters.search import FakeSearch


def test_configured_providers_without_adapters_are_listed_missing(
    valid_env: dict[str, str],
) -> None:
    container = build_container(load_settings(valid_env), registry={})

    assert container.search is None
    assert {"llm:anthropic", "llm:openai", "search:searxng", "vector:qdrant"} <= set(
        container.missing
    )


def test_registered_adapter_is_built_from_settings(valid_env: dict[str, str]) -> None:
    registry = {"search": {"searxng": "tests.unit.fake_adapters.search:make"}}

    container = build_container(load_settings(valid_env), registry=registry)

    assert isinstance(container.search, FakeSearch)
    assert container.search.base_url == "http://127.0.0.1:8888"
    assert "search:searxng" not in container.missing


def test_unconfigured_provider_module_is_never_imported(valid_env: dict[str, str]) -> None:
    registry = {"search": {"brave": "tests.unit.fake_adapters.never_imported:make"}}

    build_container(load_settings(valid_env), registry=registry)

    assert "tests.unit.fake_adapters.never_imported" not in sys.modules
