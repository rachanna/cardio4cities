from typing import Protocol

from pydantic import BaseModel, ConfigDict


class StructuredRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    value_as_written: str
    year: int | None
    sex: str | None
    age_band: str | None
    area_name: str | None
    area_level: str | None
    raw: bytes  # returned unchanged so code verification can re-read it


class StructuredDataPort(Protocol):
    provider: str

    async def indicator(
        self, code: str, country_iso3: str, admin1_name: str | None = None
    ) -> list[StructuredRecord]: ...
