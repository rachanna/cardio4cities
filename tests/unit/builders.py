"""Builders for rule tests. Fictional places only: Halden Bay, Norvania (CLAUDE.md).

Parameters are built from the shipped config, so tests exercise the real tunables.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import yaml

from app.domain.models import Claim, Labels, Relation, SlotDef, Statistic
from app.domain.params import (
    BadgeParams,
    ConfidenceParams,
    ConsistencyParams,
    QuoteParams,
    ReplanParams,
    VerifyParams,
)
from app.domain.vocab import (
    AnswerKind,
    ClaimKind,
    ClaimStatus,
    GeographyLevel,
    MeasureType,
    PeriodType,
    RelationType,
    Representativeness,
    Sex,
)
from app.settings import CONFIG_DIR

TODAY = date(2026, 10, 3)
CITY = GeographyLevel.CITY_WIDE
CITY_SLOT = (GeographyLevel.CITY_WIDE,)


def config(profile: str = "local") -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((CONFIG_DIR / f"{profile}.yaml").read_text("utf-8"))
    return raw


def quote_params() -> QuoteParams:
    return QuoteParams(**config()["quote"])


def consistency_params() -> ConsistencyParams:
    c = config()["consistency"]
    return ConsistencyParams(Decimal(str(c["agree_pp"])), Decimal(str(c["agree_rel"])))


def badge_params() -> BadgeParams:
    return BadgeParams(**config()["badge"])


def confidence_params() -> ConfidenceParams:
    return ConfidenceParams(**config()["confidence"])


def replan_params() -> ReplanParams:
    return ReplanParams(**config()["replan"])


def verify_params(profile: str = "deployed") -> VerifyParams:
    return VerifyParams(**config(profile)["verify"])


def labels(**overrides: Any) -> Labels:
    values: dict[str, Any] = {
        "geography_level": CITY,
        "geography_name": "Halden Bay",
        "measure_type": MeasureType.MEASURED_PREVALENCE,
        "reference_start": date(2024, 1, 1),
        "reference_end": date(2024, 12, 31),
        "reference_precision": "year",
        "period_type": PeriodType.PERIOD,
        "population_age_min": 30,
        "population_age_max": 79,
        "population_sex": Sex.ALL,
        "population_group": "adults",
        "setting": "community",
        "sample_size": 2400,
        "case_definition": "SBP>=140 and/or DBP>=90, or on medication",
        "threshold_code": "bp_140_90",
        "representativeness": Representativeness.REPRESENTATIVE_SAMPLE,
        "denominator_text": "adults aged 30-79",
        "denominator_stated": True,
    }
    values.update(overrides)
    return Labels(**values)


def claim(claim_id: str = "clm_a", **overrides: Any) -> Claim:
    label_overrides = overrides.pop("labels", {})
    values: dict[str, Any] = {
        "claim_id": claim_id,
        "run_id": "run_1",
        "city_id": "city_hb",
        "slot_id": "S03",
        "source_id": "src_1",
        "kind": ClaimKind.STATISTIC,
        "statement": "In Halden Bay, 31.2% of adults aged 30-79 had hypertension in 2024.",
        "quote": "Hypertension affected 31.2% of adults aged 30-79 in Halden Bay in 2024.",
        "quote_lang": "en",
        "quote_translation": None,
        "span_start": 0,
        "span_end": 72,
        "labels": labels(**label_overrides),
        "status": ClaimStatus.SUPPORTED,
        "extractor_model": "test-model",
        "prompt_version": "extractor@v1+00000000",
    }
    values.update(overrides)
    return Claim(**values)


def statistic(claim_id: str = "clm_a", value: str = "31.2", **overrides: Any) -> Statistic:
    values: dict[str, Any] = {
        "claim_id": claim_id,
        "indicator_code": "HTN_PREV",
        "value_as_written": f"{value}%",
        "value_num": Decimal(value),
        "unit": "percent",
    }
    values.update(overrides)
    return Statistic(**values)


def relation(
    claim_id: str,
    subject: str,
    obj: str = "ent_halden_bay",
    relation_type: RelationType = RelationType.GOVERNS,
    valid_from: date | None = None,
    valid_to: date | None = None,
    proxy: bool = False,
) -> Relation:
    return Relation(
        claim_id=claim_id,
        subject_entity_id=subject,
        relation_type=relation_type,
        object_entity_id=obj,
        valid_from=valid_from,
        valid_to=valid_to,
        valid_from_is_proxy=proxy,
    )


def slot(slot_id: str = "S03", **overrides: Any) -> SlotDef:
    values: dict[str, Any] = {
        "slot_id": slot_id,
        "dimension": "D2",
        "question": "What share of adults has hypertension?",
        "short_label": "hypertension prevalence",
        "answer_kind": AnswerKind.STATISTIC,
        "indicator_codes": ["HTN_PREV"],
        "relation_types": [],
        "headline": False,
        "accepted_levels": [GeographyLevel.CITY_WIDE],
    }
    values.update(overrides)
    return SlotDef(**values)
