"""Prefixed ULIDs generated in the app (LLD-1 §0, LD-01): sortable by time and readable
in logs and citations, e.g. `src_01J9Z3K8Q2…`. Not in `domain/`: a ULID reads the clock."""

from typing import Literal

from ulid import ULID

Prefix = Literal["city", "run", "src", "clm", "ent", "evt", "ans", "cp", "cd", "sq", "rep"]


def new_id(prefix: Prefix) -> str:
    return f"{prefix}_{ULID()}"
