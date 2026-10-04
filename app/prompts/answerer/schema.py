"""Answerer output (LLD-3 §7.3; answerer@v2, CHG-01)."""

from typing import Literal

from pydantic import BaseModel, Field

SentenceKind = Literal["fact", "mention", "analysis", "abstain"]


class AnswerSentence(BaseModel):
    text: str = Field(max_length=400)
    refs: list[str]
    kind: SentenceKind
    slot_id: str | None  # required when kind = 'abstain'


class AnswererOutput(BaseModel):
    sentences: list[AnswerSentence] = Field(max_length=8)
