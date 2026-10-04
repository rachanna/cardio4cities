"""The prompt golden set stays well formed (LLD-3 §9): every expectation names a field the
grader knows, and every checker case builds valid labels. No model is called."""

import re
from pathlib import Path

import yaml

from app.domain.vocab import VerdictLabel
from app.prompts.loader import load_prompt
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
