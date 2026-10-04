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


def test_current_versions_are_the_bd22_prompts() -> None:
    assert loader.load_prompt("extractor").version == 3  # BD-22: located labels, v3 vocabulary
    assert loader.load_prompt("checker").version == 3  # BD-22: case definition and sample size
    assert loader.load_prompt("planner").version == 3  # BD-15: queries per slot from config
