"""World Bank Indicators API (LLD-4 §8, spike S-2, BD-13). Pure: builds the request URL
and parses the response. The collector makes the request."""

import json
import re
from collections.abc import Mapping
from typing import Any

from app.ports.structured import StructuredRecord
from app.settings import Settings

RECENT_YEARS = 10  # the last ten published years; Wave 0 keeps the latest
_CODE = re.compile(r"^[A-Za-z0-9_.]+$")
_ISO3 = re.compile(r"^[A-Z]{3}$")


class WorldBank:
    provider = "world_bank"

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def request_urls(self, code: str, country_iso3: str, params: Mapping[str, Any]) -> list[str]:
        if not _CODE.match(code) or not _ISO3.match(country_iso3):
            raise ValueError("indicator and country codes come from the registry and gazetteer")
        return [
            f"{self._base}/country/{country_iso3}/indicator/{code}"
            f"?format=json&per_page=100&mrv={RECENT_YEARS}"
        ]

    def parse(self, code: str, raw: bytes) -> list[StructuredRecord]:
        try:
            payload = json.loads(raw.decode("utf-8"))
            rows = payload[1] or []
        except (UnicodeDecodeError, json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
            raise ValueError(f"not a World Bank API response: {type(exc).__name__}") from exc
        records = []
        for row in rows:
            value = row.get("value")
            if value is None or not str(row.get("date", "")).isdigit():
                continue
            records.append(
                StructuredRecord(
                    indicator_code=str(row["indicator"]["id"]),
                    area_code=str(row["countryiso3code"]),
                    year=int(row["date"]),
                    sex="total",
                    age_group=None,
                    value_as_written=str(value),
                )
            )
        return records


def make(settings: Settings) -> WorldBank:
    return WorldBank(settings.config.structured.providers["world_bank"].base_url)
