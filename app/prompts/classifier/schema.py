"""Classifier output (LLD-3 §6.3, LLD-5 §3.1; classifier@v2, CHG-01)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.vocab import EntityType

QuestionType = Literal["figure", "relationship", "change_over_time", "open", "out_of_scope"]


class EntityMention(BaseModel):
    text: str = Field(max_length=200)
    type: EntityType | None


class ClassifierOutput(BaseModel):
    question_type: QuestionType
    slot_ids: list[str]
    indicator_codes: list[str]
    entity_mentions: list[EntityMention]
    as_of: str | None  # only if the user gave a date
    sub_questions: list[str] = Field(default_factory=list, max_length=3)
    refers_to_previous: bool
