"""WHO Global Health Observatory OData API (LLD-4 §8, spike S-2, BD-13). Pure: builds the
request URL and parses the response. The collector makes the request.

A record's value is copied as the provider wrote it: the leading number of its display
text ("31.1" from "31.1 [26.2-36.0]"); the display text is kept beside it.
"""

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from app.ports.structured import StructuredRecord
from app.settings import Settings

_LEADING_NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")
_CODE = re.compile(r"^[A-Za-z0-9_.]+$")
_ISO3 = re.compile(r"^[A-Z]{3}$")


class WhoGho:
    provider = "who_gho"

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def request_urls(self, code: str, country_iso3: str, params: Mapping[str, Any]) -> list[str]:
        if not _CODE.match(code) or not _ISO3.match(country_iso3):
            raise ValueError("indicator and country codes come from the registry and gazetteer")
        odata_filter = quote(f"SpatialDim eq '{country_iso3}'", safe="")
        return [f"{self._base}/{code}?$filter={odata_filter}"]

    def parse(self, code: str, raw: bytes) -> list[StructuredRecord]:
        try:
            rows = json.loads(raw.decode("utf-8"))["value"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"not a GHO OData response: {type(exc).__name__}") from exc
        records = []
        for row in rows:
            display = row.get("Value")
            match = _LEADING_NUMBER.match(display) if isinstance(display, str) else None
            if match is None or row.get("TimeDim") is None:
                continue  # no published value
            records.append(
                StructuredRecord(
                    indicator_code=str(row.get("IndicatorCode", code)),
                    area_code=str(row["SpatialDim"]),
                    year=int(row["TimeDim"]),
                    sex=str(row.get("Dim1") or ""),
                    age_group=row.get("Dim2") if row.get("Dim2Type") == "AGEGROUP" else None,
                    value_as_written=match.group(1),
                    display=display.strip(),
                )
            )
        return records


def make(settings: Settings) -> WhoGho:
    return WhoGho(settings.config.structured.providers["who_gho"].base_url)
