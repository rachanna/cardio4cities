from pathlib import Path

import pytest

from app.container import Container
from app.main import create_app
from app.settings import ConfigError


@pytest.fixture
def environ(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> pytest.MonkeyPatch:
    for name, value in valid_env.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


async def test_app_starts_with_valid_config(environ: pytest.MonkeyPatch) -> None:
    app = create_app(env_file=None)

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.container, Container)


async def test_app_refuses_to_start_with_bad_config(environ: pytest.MonkeyPatch) -> None:
    environ.setenv("ACCESS_CODE", "short")
    app = create_app(env_file=None)

    with pytest.raises(ConfigError, match="ACCESS_CODE must be at least 12"):
        async with app.router.lifespan_context(app):
            pass


async def test_env_file_never_overrides_real_environment(
    environ: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ACCESS_CODE=short\n", encoding="utf-8")
    app = create_app(env_file=env_file)

    async with app.router.lifespan_context(app):
        assert app.state.container.settings.env == "local"
