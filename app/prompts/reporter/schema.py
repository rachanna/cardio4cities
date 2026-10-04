"""Report writer output (LLD-3 §8.4; reporter@v1)."""

from typing import Literal

from pydantic import BaseModel, Field


class ReportSentence(BaseModel):
    text: str = Field(max_length=400)
    refs: list[str]
    kind: Literal["fact", "analysis", "gap"]


class DimensionIntro(BaseModel):
    sentences: list[ReportSentence] = Field(max_length=6)


class AnalysisPoint(BaseModel):
    text: str = Field(max_length=300)
    derived_from: list[str] = Field(min_length=1)
    kind: Literal["opportunity", "risk", "gap"]


class AnalysisOutput(BaseModel):
    points: list[AnalysisPoint] = Field(max_length=5)
