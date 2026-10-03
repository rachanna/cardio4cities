"""`app/domain` and `app/workflow/rules` stay pure (CLAUDE.md, How to work §3): no I/O
modules, no clock, no randomness, no file access. Time comes in as `today`."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PURE_DIRS = ("app/domain", "app/workflow/rules")
FORBIDDEN_MODULES = {
    "os", "io", "pathlib", "socket", "urllib", "http", "subprocess", "asyncio",
    "time", "random", "secrets", "shutil", "tempfile", "logging", "requests", "httpx",
}  # fmt: skip
FORBIDDEN_CALLS = {"open", "print", "input", "today", "now", "utcnow"}
ALLOWED_SUBMODULES = {"urllib.parse"}  # string handling only, no I/O


def _pure_files() -> list[Path]:
    return sorted(p for d in PURE_DIRS for p in (ROOT / d).rglob("*.py"))


@pytest.mark.parametrize("path", _pure_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_module_is_pure(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            names = []
        problems += [
            f"imports {n}"
            for n in names
            if n.split(".")[0] in FORBIDDEN_MODULES and n not in ALLOWED_SUBMODULES
        ]
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in FORBIDDEN_CALLS:
                problems.append(f"calls {name}() at line {node.lineno}")

    assert not problems, f"{path.name}: " + "; ".join(problems)


def test_scan_covers_the_rule_modules() -> None:
    names = {p.name for p in _pure_files()}

    assert {"quotes.py", "numbers.py", "consistency.py", "badges.py", "confidence.py"} <= names
