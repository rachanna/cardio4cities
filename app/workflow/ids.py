"""IDs generated in the app (LLD-1 §0, LD-01).

`new_id`: prefixed ULIDs, sortable by time, for things created once (cities, runs,
entities). `stable_id`: derived from the run and the content, for anything a resumed
step may write again (searches, crawl decisions, sources, claims, contested pairs,
events), so a repeat finds the same row and `ON CONFLICT DO NOTHING` keeps one (BD-14).
Not in `domain/`: a ULID reads the clock."""

import base64
import hashlib
from typing import Literal

from ulid import ULID

Prefix = Literal["city", "run", "src", "clm", "ent", "evt", "ans", "conv", "cp", "cd", "sq", "rep"]


def new_id(prefix: Prefix) -> str:
    return f"{prefix}_{ULID()}"


def stable_id(prefix: Prefix, *parts: str) -> str:
    """The same parts always give the same 26-character ID (as long as a ULID)."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return f"{prefix}_{base64.b32encode(digest).decode('ascii')[:26]}"
