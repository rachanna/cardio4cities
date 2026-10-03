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


@cache
def load_prompt(role: str, version: int = 1) -> Prompt:
    folder = PROMPTS_DIR / role
    text = (folder / f"v{version}.md").read_bytes()
    schema = (folder / "schema.py").read_bytes()
    digest = hashlib.sha256(text + schema).hexdigest()[:8]
    return Prompt(role, version, text.decode("utf-8").strip(), f"{role}@v{version}+{digest}")
