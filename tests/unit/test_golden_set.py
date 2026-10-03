"""The prompt golden set stays well formed (LLD-3 §9): every expectation names a field the
grader knows, and every checker case builds valid labels. No model is called."""

import yaml

from app.domain.vocab import VerdictLabel
from scripts.eval_prompts import GOLDEN, _labels

GRADED = {
    "kind", "value", "match", "geography_level", "geography_name", "measure_type",
    "denominator_stated", "period_year", "period_none", "label_quote", "relation_type",
    "programme_status", "sample_size", "population_group", "representativeness", "setting",
    "subgroup",
}  # fmt: skip


def _load(name: str) -> list[dict[str, object]]:
    data: list[dict[str, object]] = yaml.safe_load((GOLDEN / name).read_text(encoding="utf-8"))
    return data


def test_extractor_cases_use_known_fields_and_unique_ids() -> None:
    cases = _load("extractor.yaml")
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case.get("expect") or case.get("expect_none"), case["id"]
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
