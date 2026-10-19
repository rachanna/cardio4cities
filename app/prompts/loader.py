"""Prompt files and their versions (LLD-3 §2.5): `prompt_version` is
`<role>@v<n>+<first 8 hex of sha256(prompt file + schema source)>`, recorded on every
claim, verdict and answer so each output traces to the exact prompt (R-62).

Served prompts (E-15, BD-60): the tools-and-prompts MCP server can own the prompt text.
At start-up the agent installs what it serves with `use_served`, which recomputes each
version from the served text and this code's own schema, context builder and safety
rules, and refuses any difference: a prompt never drifts from the schema that parses its
output, nor from the escaping that wraps fetched text."""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent
_VERSION = re.compile(r"^(?P<role>[a-z]+)@v(?P<n>\d+)\+[0-9a-f]{8}$")


@dataclass(frozen=True)
class Prompt:
    role: str
    version: int
    system: str
    prompt_version: str


class PromptMismatchError(Exception):
    """A served prompt does not match the schema, context builder or safety rules here."""


# The version each role runs now; earlier files stay for the record (R-62).
CURRENT = {
    "planner": 5,
    "extractor": 6,
    "checker": 4,
    "classifier": 2,
    "answerer": 2,
    "reporter": 1,
}  # classifier, answerer: BD-38; reporter: BD-40; extractor v5 (flat output): BD-45

_SERVED: dict[str, Prompt] = {}


@cache
def load_prompt(role: str, version: int | None = None) -> Prompt:
    version = version if version is not None else CURRENT[role]
    if version == CURRENT[role] and role in _SERVED:
        return _SERVED[role]
    text = prompt_text(role, version)
    return Prompt(role, version, text.strip(), _version_of(role, version, text))


def prompt_text(role: str, version: int) -> str:
    """The prompt file as its version hashes it (what the MCP server serves)."""
    # Line endings are normalised so a checkout's CRLF or LF never changes the version
    return _normalised((PROMPTS_DIR / role / f"v{version}.md").read_bytes()).decode("utf-8")


def _version_of(role: str, version: int, text: str) -> str:
    folder = PROMPTS_DIR / role
    schema = _normalised((folder / "schema.py").read_bytes())
    # What the model sees is built by context.py and escaped by safety.py: both count
    # towards the version (BD-26; code review RV-065)
    context = folder / "context.py"
    built = _normalised(context.read_bytes()) if context.exists() else b""
    shared = PROMPTS_DIR / "safety.py"
    safety = _normalised(shared.read_bytes()) if shared.exists() else b""
    body = _normalised(text.encode("utf-8"))
    digest = hashlib.sha256(body + schema + built + safety).hexdigest()[:8]
    return f"{role}@v{version}+{digest}"


def use_served(served: Iterable[tuple[str, str, str]]) -> None:
    """Install `(role, text, prompt_version)` for every current role, or refuse them all."""
    checked: dict[str, Prompt] = {}
    for role, text, prompt_version in served:
        match = _VERSION.match(prompt_version)
        if role not in CURRENT or match is None or match["role"] != role:
            raise PromptMismatchError(f"{role}: unexpected served version {prompt_version!r}")
        n = int(match["n"])
        if n != CURRENT[role]:
            raise PromptMismatchError(f"{role}: served v{n}, this code runs v{CURRENT[role]}")
        expected = _version_of(role, n, text)
        if prompt_version != expected:
            raise PromptMismatchError(
                f"{role}: served {prompt_version}, but its text with this code's schema, "
                f"context builder and safety rules is {expected}"
            )
        checked[role] = Prompt(role, n, text.strip(), prompt_version)
    if missing := sorted(set(CURRENT) - set(checked)):
        raise PromptMismatchError(f"not served: {', '.join(missing)}")
    _SERVED.clear()
    _SERVED.update(checked)
    load_prompt.cache_clear()


def served_roles() -> list[str]:
    return sorted(_SERVED)


def reset_served() -> None:
    """Back to the prompt files (tests)."""
    _SERVED.clear()
    load_prompt.cache_clear()


def _normalised(data: bytes) -> bytes:
    """CRLF to LF: a checkout's line endings never change a prompt's version."""
    return data.replace(b"\r\n", b"\n")
