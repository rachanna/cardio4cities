"""Structured data from official APIs for Wave 0 (LLD-2 §13, LLD-4 §8; reshaped by BD-13).

Adapters are pure: they build request URLs and parse response bytes. Every request goes
through the collector's API path (`Collector.fetch_api`), so API hosts pass the same
address checks and pinning as any page, and the bytes parsed are the bytes stored in the
snapshot. Code verification re-parses the snapshot with the same adapter.
"""

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class StructuredRecord(BaseModel):
    """One observation as the provider published it."""

    model_config = ConfigDict(frozen=True)

    indicator_code: str  # the provider's code
    area_code: str  # ISO3 for national records
    year: int
    sex: str  # the provider's code, e.g. SEX_BTSX
    age_group: str | None  # the provider's code, when the indicator has an age dimension
    value_as_written: str  # the value exactly as the provider wrote it
    display: str | None = None  # the provider's display text, e.g. "31.1 [26.2-36.0]"


class StructuredDataPort(Protocol):
    provider: str

    def request_urls(
        self, code: str, country_iso3: str, params: Mapping[str, Any]
    ) -> list[str]: ...

    def parse(self, code: str, raw: bytes) -> list[StructuredRecord]:
        """Every record in the response; raises ValueError when the bytes do not parse."""
        ...
