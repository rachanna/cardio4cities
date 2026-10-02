import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from importlinter.cli import lint_imports

ROOT = Path(__file__).resolve().parents[2]
VENDOR_CONTRACT = "Vendor SDKs only in adapters"


def _importlinter_config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)["tool"]["importlinter"]
    return config


def _contract(name: str) -> dict[str, Any]:
    return next(c for c in _importlinter_config()["contracts"] if c["name"] == name)


def test_import_contracts_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-34: no module outside the adapters layer imports a vendor SDK; layers hold."""
    monkeypatch.chdir(ROOT)

    assert lint_imports(no_cache=True, no_logo=True) == 0


def test_vendor_contract_matches_repo_structure() -> None:
    """AT-34: the enforced vendor list is the one REPO_STRUCTURE §3 names, no shorter."""
    text = (ROOT / "docs/design/REPO_STRUCTURE.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("**Vendor packages allowed"))
    documented = set(re.findall(r"`([a-z0-9_]+)`", line))

    assert set(_contract(VENDOR_CONTRACT)["forbidden_modules"]) == documented


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)  # strings and lists of strings are valid TOML as JSON


def _write_probe(tmp_path: Path, violation: str) -> Path:
    """A copy of the app's layout as `probeapp`, with one deliberate violation in domain."""
    for package in ("api", "workflow", "query", "report", "prompts", "ports", "domain", "adapters"):
        (tmp_path / "probeapp" / package).mkdir(parents=True)
        (tmp_path / "probeapp" / package / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "probeapp" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "probeapp" / "container.py").write_text("", encoding="utf-8")
    (tmp_path / "probeapp" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "probeapp" / "domain" / "bad.py").write_text(violation, encoding="utf-8")

    config = _importlinter_config()
    lines = ["[tool.importlinter]", 'root_package = "probeapp"']
    lines.append(f"include_external_packages = {_toml_value(config['include_external_packages'])}")
    for contract in config["contracts"]:
        lines.append("[[tool.importlinter.contracts]]")
        for key, value in contract.items():
            renamed = json.loads(re.sub(r"\bapp\.", "probeapp.", json.dumps(value)))
            lines.append(f"{key} = {_toml_value(renamed)}")
    path = tmp_path / "probe.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("source", "exit_code"),
    [
        ("import json\n", 0),
        ("import httpx\n", 1),
        ("import probeapp.api\n", 1),
        ("import probeapp.adapters\n", 1),
    ],
    ids=["clean-control", "vendor-sdk", "upward-layer", "adapter-from-core"],
)
def test_contracts_catch_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, exit_code: int
) -> None:
    """AT-34: the same contracts, applied to a probe package, fail on each kind of violation.

    The clean control proves the probe is well formed, so a failure means a real violation.
    """
    config_file = _write_probe(tmp_path, source)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert lint_imports(config_filename=str(config_file), no_cache=True, no_logo=True) == exit_code
