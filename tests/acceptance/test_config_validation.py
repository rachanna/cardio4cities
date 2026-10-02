from typing import Any

import pytest

from app.settings import ConfigError, load_settings
from tests.conftest import ConfigWriter


def _same_family_checker(raw: dict[str, Any]) -> None:
    raw["llm"]["roles"]["checker"] = {
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "family": "anthropic",
    }


def test_same_family_checker_refused_without_flag(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    """AT-36: checker and extractor share a model family, no flag: start-up refused, clearly."""
    config_dir = write_config(change=_same_family_checker)

    with pytest.raises(ConfigError) as exc:
        load_settings(valid_env, config_dir)

    message = str(exc.value)
    assert "checker independence" in message
    assert "llm.roles.checker.family ('anthropic')" in message
    assert "llm.allow_same_family_checker" in message


def test_same_family_checker_allowed_with_flag_and_labelled(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    """AT-36: with the explicit flag a same-family checker starts, and is reported as such."""

    def change(raw: dict[str, Any]) -> None:
        _same_family_checker(raw)
        raw["llm"]["allow_same_family_checker"] = True

    settings = load_settings(valid_env, write_config(change=change))

    assert settings.same_family_checker


def test_shipped_configs_have_independent_checker(valid_env: dict[str, str]) -> None:
    """AT-36: the checked-in local config passes the independence check as shipped."""
    settings = load_settings(valid_env)

    assert not settings.same_family_checker
