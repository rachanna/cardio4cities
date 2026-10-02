"""Every package in the REPO_STRUCTURE §1 layout exists and imports cleanly."""

import importlib
import pkgutil

import pytest

import app

PACKAGES = sorted(name for _, name, is_pkg in pkgutil.walk_packages(app.__path__, "app.") if is_pkg)


def test_layout_packages_found() -> None:
    assert {"app.domain", "app.ports", "app.adapters", "app.workflow.rules"} <= set(PACKAGES)


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)


def test_app_factory_builds() -> None:
    from app.main import create_app

    assert create_app().title == "CARDIO4Cities"
