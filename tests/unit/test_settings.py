from pathlib import Path
from typing import Any

import pytest

from app.settings import (
    CONFIG_DIR,
    ConfigError,
    check_embedding_dimension,
    check_indicator_codes,
    check_reference_slots,
    load_settings,
)
from tests.conftest import ConfigWriter


def _problems(env: dict[str, str], config_dir: Path = CONFIG_DIR) -> list[str]:
    with pytest.raises(ConfigError) as exc:
        load_settings(env, config_dir)
    return exc.value.problems


def _restore_day1_placeholders(raw: dict[str, Any]) -> None:
    raw["app"]["public_base_url"] = "<confirm day 1>"
    raw["llm"]["roles"]["checker"]["model"] = "<confirm day 1>"
    raw["embeddings"].update(model="<confirm day 1>", dimension=0)
    raw["budget"].update(tokens=0, cost_micro_usd=0)


# --- shipped configs -------------------------------------------------------


def test_local_config_loads(valid_env: dict[str, str]) -> None:
    settings = load_settings(valid_env)

    assert settings.env == "local"
    assert settings.config.search.provider == "searxng"
    assert settings.config.search.mode == "links_only"


def test_local_does_not_need_brave_qdrant_or_langsmith_keys(valid_env: dict[str, str]) -> None:
    for name in ("BRAVE_API_KEY", "QDRANT_API_KEY", "LANGSMITH_API_KEY"):
        del valid_env[name]

    load_settings(valid_env)


def test_local_allows_placeholders(valid_env: dict[str, str]) -> None:
    settings = load_settings(valid_env)

    assert settings.config.embeddings.dimension == 0


def test_deployed_refuses_day1_placeholders_and_zero_budgets(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    valid_env["APP_ENV"] = "deployed"
    config_dir = write_config("deployed", _restore_day1_placeholders)

    problems = "\n".join(_problems(valid_env, config_dir))

    for expected in (
        "app.public_base_url: placeholder",
        "llm.roles.checker.model: placeholder",
        "embeddings.model: placeholder",
        "budget.tokens: 0",
        "budget.cost_micro_usd: 0",
        "embeddings.dimension: 0",
    ):
        assert expected in problems


def test_shipped_deployed_config_passes_validation(valid_env: dict[str, str]) -> None:
    """BD-04: confirmed model IDs and provisional budgets; nothing left as a placeholder."""
    valid_env["APP_ENV"] = "deployed"

    config = load_settings(valid_env).config

    assert config.search.provider == "brave"
    assert config.llm.roles.checker.model == "gpt-6-astra"
    assert (config.embeddings.model, config.embeddings.dimension) == (
        "text-embedding-3-small",
        1536,
    )
    assert config.budget.tokens > 0
    assert config.budget.cost_micro_usd > 0


# --- file shape ---------------------------------------------------------------


def test_unknown_key_refused(write_config: ConfigWriter, valid_env: dict[str, str]) -> None:
    config_dir = write_config(change=lambda raw: raw["fetch"].update(max_byte=1))

    assert any("fetch.max_byte" in p for p in _problems(valid_env, config_dir))


def test_search_mode_must_be_links_only(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    config_dir = write_config(change=lambda raw: raw["search"].update(mode="content"))

    assert any("search.mode" in p for p in _problems(valid_env, config_dir))


def test_invalid_app_env_refused(valid_env: dict[str, str]) -> None:
    valid_env["APP_ENV"] = "staging"

    assert _problems(valid_env) == ["APP_ENV must be 'local' or 'deployed', not 'staging'"]


def test_missing_config_file_refused(tmp_path: Path, valid_env: dict[str, str]) -> None:
    assert "config file not found" in _problems(valid_env, tmp_path)[0]


def test_undeclared_llm_provider_refused(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    config_dir = write_config(
        change=lambda raw: raw["llm"]["roles"]["planner"].update(provider="unknown")
    )

    assert any("llm.roles.planner" in p for p in _problems(valid_env, config_dir))


def test_searxng_needs_base_url(write_config: ConfigWriter, valid_env: dict[str, str]) -> None:
    config_dir = write_config(change=lambda raw: raw["search"].pop("base_url"))

    assert "search.base_url is required for provider 'searxng'" in _problems(valid_env, config_dir)


# --- secrets and access ---------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_secret_named(valid_env: dict[str, str], value: str | None) -> None:
    if value is None:
        del valid_env["OPENAI_API_KEY"]
    else:
        valid_env["OPENAI_API_KEY"] = value

    assert (
        "environment variable OPENAI_API_KEY is not set (needed by llm.providers.openai)"
        in _problems(valid_env)
    )


def test_langsmith_key_needed_only_when_enabled(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    del valid_env["LANGSMITH_API_KEY"]
    config_dir = write_config(
        change=lambda raw: raw["tracing"].update(
            providers=["events", "langsmith"], langsmith_api_key_env="LANGSMITH_API_KEY"
        )
    )

    assert any("LANGSMITH_API_KEY" in p for p in _problems(valid_env, config_dir))


def test_short_access_code_refused(valid_env: dict[str, str]) -> None:
    valid_env["ACCESS_CODE"] = "short"

    assert "ACCESS_CODE must be at least 12 characters" in _problems(valid_env)


def test_admin_code_equal_to_access_code_refused(valid_env: dict[str, str]) -> None:
    valid_env["ADMIN_CODE"] = valid_env["ACCESS_CODE"]

    assert "ADMIN_CODE must differ from ACCESS_CODE" in _problems(valid_env)


def test_all_problems_reported_together(valid_env: dict[str, str]) -> None:
    valid_env["ACCESS_CODE"] = "short"
    del valid_env["NEO4J_PASSWORD"]

    assert len(_problems(valid_env)) == 2


def test_secrets_resolved_and_not_in_repr(valid_env: dict[str, str]) -> None:
    settings = load_settings(valid_env)

    assert settings.secret("ANTHROPIC_API_KEY") == "test-anthropic-key"
    assert "test-anthropic-key" not in repr(settings)


def test_unreferenced_environment_not_held(valid_env: dict[str, str]) -> None:
    valid_env["UNRELATED"] = "x"
    settings = load_settings(valid_env)

    with pytest.raises(KeyError):
        settings.secret("UNRELATED")


# --- checks that start-up runs once adapters and tables exist (BD-02) ---------


def test_embedding_dimension_matches() -> None:
    assert check_embedding_dimension(1536, 1536, "source_chunks__k", None) == []
    assert check_embedding_dimension(1536, 1536, "source_chunks__k", 1536) == []


def test_embedding_dimension_differs_from_provider() -> None:
    assert check_embedding_dimension(1536, 3072, "source_chunks__k", None) == [
        "embeddings.dimension is 1536 but the provider reports 3072"
    ]


def test_existing_collection_with_other_size_refused() -> None:
    problems = check_embedding_dimension(1536, 1536, "source_chunks__k", 768)

    assert "would mix embedding models" in problems[0]


def test_reference_slots_exactly_s01_to_s16() -> None:
    expected = [f"S{n:02d}" for n in range(1, 17)]

    assert check_reference_slots(expected) == []
    assert "missing: ['S16']" in check_reference_slots(expected[:-1])[0]
    assert "unexpected: ['S17']" in check_reference_slots([*expected, "S17"])[0]


def test_empty_reference_slots_point_to_the_loader() -> None:
    assert check_reference_slots([]) == [
        "ref_slot is empty: run `poe reference` against DATABASE_URL"
    ]


def test_placeholder_indicator_codes_refused() -> None:
    problems = check_indicator_codes(
        {
            "world_bank.POP_TOTAL": "SP.POP.TOTL",
            "who_gho.HTN_PREV": "<GHO indicator code, confirmed day 1>",
            "dhs.HTN_PREV": "",
        }
    )

    assert len(problems) == 2
    assert all("placeholder" in p for p in problems)
