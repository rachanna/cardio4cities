"""Prompt versions (LLD-3 §2.5, R-62) depend on content, never on a checkout's line endings."""

from pathlib import Path

import pytest

from app.prompts import loader


def test_crlf_and_lf_checkouts_give_the_same_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = []
    for ending in ("\n", "\r\n"):
        folder = tmp_path / ending.encode().hex() / "checker"
        folder.mkdir(parents=True)
        (folder / "v1.md").write_bytes(ending.join(["Judge.", "Rules."]).encode())
        (folder / "schema.py").write_bytes(ending.join(["x = 1", ""]).encode())
        monkeypatch.setattr(loader, "PROMPTS_DIR", folder.parent)
        loader.load_prompt.cache_clear()
        versions.append(loader.load_prompt("checker", 1).prompt_version)
    loader.load_prompt.cache_clear()
    assert versions[0] == versions[1]
    assert versions[0].startswith("checker@v1+")


def test_current_versions_are_the_bd26_prompts() -> None:
    assert loader.load_prompt("extractor").version == 4  # BD-26: new examples, field rules
    assert loader.load_prompt("checker").version == 4  # BD-26: evidence before the verdict
    assert loader.load_prompt("planner").version == 4  # BD-31: English only


def test_the_version_changes_when_the_context_builder_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RV-065 (BD-26): what the model sees is built by context.py; it counts."""
    versions = []
    for body in ("lines = ['a']", "lines = ['b']"):
        folder = tmp_path / body[-3] / "checker"
        folder.mkdir(parents=True)
        (folder / "v1.md").write_text("Judge.", encoding="utf-8")
        (folder / "schema.py").write_text("x = 1", encoding="utf-8")
        (folder / "context.py").write_text(body, encoding="utf-8")
        monkeypatch.setattr(loader, "PROMPTS_DIR", folder.parent)
        loader.load_prompt.cache_clear()
        versions.append(loader.load_prompt("checker", 1).prompt_version)
    loader.load_prompt.cache_clear()
    assert versions[0] != versions[1]
