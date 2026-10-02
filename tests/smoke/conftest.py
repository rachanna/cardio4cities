import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--smoke-url", default=os.environ.get("SMOKE_URL", ""), help="Deployed base URL"
    )


@pytest.fixture(scope="session")
def smoke_url(request: pytest.FixtureRequest) -> str:
    url = str(request.config.getoption("--smoke-url")).rstrip("/")
    if not url:
        pytest.skip("set a URL: uv run poe smoke <url>")
    return url
