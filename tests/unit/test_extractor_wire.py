"""The extractor's flat wire shape (BD-45): Anthropic refused the nested schema ("compiled
grammar is too large"), so the provider fills one flat object per claim and code converts
it. These tests prove the conversion loses nothing, that code enforces what the grammar
used to, and that the wire schema stays small enough to compile."""

import json
from typing import Any

from app.domain.vocab import (
    ClaimKind,
    EntityType,
    GeographyLevel,
    MeasureType,
    Method,
    ProgrammeStatus,
    RelationType,
    Representativeness,
    Setting,
    Sex,
)
from app.prompts.extractor.schema import (
    ClaimOut,
    ExtractorOutput,
    ExtractorWire,
    LabelQuotesOut,
    LabelsOut,
    PeriodOut,
    PopulationOut,
    RelationOut,
    StatisticOut,
    to_output,
    wire_problems,
)


def labels(**changes: Any) -> LabelsOut:
    values: dict[str, Any] = {
        "geography_level": GeographyLevel.CITY_WIDE,
        "geography_name": "Halden Bay",
        "measure_type": MeasureType.MEASURED_PREVALENCE,
        "reference_period": PeriodOut(start="2022", end="2023-06"),
        "population": PopulationOut(
            age_min=25, age_max=64, sex=Sex.FEMALE, group="fishing crew", subgroup=True
        ),
        "setting": Setting.WORKPLACE,
        "sample_size_as_written": "n = 1,204",
        "case_definition": "140/90 mmHg or above",
        "method": Method.MEASURED,
        "representativeness": Representativeness.REPRESENTATIVE_SAMPLE,
        "denominator_text": "adults with hypertension",
        "denominator_stated": True,
    }
    values.update(changes)
    return LabelsOut(**values)


STATISTIC = ClaimOut(
    slot_id="S03", kind=ClaimKind.STATISTIC,
    statement="In Halden Bay in 2022, 33.1% of women aged 25-64 had raised blood pressure.",
    quote="33.1% of women aged 25-64 had raised blood pressure", quote_lang="no",
    quote_translation="33.1% of women aged 25-64 had raised blood pressure",
    labels=labels(),
    statistic=StatisticOut(indicator_code="HTN_PREV", value_as_written="33.1%"),
    relation=None,
    label_quotes=LabelQuotesOut(
        period="Field work ran from May 2022 to June 2023", geography=None,
        population="a random sample of adults aged 25-64",
    ),
)  # fmt: skip
RELATION = ClaimOut(
    slot_id="S07", kind=ClaimKind.RELATION,
    statement="The Saltmarsh Health Trust runs the Halden Bay Heart Network.",
    quote="The Halden Bay Heart Network is operated by the Saltmarsh Health Trust",
    quote_lang="en", quote_translation=None,
    labels=labels(
        measure_type=MeasureType.QUALITATIVE, reference_period=None,
        population=PopulationOut(age_min=None, age_max=None, sex=Sex.NOT_STATED, group=None),
        setting=None, sample_size_as_written=None, case_definition=None,
        method=Method.NOT_STATED, representativeness=Representativeness.NOT_APPLICABLE,
        denominator_text=None, denominator_stated=False,
    ),
    statistic=None,
    relation=RelationOut(
        subject_name="Saltmarsh Health Trust", subject_type=EntityType.ORGANIZATION,
        relation_type=RelationType.RUNS, object_name="Halden Bay Heart Network",
        object_type=EntityType.PROGRAMME, valid_from="2024-03", valid_to=None,
        programme_status=ProgrammeStatus.RUNNING,
    ),
    label_quotes=None,
)  # fmt: skip
STATEMENT = RELATION.model_copy(
    update={"kind": ClaimKind.STATEMENT, "relation": None, "slot_id": "S11",
            "statement": "Halden Bay has a salt reduction policy."}
)  # fmt: skip


def test_the_round_trip_loses_nothing() -> None:
    """Nested -> flat -> nested gives back exactly the same claims: every label, block and
    label quote, with not-stated values still not stated."""
    original = ExtractorOutput(claims=[STATISTIC, RELATION, STATEMENT])
    back, problems = to_output(ExtractorWire.from_output(original))
    assert problems == []
    assert back == original


def test_vocabulary_values_are_matched_forgivingly() -> None:
    wire = ExtractorWire.from_output(ExtractorOutput(claims=[STATISTIC]))
    claim = wire.claims[0].model_copy(
        update={"measure_type": "Measured prevalence", "geography_level": "CITY-WIDE",
                "setting": " workplace "}
    )  # fmt: skip
    out, problems = to_output(ExtractorWire(claims=[claim]))
    assert problems == []
    assert out.claims[0].labels.measure_type is MeasureType.MEASURED_PREVALENCE
    assert out.claims[0].labels.geography_level is GeographyLevel.CITY_WIDE


def test_a_value_outside_its_vocabulary_is_a_repair_problem_and_the_claim_waits() -> None:
    """What the grammar enforced, code enforces: the model is asked once to repair."""
    wire = ExtractorWire.from_output(ExtractorOutput(claims=[STATISTIC, RELATION]))
    bad = wire.claims[0].model_copy(update={"measure_type": "prevalence-ish"})
    out, problems = to_output(ExtractorWire(claims=[bad, wire.claims[1]]))
    assert [c.slot_id for c in out.claims] == ["S07"]
    assert len(problems) == 1
    assert problems[0].startswith("claim 1: measure_type 'prevalence-ish' is not one of:")


def test_the_kind_and_block_checks_still_apply() -> None:
    wire = ExtractorWire.from_output(ExtractorOutput(claims=[STATISTIC]))
    no_value = wire.claims[0].model_copy(update={"indicator_code": "", "value_as_written": ""})
    assert wire_problems(ExtractorWire(claims=[no_value])) == [
        "claim 1: kind statistic needs a statistic block, and only then"
    ]


def test_the_wire_schema_stays_small_enough_to_compile() -> None:
    """The regression guard: Anthropic refused the nested schema (17 nested types, 21
    optional unions, 10 enums). The wire schema has one object, no enums and three
    nullable numbers or flags; a change that brings the nesting back fails here."""
    schema = ExtractorWire.model_json_schema()
    text = json.dumps(schema)
    assert set(schema.get("$defs", {})) == {"ClaimWire"}
    assert '"enum"' not in text
    assert text.count('"anyOf"') <= 3


def test_blank_or_not_applicable_values_mean_what_the_enum_used_to_force() -> None:
    """Measured on the demo models (BD-45): for a relation or statement claim the model may
    leave measure_type blank or write not_applicable, where the enum forced qualitative;
    a blank sex, method or representativeness is the vocabulary's own not_stated."""
    wire = ExtractorWire.from_output(ExtractorOutput(claims=[RELATION, STATISTIC]))
    relation = wire.claims[0].model_copy(
        update={"measure_type": "not_applicable", "sex": "", "method": "", "representativeness": ""}
    )
    out, problems = to_output(ExtractorWire(claims=[relation]))
    assert problems == []
    labels = out.claims[0].labels
    assert labels.measure_type is MeasureType.QUALITATIVE
    assert labels.population.sex is Sex.NOT_STATED
    assert labels.method is Method.NOT_STATED
    assert labels.representativeness is Representativeness.NOT_STATED
    # a statistic must still name its measure
    blank = wire.claims[1].model_copy(update={"measure_type": ""})
    assert to_output(ExtractorWire(claims=[blank]))[1][0].startswith("claim 1: measure_type ''")


def test_a_prevalence_without_a_stated_method_is_its_own_value() -> None:
    """BD-48: before, a statistic had to say measured, self-reported or modelled even when
    the source did not; the model guessed and the checker rejected the claim."""
    unstated = STATISTIC.model_copy(
        update={
            "labels": labels(
                measure_type=MeasureType.PREVALENCE,
                method=Method.NOT_STATED,
                representativeness=Representativeness.NOT_STATED,
            )
        }
    )
    original = ExtractorOutput(claims=[unstated])
    back, problems = to_output(ExtractorWire.from_output(original))
    assert problems == []
    assert back == original
    assert back.claims[0].labels.measure_type is MeasureType.PREVALENCE
