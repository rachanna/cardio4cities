"""Checker output (LLD-3 §5.3) and code validation (§5.4)."""

from enum import StrEnum

from pydantic import BaseModel

from app.domain.vocab import VerdictLabel

MAX_RATIONALE_CHARS = 400


class CheckIssue(StrEnum):
    VALUE_MISMATCH = "value_mismatch"
    GEOGRAPHY_MISMATCH = "geography_mismatch"
    POPULATION_MISMATCH = "population_mismatch"
    PERIOD_MISMATCH = "period_mismatch"
    MEASURE_MISMATCH = "measure_mismatch"
    NOT_STATED = "not_stated"
    CONTRADICTED = "contradicted"


class CheckerOutput(BaseModel):
    # Order matters (v4, BD-26): structured output is written field by field, and at low
    # effort the checker spends almost no tokens reasoning (S-6: about 0 to 10 a call), so
    # the evidence and the issues come before the verdict (code review RV-016).
    rationale: str
    scope_verified: bool  # area and population confirmed by the passages
    period_verified: bool  # the period confirmed by the passages
    issues: list[CheckIssue]
    label: VerdictLabel


def final_label(output: CheckerOutput) -> VerdictLabel:
    """`supported` with any issue is treated as `insufficient`: an inconsistent verdict
    never creates a fact (PD-03)."""
    if output.label is VerdictLabel.SUPPORTED and output.issues:
        return VerdictLabel.INSUFFICIENT
    return output.label


def rationale(output: CheckerOutput) -> str:
    return output.rationale.strip()[:MAX_RATIONALE_CHARS]
