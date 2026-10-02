"""Domain types (LLD-1 §2). Pydantic v2; field names, types and validators are binding.

Started in D1-3 with the reference-data types; D2-1 adds the rest.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.vocab import AnswerKind, GeographyLevel, RelationType


class SlotDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slot_id: str = Field(pattern=r"^S(0[1-9]|1[0-6])$")  # 'S01'…'S16'
    dimension: str = Field(pattern=r"^D[1-6]$")  # 'D1'…'D6'
    question: str  # plain-language question shown in UI
    short_label: str  # used in abstentions: "No confirmed {short_label} for {city}" (BD-03)
    answer_kind: AnswerKind
    indicator_codes: list[str]  # for statistic slots; LLD-1 §3.3
    relation_types: list[RelationType]  # for relation slots; LLD-1 §6.2
    headline: bool  # True only for S04
    accepted_levels: list[GeographyLevel]  # levels that count as 'answered'

    @model_validator(mode="after")
    def _kind_matches_targets(self) -> "SlotDef":
        has_indicators, has_relations = bool(self.indicator_codes), bool(self.relation_types)
        expected = {
            AnswerKind.STATISTIC: (True, False),
            AnswerKind.RELATION: (False, True),
            AnswerKind.STATEMENT: (False, False),
            AnswerKind.MIXED: (False, True),
        }[self.answer_kind]
        if (has_indicators, has_relations) != expected:
            raise ValueError(
                f"{self.slot_id}: answer_kind {self.answer_kind} does not fit "
                f"indicator_codes={self.indicator_codes} relation_types={self.relation_types}"
            )
        if not self.accepted_levels:
            raise ValueError(f"{self.slot_id}: accepted_levels must not be empty")
        return self


class IndicatorDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str
    comparability_key: str  # which labels make two claims comparable (R-35)
    notes: str | None = None
