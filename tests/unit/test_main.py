import re
from pathlib import Path

import pytest

from app.container import Container
from app.main import create_app
from app.settings import ConfigError
from tests.unit.fake_adapters import relational as fake_relational

FAKE_REGISTRY = {"relational": {"postgres": "tests.unit.fake_adapters.relational:make"}}


@pytest.fixture
def environ(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> pytest.MonkeyPatch:
    for name, value in valid_env.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


async def test_app_starts_with_valid_config_and_reference_data(
    environ: pytest.MonkeyPatch,
) -> None:
    app = create_app(env_file=None, registry=FAKE_REGISTRY)

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.container, Container)


async def test_app_refuses_to_start_with_bad_config(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("ACCESS_CODE", "short")
    app = create_app(env_file=None, registry=FAKE_REGISTRY)

    with pytest.raises(ConfigError, match="ACCESS_CODE must be at least 12"):
        async with app.router.lifespan_context(app):
            pass


async def test_env_file_never_overrides_real_environment(
    environ: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ACCESS_CODE=short\n", encoding="utf-8")
    app = create_app(env_file=env_file, registry=FAKE_REGISTRY)

    async with app.router.lifespan_context(app):
        assert app.state.container.settings.env == "local"


async def test_app_refuses_to_start_without_all_slots(environ: pytest.MonkeyPatch) -> None:
    environ.setattr(fake_relational, "SLOT_IDS", ["S01", "S02"])
    app = create_app(env_file=None, registry=FAKE_REGISTRY)

    with pytest.raises(ConfigError, match="ref_slot must hold exactly S01-S16"):
        async with app.router.lifespan_context(app):
            pass


async def test_app_refuses_to_start_with_placeholder_indicator_code(
    environ: pytest.MonkeyPatch,
) -> None:
    environ.setattr(fake_relational, "INDICATOR_CODES", {"who_gho.HTN_PREV": "<code>"})
    app = create_app(env_file=None, registry=FAKE_REGISTRY)

    with pytest.raises(ConfigError, match=re.escape("who_gho.HTN_PREV")):
        async with app.router.lifespan_context(app):
            pass


async def test_unreadable_database_refused_with_next_step_and_closed(
    environ: pytest.MonkeyPatch,
) -> None:
    environ.setattr(fake_relational, "FAIL", True)
    environ.setattr(fake_relational, "closed", [])
    app = create_app(env_file=None, registry=FAKE_REGISTRY)

    with pytest.raises(ConfigError, match=re.escape("run `poe migrate` and `poe reference`")):
        async with app.router.lifespan_context(app):
            pass
    assert fake_relational.closed == [True]
