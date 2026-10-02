"""Loading and validating the reference YAML files (LLD-1 §3.2 to §3.4). Pure."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.adapters.postgres.repos.reference import SourceEntry
from app.domain.models import IndicatorDef, SlotDef

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "reference"
PLACEHOLDER = re.compile(r"^\s*<.*>\s*$")


class ReferenceError(Exception):
    pass


class _SourceIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    age: tuple[int, int] | None = None


class _Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    adapter: str
    geography: str | list[str]
    representativeness: str | None = None
    indicators: dict[str, _SourceIndicator]


@dataclass(frozen=True)
class Sources:
    ready: list[SourceEntry]
    pending: dict[str, list[str]]  # provider -> indicators whose code is a placeholder


def _load[T](path: Path, kind: type[T]) -> T:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return TypeAdapter(kind).validate_python(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ReferenceError(f"{path.name}: {exc}") from exc


def read_slots(directory: Path = REFERENCE_DIR) -> list[SlotDef]:
    slots = _load(directory / "slots.yaml", list[SlotDef])
    ids = [s.slot_id for s in slots]
    expected = [f"S{n:02d}" for n in range(1, 17)]
    if sorted(ids) != expected:
        raise ReferenceError(f"slots.yaml must define exactly S01-S16 once each, found {ids}")
    headlines = [s.slot_id for s in slots if s.headline]
    if headlines != ["S04"]:
        raise ReferenceError(f"only S04 is the headline slot, found {headlines}")
    return slots


def read_indicators(directory: Path = REFERENCE_DIR) -> list[IndicatorDef]:
    indicators = _load(directory / "indicators.yaml", list[IndicatorDef])
    codes = [i.code for i in indicators]
    if len(codes) != len(set(codes)):
        raise ReferenceError(f"indicators.yaml has duplicate codes: {codes}")
    return indicators


def read_sources(directory: Path, indicator_codes: set[str]) -> Sources:
    """Split providers into ready ones and ones still holding placeholder codes (BD-03)."""
    sources = _load(directory / "sources.yaml", list[_Source])
    ready, pending = [], {}
    for source in sources:
        unknown = set(source.indicators) - indicator_codes
        if unknown:
            raise ReferenceError(f"sources.yaml {source.provider}: unknown indicators {unknown}")
        placeholders = [
            name
            for name, spec in source.indicators.items()
            if not spec.code.strip() or PLACEHOLDER.match(spec.code)
        ]
        if placeholders:
            pending[source.provider] = placeholders
            continue
        config = source.model_dump(exclude={"provider", "adapter"}, exclude_none=True)
        ready.append(SourceEntry(source.provider, source.adapter, config))
    return Sources(ready, pending)


def check_slot_targets(slots: list[SlotDef], indicator_codes: set[str]) -> None:
    for slot in slots:
        unknown = set(slot.indicator_codes) - indicator_codes
        if unknown:
            raise ReferenceError(f"slots.yaml {slot.slot_id}: unknown indicators {unknown}")
