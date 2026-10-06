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
CURRENT = {
    "planner": 4,
    "extractor": 6,
    "checker": 4,
    "classifier": 2,
    "answerer": 2,
    "reporter": 1,
}  # classifier, answerer: BD-38; reporter: BD-40; extractor v5 (flat output): BD-45


@cache
def load_prompt(role: str, version: int | None = None) -> Prompt:
    version = version if version is not None else CURRENT[role]
    folder = PROMPTS_DIR / role
    # Line endings are normalised so a checkout's CRLF or LF never changes the version
    text = _normalised((folder / f"v{version}.md").read_bytes())
    schema = _normalised((folder / "schema.py").read_bytes())
    # What the model sees is built by context.py and escaped by safety.py: both count
    # towards the version (BD-26; code review RV-065)
    context = folder / "context.py"
    built = _normalised(context.read_bytes()) if context.exists() else b""
    shared = PROMPTS_DIR / "safety.py"
    safety = _normalised(shared.read_bytes()) if shared.exists() else b""
    digest = hashlib.sha256(text + schema + built + safety).hexdigest()[:8]
    return Prompt(role, version, text.decode("utf-8").strip(), f"{role}@v{version}+{digest}")


def _normalised(data: bytes) -> bytes:
    """CRLF to LF: a checkout's line endings never change a prompt's version."""
    return data.replace(b"\r\n", b"\n")
