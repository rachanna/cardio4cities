"""Load slots, indicators and the source registry into ref_slot, ref_indicator, ref_source.

    python -m scripts.reference.load_yaml_reference [--strict]

Providers whose indicator codes are still placeholders are never written; they
are listed as pending. With --strict (deployed), any pending provider is an
error (BD-03). Idempotent: a second run reports zero changes.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from scripts.reference._db import relational_from_env
from scripts.reference.yaml_reference import (
    REFERENCE_DIR,
    ReferenceError,
    check_slot_targets,
    read_indicators,
    read_slots,
    read_sources,
)


async def load(directory: Path, strict: bool) -> int:
    slots = read_slots(directory)
    indicators = read_indicators(directory)
    codes = {i.code for i in indicators}
    check_slot_targets(slots, codes)
    sources = read_sources(directory, codes)
    if strict and sources.pending:
        raise ReferenceError(f"placeholder indicator codes (--strict): {sources.pending}")

    relational = relational_from_env()
    try:
        print(await relational.reference.sync_indicators(indicators))
        print(await relational.reference.sync_slots(slots))
        print(await relational.reference.sync_sources(sources.ready))
    finally:
        await relational.close()
    for provider, names in sources.pending.items():
        print(f"pending: {provider} not loaded, placeholder codes for {', '.join(names)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="fail on placeholder codes")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(load(REFERENCE_DIR, args.strict))
    except ReferenceError as exc:
        print(f"reference data refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
