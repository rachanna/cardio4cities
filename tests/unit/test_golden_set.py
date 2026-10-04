"""The prompt golden set stays well formed (LLD-3 §9): every expectation names a field the
grader knows, and every checker case builds valid labels. No model is called."""

import re
from pathlib import Path

import yaml

from app.domain.vocab import VerdictLabel
from app.prompts.answerer.schema import AnswererOutput, AnswerSentence
from app.prompts.loader import load_prompt
from scripts import eval_answers
from scripts.eval_prompts import GOLDEN, _labels

GRADED = {
    "kind", "value", "match", "geography_level", "geography_name", "measure_type",
    "denominator_stated", "period_year", "period_none", "label_quote", "relation_type",
    "programme_status", "sample_size", "population_group", "representativeness", "setting",
    "subgroup", "case_definition_contains",
}  # fmt: skip


def _load(name: str) -> list[dict[str, object]]:
    data: list[dict[str, object]] = yaml.safe_load((GOLDEN / name).read_text(encoding="utf-8"))
    return data


def test_extractor_cases_use_known_fields_and_unique_ids() -> None:
    cases = _load("extractor.yaml")
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case.get("expect") or case.get("expect_none") or case.get("expect_min_claims"), case[
            "id"
        ]
        for expect in case.get("expect", []):  # type: ignore[attr-defined]
            assert set(expect) <= GRADED, case["id"]
            assert "value" in expect or "match" in expect, case["id"]


def test_checker_cases_build_labels_and_name_a_verdict() -> None:
    cases = _load("checker.yaml")
    assert len(cases) >= 20
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        _labels(case["labels"])  # type: ignore[arg-type]
        assert VerdictLabel(str(case["expected"]))
        for kind in case.get("label_passages") or {}:  # type: ignore[attr-defined]
            assert kind in ("period", "geography", "population"), case["id"]


def test_recorded_results_are_for_the_committed_prompts() -> None:
    """RV-019 (BD-26): a results file that names another prompt version than the one
    committed reports a measurement of text that is not in the repository. Re-run the
    golden set (paid, with the owner's approval) or move the file to results/archive/."""
    results = Path(__file__).resolve().parents[1] / "prompts" / "golden" / "results"
    for path in results.glob("*-latest.md"):
        text = path.read_text(encoding="utf-8")
        named = re.findall(r"^- prompt (\w+): (\S+)$", text, re.M)
        named += [
            (r.lower(), v) for r, v in re.findall(r"^## (\w+) \((\w+@v\d+\+\w+)\)$", text, re.M)
        ]
        assert named, f"{path.name} names no prompt version"
        for role, version in named:
            assert version == load_prompt(role).prompt_version, (path.name, role, version)


# --- classifier and answerer (BD-38) --------------------------------------------------------


def test_classifier_cases_name_known_types_and_slots() -> None:
    from scripts.reference.yaml_reference import read_slots

    slot_ids = {s.slot_id for s in read_slots()}
    types = {"figure", "relationship", "change_over_time", "open", "out_of_scope"}
    cases = eval_answers.load("classifier.yaml")
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert set(case["types"]) <= types, case["id"]
        assert set(case.get("slots") or []) <= slot_ids, case["id"]


def _ideal(case: dict[str, object], b: eval_answers.Bundle) -> AnswererOutput:
    """What a faultless answerer would write for the case."""
    sentences = []
    for ref, e in b.evidence.items():
        text = e.fact.claim.statement
        if case["expect"] == "wider_area":
            text = f"No city-level figure was found for Halden Bay; nationally: {text}"
        sentences.append(
            AnswerSentence(text=text, refs=[ref], kind="fact", slot_id=e.fact.claim.slot_id)
        )
    for m in b.mentions:
        if case["expect"] == "abstain_or_mention":
            sentences.append(
                AnswerSentence(
                    text="A news report says camps ran, but this is not confirmed.",
                    refs=[m.ref_id],
                    kind="mention",
                    slot_id=None,
                )
            )
    asked = list(case.get("asked") or [])  # type: ignore[call-overload]
    for slot in asked:
        if not any(s.slot_id == slot for s in sentences):
            sentences.append(
                AnswerSentence(text="Not found.", refs=[], kind="abstain", slot_id=slot)
            )
    return AnswererOutput(sentences=sentences)


def test_every_answerer_case_can_be_passed() -> None:
    """An ideal answer to every bundle passes the grader, through the real post-check."""
    from app.domain.params import BadgeParams, ConfidenceParams
    from scripts.reference.yaml_reference import read_slots

    slots = {s.slot_id: s for s in read_slots()}
    badge = BadgeParams(stale_years=5, stale_years_people=2, small_sample=300)
    for case in eval_answers.load("answerer.yaml"):
        b = eval_answers.bundle(case, slots, badge, ConfidenceParams(recent_years=5))
        checked = eval_answers.post_check(_ideal(case, b), b)
        assert eval_answers.answer_problems(case, checked) == [], case["id"]
        assert "<question>" in eval_answers.answerer_user(case, b)
