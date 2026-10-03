"""Prompt files and their versions (LLD-3 §2.5): `prompt_version` is
`<role>@v<n>+<first 8 hex of sha256(prompt file + schema source)>`, recorded on every
claim, verdict and answer so each output traces to the exact prompt (R-62)."""

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    role: str
    version: int
    system: str
    prompt_version: str


# The version each role runs now; earlier files stay for the record (R-62).
CURRENT = {"planner": 1, "extractor": 2, "checker": 2}


@cache
def load_prompt(role: str, version: int | None = None) -> Prompt:
    version = version if version is not None else CURRENT[role]
    folder = PROMPTS_DIR / role
    # Line endings are normalised so a checkout's CRLF or LF never changes the version
    text = _normalised((folder / f"v{version}.md").read_bytes())
    schema = _normalised((folder / "schema.py").read_bytes())
    digest = hashlib.sha256(text + schema).hexdigest()[:8]
    return Prompt(role, version, text.decode("utf-8").strip(), f"{role}@v{version}+{digest}")


def _normalised(data: bytes) -> bytes:
    """CRLF to LF: a checkout's line endings never change a prompt's version."""
    return data.replace(b"\r\n", b"\n")
