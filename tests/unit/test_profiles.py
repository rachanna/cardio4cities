"""Model profiles (BD-05): local, local-quality and deployed stay in step, and every
binding sends only the setting its model accepts."""

from typing import Any

import pytest
import yaml

from app.settings import CONFIG_DIR, ConfigError, load_settings
from tests.conftest import ConfigWriter

PROFILES = ("local", "local-quality", "local-openai", "deployed")
MODEL_SECTIONS = ("llm", "embeddings")


def _raw(profile: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((CONFIG_DIR / f"{profile}.yaml").read_text("utf-8"))
    return data


def _bindings(raw: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for role in raw["llm"]["roles"].values():
        found.append(role)
        found += [role[k] for k in ("escalate_to", "fallback") if k in role]
    return found


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_loads(profile: str, valid_env: dict[str, str]) -> None:
    valid_env["APP_ENV"] = profile

    assert load_settings(valid_env).env == profile


def test_local_quality_is_local_with_the_deployed_model_bindings() -> None:
    local, quality, deployed = _raw("local"), _raw("local-quality"), _raw("deployed")

    for section in quality:
        if section in MODEL_SECTIONS:
            assert quality[section] == deployed[section], section
        elif section == "budget":  # the cost cap follows from the models
            expected = {**local["budget"], "tokens": quality["budget"]["tokens"]}
            expected["cost_micro_usd"] = quality["budget"]["cost_micro_usd"]
            assert quality["budget"] == expected
        else:
            assert quality[section] == local[section], section
    assert set(quality) == set(local)


@pytest.mark.parametrize("profile", PROFILES)
def test_bindings_send_only_settings_their_model_accepts(profile: str) -> None:
    """Haiku 4.5 errors on effort; Sonnet/Opus 5.5 reject temperature; Sol has no none/minimal."""
    for binding in _bindings(_raw(profile)):
        model = binding["model"]
        if model.startswith("claude-haiku-4-5"):
            assert "effort" not in binding, binding
        if model.startswith(("claude-sonnet-5-5", "claude-opus-5-5")):
            assert "temperature" not in binding, binding
        if model == "gpt-6.1-sol":
            assert binding.get("effort") not in ("none", "minimal"), binding


def test_local_profile_is_low_cost() -> None:
    raw = _raw("local")
    roles = raw["llm"]["roles"]

    for name in ("planner", "extractor", "classifier", "answerer", "reporter"):
        assert roles[name]["model"].startswith("claude-haiku-4-5"), name
    assert "escalate_to" not in roles["extractor"]
    assert (roles["checker"]["model"], roles["checker"]["effort"]) == ("gpt-6-luna", "low")
    assert raw["embeddings"]["provider"] == "sentence_transformers"
    assert raw["verify"]["max_claims_per_slot"] == 5  # owner, BD-10: a Luna check costs ~$0.0002
    assert raw["search"]["provider"] == "searxng"


def test_deployed_checker_is_sol_on_low_effort_with_opus_fallback() -> None:
    checker = _raw("deployed")["llm"]["roles"]["checker"]

    assert (checker["model"], checker["effort"]) == ("gpt-6.1-sol", "low")
    assert checker["fallback"]["model"] == "claude-opus-5-5"


def test_every_profile_caps_a_run_at_the_owners_limits() -> None:
    """BD-15: $3 a run, set from the S-6 measurements; BD-46: 120 fetches and 3M tokens,
    so weak questions get their re-plan rounds; the $3 cap still bounds the spend."""
    for p in PROFILES:
        budget = _raw(p)["budget"]
        assert (budget["cost_micro_usd"], budget["tokens"]) == (3_000_000, 3_000_000), p
        assert budget["fetches"] == 120, p


def _ollama_checker(raw: dict[str, Any]) -> None:
    raw["llm"]["roles"]["checker"] = {"provider": "ollama", "model": "qwen2.5:3b", "family": "qwen"}


def test_ollama_checker_needs_its_address(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    config_dir = write_config(change=_ollama_checker)

    with pytest.raises(ConfigError, match="OLLAMA_BASE_URL"):
        load_settings(valid_env, config_dir)

    valid_env["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
    settings = load_settings(valid_env, config_dir)
    assert settings.secret("OLLAMA_BASE_URL") == "http://127.0.0.1:11434"
    assert not settings.same_family_checker  # qwen is independent of the anthropic extractor


def test_effort_and_temperature_together_refused(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    config_dir = write_config(
        change=lambda raw: raw["llm"]["roles"]["planner"].update(effort="low", temperature=0.3)
    )

    with pytest.raises(ConfigError, match="set effort or temperature, not both"):
        load_settings(valid_env, config_dir)


def test_unknown_effort_value_refused(
    write_config: ConfigWriter, valid_env: dict[str, str]
) -> None:
    config_dir = write_config(
        change=lambda raw: raw["llm"]["roles"]["checker"].update(effort="extreme")
    )

    with pytest.raises(ConfigError, match=r"llm\.roles\.checker\.effort"):
        load_settings(valid_env, config_dir)


def test_local_openai_is_local_with_every_role_on_openai() -> None:
    """BD-23: development on the owner's OpenAI budget. Only the model bindings and the
    labelled same-family exception differ from local."""
    local, dev = _raw("local"), _raw("local-openai")
    assert set(dev) == set(local)
    for section in dev:
        if section == "llm":
            other = ("roles", "allow_same_family_checker")
            assert {k: v for k, v in dev["llm"].items() if k not in other} == {
                k: v for k, v in local["llm"].items() if k not in other
            }
        else:
            assert dev[section] == local[section], section
    assert all(b["provider"] == "openai" for b in _bindings(dev))
    assert dev["llm"]["allow_same_family_checker"] is True
    checker = dev["llm"]["roles"]["checker"]
    assert (checker["model"], checker["effort"]) == ("gpt-6.1-sol", "low")
