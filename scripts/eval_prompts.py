"""Prompt golden set against real models (LLD-3 §9). Costs money: ask the owner first.

Runs the extractor on every snippet in `tests/prompts/golden/extractor.yaml` and the
checker on every pair in `tests/prompts/golden/checker.yaml`, with the model bindings of
the active profile (APP_ENV) and the same role calls the workflow uses: budget reserved
first, one repair, the labelled checker fallback. Spend stops at `--max-usd`.

Pass bar: checker agreement with the expected verdicts of at least
`eval.checker_agreement_min`; recall (expected claims found) of at least
`eval.recall_min` (owner, BD-26); no trap claim that the extractor mislabelled and the
checker then supported; and a planner plan that passes the structural check. Writes
`tests/prompts/golden/results/<profile>-latest.md` (`<profile>-<role>-latest.md` for a
run of one role), whose header names each prompt
version measured; a unit test fails when that is not the committed version (RV-019).

Classifier and answerer (BD-38): each classifier case passes when its classification
holds what the case expects; each answerer bundle passes when what survives the real
post-check is what the case expects (`scripts/eval_answers.py`). Pass bars:
`eval.classifier_min` and `eval.answerer_min`.

    uv run poe eval [--max-usd 1.0] [--only extractor|checker|planner|classifier|answerer]
"""

import argparse
import asyncio
import importlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml
from dotenv import load_dotenv

from app.api.asking import roles_for
from app.container import ADAPTERS
from app.domain.models import CityIdentity, Labels
from app.domain.params import BadgeParams, ConfidenceParams, QuoteParams
from app.domain.vocab import ClaimKind, PeriodType, VerdictLabel
from app.ports.errors import PortError
from app.ports.llm import LLMPort
from app.prompts.answerer.schema import AnswererOutput
from app.prompts.checker import context as checker_context
from app.prompts.checker.schema import CheckerOutput, final_label
from app.prompts.classifier.schema import ClassifierOutput
from app.prompts.extractor import context as extractor_context
from app.prompts.extractor.schema import (
    ClaimOut,
    ExtractorWire,
    keep_claim,
    to_labels,
    to_output,
    wire_problems,
)
from app.prompts.loader import load_prompt
from app.prompts.planner import context as planner_context
from app.prompts.planner.schema import PlannerOutput, validate
from app.query.llm import call as query_call
from app.query.types import AskDeps, ModelRole
from app.settings import Settings, load_settings
from app.workflow.budget import BudgetExhaustedError, BudgetLedger, BudgetLimits
from app.workflow.deps import RoleBinding, RunDeps
from app.workflow.llm import call_checker, call_role
from app.workflow.rules.label_evidence import locate_label_quotes
from app.workflow.rules.numbers import read_sample_size
from app.workflow.rules.quotes import QuoteDrop, match_quote, normalise_text
from app.workflow.rules.selection import government_sites, publisher_table
from app.workflow.runner import role_bindings
from scripts import eval_answers
from scripts.reference.yaml_reference import read_indicators, read_slots

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "prompts" / "golden"
REFERENCE = Path(__file__).resolve().parents[1] / "reference"
SOURCE_ID = "src_golden"
CITY = CityIdentity(
    city_id="city_golden", gazetteer_id="9000001", name="Halden Bay", ascii_name="Halden Bay",
    country_iso2="XN", country_iso3="XNV", country_name="Norvania", admin1_code="01",
    admin1_name="West Coast", admin2_name=None, population=420000, lat=60.1, lon=5.2,
    languages=["nv", "en"],
)  # fmt: skip


@dataclass
class EvalDeps:
    """The parts of RunDeps that model calls use."""

    ledger: BudgetLedger
    llm: dict[str, LLMPort]
    roles: dict[str, RoleBinding]


@dataclass
class Tally:
    lines: list[str] = field(default_factory=list)
    fields_ok: int = 0
    fields_all: int = 0
    found: int = 0
    expected: int = 0
    quotes_ok: int = 0
    quotes_all: int = 0
    traps_accepted: list[str] = field(default_factory=list)
    checker_ok: int = 0
    checker_all: int = 0
    failures: int = 0
    planner_problems: list[str] = field(default_factory=list)
    classifier_ok: int = 0
    classifier_all: int = 0
    answerer_ok: int = 0
    answerer_all: int = 0
    survival: list[float] = field(default_factory=list)  # post-check first-pass survival
    versions: dict[str, str] = field(default_factory=dict)  # role -> prompt version measured


def llm_adapters(settings: Settings) -> dict[str, LLMPort]:
    providers = {
        ref.provider for _, role in settings.config.llm.roles.items() for ref in role.model_refs()
    }
    adapters: dict[str, LLMPort] = {}
    for provider in sorted(providers):
        module, _, attr = ADAPTERS["llm"][provider].partition(":")
        adapters[provider] = getattr(importlib.import_module(module), attr)(settings)
    return adapters


def _year_of(out: ClaimOut) -> set[int]:
    period = out.labels.reference_period
    years = set()
    for value in (period.start, period.end) if period else ():
        if value and value[:4].isdigit():
            years.add(int(value[:4]))
    return years


def _field(out: ClaimOut, name: str, want: Any, text: str, quote: QuoteParams) -> bool:
    lab = out.labels
    rel = out.relation
    checks: dict[str, Any] = {
        "kind": lambda: out.kind.value == want,
        "geography_level": lambda: lab.geography_level.value == want,
        "geography_name": lambda: str(want).casefold() in lab.geography_name.casefold(),
        "measure_type": lambda: lab.measure_type.value == want,
        "denominator_stated": lambda: lab.denominator_stated is want,
        "period_year": lambda: want in _year_of(out),
        "period_none": lambda: not _year_of(out),
        "sample_size": lambda: read_sample_size(lab.sample_size_as_written) == want,
        "representativeness": lambda: lab.representativeness.value == want,
        "setting": lambda: (lab.setting.value if lab.setting else None) == want,
        "subgroup": lambda: lab.population.subgroup is want,
        "case_definition_contains": lambda: str(want) in (lab.case_definition or ""),
        "population_group": lambda: str(want).casefold() in (lab.population.group or "").casefold(),
        "relation_type": lambda: rel is not None and rel.relation_type.value == want,
        "programme_status": lambda: (
            rel is not None
            and rel.programme_status is not None
            and rel.programme_status.value == want
        ),
        "label_quote": lambda: _label_quote_located(out, want, text, quote),
    }
    return bool(checks[name]())


def _label_quote_located(out: ClaimOut, kind: str, text: str, quote: QuoteParams) -> bool:
    quotes = out.label_quotes.model_dump() if out.label_quotes else {}
    labels, _ = to_labels(out.labels, None)
    evidence = locate_label_quotes({kind: quotes.get(kind)}, text, 0, labels, quote)  # type: ignore[dict-item]
    return kind in evidence.spans


def _find(claims: list[ClaimOut], expect: dict[str, Any]) -> ClaimOut | None:
    """`value`: the value as written, or a list of the forms the source writes it in
    ("86 per 100,000" and "86 per 100,000 people" both copy the text exactly)."""
    wanted = expect.get("value")
    forms = {normalise_text(v) for v in (wanted if isinstance(wanted, list) else [wanted]) if v}
    for c in claims:
        value = c.statistic.value_as_written if c.statistic else None
        if forms and value and normalise_text(value) in forms:
            return c
        if "match" in expect and expect["match"].casefold() in c.statement.casefold():
            return c
        if "match" in expect and c.relation is not None:
            names = f"{c.relation.subject_name} {c.relation.object_name}".casefold()
            if expect["match"].casefold() in names:
                return c
    return None


async def check_claim(d: RunDeps, out: ClaimOut, text: str, span: tuple[int, int]) -> VerdictLabel:
    labels, _ = to_labels(out.labels, None)
    if labels.reference_end is None:
        labels = labels.model_copy(update={"period_type": PeriodType.PUBLICATION_DATE_PROXY})
    user = checker_context.build_user_message(
        out.statement, out.statistic.value_as_written if out.statistic else None, labels,
        SOURCE_ID, "government", None, checker_context.passage(text, *span),
    )  # fmt: skip
    result = await call_checker(d, load_prompt("checker").system, user, CheckerOutput)
    return final_label(result.parsed)


async def run_extractor(d: RunDeps, quote: QuoteParams, tally: Tally) -> None:
    slots = {s.slot_id: s for s in read_slots()}
    indicators = read_indicators()
    prompt = load_prompt("extractor")
    tally.versions["extractor"] = prompt.prompt_version
    tally.lines += ["", f"## Extractor ({prompt.prompt_version})", ""]
    for case in yaml.safe_load((GOLDEN / "extractor.yaml").read_text(encoding="utf-8")):
        chosen = [slots[s] for s in case.get("slots", ["S04"])]
        wanted = [i for i in indicators if any(i.code in s.indicator_codes for s in chosen)]
        text = case["text"]
        user = extractor_context.build_user_message(
            CITY, chosen, wanted, SOURCE_ID, None, "government", None,
            f"https://golden.halden-bay.test/{case['id']}", text, 1, 1,
        )  # fmt: skip
        try:
            out = await call_role(
                d, "extractor", prompt.system, user, ExtractorWire, problems=wire_problems
            )
        except PortError as exc:
            tally.failures += 1
            tally.lines.append(
                f"- {case['id']}: model call failed ({type(exc).__name__}: {str(exc)[:160]})"
            )
            continue
        nested = to_output(out.parsed)[0]  # flat wire to nested (BD-45)
        claims = [c for c in nested.claims if keep_claim(c, set(case.get("slots", ["S04"])))]
        notes: list[str] = []
        for c in claims:
            value = c.statistic.value_as_written if c.statistic else None
            tally.quotes_all += 1
            if not isinstance(match_quote(c.quote, text, quote, value), QuoteDrop):
                tally.quotes_ok += 1
            for bad in case.get("forbid_values", []):
                if value and bad in value:
                    notes.append(f"forbidden value {bad} extracted")
                    tally.traps_accepted.append(f"{case['id']}: extracted {bad}")
        for place in case.get("forbid_geography", []):  # the context city is not evidence
            if any(place.casefold() in c.labels.geography_name.casefold() for c in claims):
                notes.append(f"forbidden area {place} labelled")
                tally.traps_accepted.append(f"{case['id']}: labelled {place}")
        if (least := case.get("expect_min_claims")) is not None:
            tally.expected += 1
            ok = len(claims) >= least
            tally.found += ok
            notes.append(f"{len(claims)} claims" + ("" if ok else f", expected at least {least}"))
        if case.get("expect_none"):
            tally.expected += 1
            ok = not any(c.kind is ClaimKind.STATISTIC for c in claims)
            tally.found += ok
            notes.append("no claims, as expected" if ok else f"{len(claims)} claims, expected none")
        for expect in case.get("expect", []):
            tally.expected += 1
            found = _find(claims, expect)
            if found is None:
                got = [
                    c.statistic.value_as_written if c.statistic else c.kind.value for c in claims
                ]
                notes.append(f"missing {expect.get('value') or expect.get('match')} (got {got})")
                continue
            tally.found += 1
            wrong = []
            for name, want in expect.items():
                if name in ("value", "match"):
                    continue
                tally.fields_all += 1
                if _field(found, name, want, text, quote):
                    tally.fields_ok += 1
                else:
                    wrong.append(name)
            if wrong:
                notes.append(
                    f"{expect.get('value') or expect.get('match')}: wrong {', '.join(wrong)}"
                )
            located = match_quote(
                found.quote, text, quote,
                found.statistic.value_as_written if found.statistic else None,
            )  # fmt: skip
            if case.get("trap") and wrong and not isinstance(located, QuoteDrop):
                verdict = await check_claim(d, found, text, (located.span_start, located.span_end))
                notes.append(f"trap mislabelled; checker said {verdict.value}")
                if verdict is VerdictLabel.SUPPORTED:
                    tally.traps_accepted.append(f"{case['id']}: {', '.join(wrong)}")
        tally.lines.append(f"- {case['id']}: {'; '.join(notes) or 'all expected fields correct'}")


def _labels(raw: dict[str, Any]) -> Labels:
    year = raw.get("period")
    return Labels(
        geography_level=raw["geography_level"], geography_name=raw["geography_name"],
        measure_type=raw["measure_type"],
        reference_start=date(int(year), 1, 1) if year else None,
        reference_end=date(int(year), 12, 31) if year else None,
        reference_precision="year" if year else None,
        period_type=PeriodType.PERIOD if year else PeriodType.PUBLICATION_DATE_PROXY,
        population_age_min=raw.get("age_min"), population_age_max=raw.get("age_max"),
        population_group=raw.get("group"), representativeness="not_applicable",
        case_definition=raw.get("case_definition"), sample_size=raw.get("sample_size"),
        denominator_text=raw.get("denominator"), denominator_stated=bool(raw.get("denominator")),
    )  # fmt: skip


async def run_checker(d: RunDeps, tally: Tally) -> None:
    prompt = load_prompt("checker")
    tally.versions["checker"] = prompt.prompt_version
    tally.lines += ["", f"## Checker ({prompt.prompt_version})", ""]
    for case in yaml.safe_load((GOLDEN / "checker.yaml").read_text(encoding="utf-8")):
        user = checker_context.build_user_message(
            case["statement"], case.get("value"), _labels(case["labels"]), SOURCE_ID,
            "government", None, case["passage"].strip(),
            [(k, v.strip()) for k, v in (case.get("label_passages") or {}).items()],
        )  # fmt: skip
        try:
            out = await call_checker(d, prompt.system, user, CheckerOutput)
        except PortError as exc:
            tally.failures += 1
            tally.lines.append(
                f"- {case['id']}: model call failed ({type(exc).__name__}: {str(exc)[:160]})"
            )
            continue
        got = final_label(out.parsed)
        tally.checker_all += 1
        ok = got.value == case["expected"]
        tally.checker_ok += ok
        mark = "ok" if ok else f"MISMATCH (expected {case['expected']})"
        fallback = " via fallback" if out.fallback_used else ""
        tally.lines.append(
            f"- {case['id']}: {got.value}{fallback} {mark}; model said {out.parsed.label.value}, "
            f"issues {[i.value for i in out.parsed.issues]}"
        )


YEAR = re.compile(r"(19|20)\d{2}")


async def run_planner(d: RunDeps, settings: Settings, tally: Tally) -> None:
    """One live planner call for the fictional city, checked for structure (BD-26): every
    slot gets exactly `plan.queries_per_slot` queries, all in English (BD-31), `site:`
    only from the list given, and no numbers but years and those the context gave it."""
    prompt = load_prompt("planner")
    tally.versions["planner"] = prompt.prompt_version
    tally.lines += ["", f"## Planner ({prompt.prompt_version})", ""]
    slots = read_slots()
    indicators = {i.code: i for i in read_indicators()}
    table = publisher_table(yaml.safe_load((REFERENCE / "publishers.yaml").read_text("utf-8")))
    sites = government_sites(table, CITY.country_iso2)
    per_slot = settings.config.plan.queries_per_slot
    user = planner_context.build_user_message(CITY, slots, indicators, 0, [], sites, per_slot)
    slot_ids = {s.slot_id for s in slots}
    try:
        out = await call_role(
            d, "planner", prompt.system, user, PlannerOutput,
            problems=lambda o: validate(o, slot_ids, set(), set(sites), per_slot),
        )  # fmt: skip
    except PortError as exc:
        tally.failures += 1
        tally.planner_problems.append(f"model call failed ({type(exc).__name__})")
        tally.lines.append(f"- model call failed ({type(exc).__name__}: {str(exc)[:160]})")
        return
    given = set(re.findall(r"\d+", user))
    for slot in out.parsed.slots:
        problems = []
        if any(q.lang != "en" for q in slot.queries):  # English only (BD-31)
            problems.append("a query not in English")
        for q in slot.queries:
            numbers = re.findall(r"\d+", q.text)
            # A year, or a number the context gave it (an indicator's age band such as
            # "30-70"), is fine; any other number may be a figure the planner made up
            if any(not YEAR.fullmatch(n) and n not in given for n in numbers):
                problems.append(f"a number that is not a year in {q.text!r}")
        tally.planner_problems += [f"{slot.slot_id}: {p}" for p in problems]
        tally.lines.append(f"- {slot.slot_id}: {'; '.join(problems) or 'ok'}")


@dataclass
class QaDeps:
    """The parts of AskDeps that `app/query/llm.call` uses."""

    ledger: BudgetLedger
    llm: dict[str, LLMPort]
    roles: dict[str, ModelRole]


async def run_classifier(q: AskDeps, tally: Tally) -> None:
    prompt = load_prompt("classifier")
    tally.versions["classifier"] = prompt.prompt_version
    tally.lines += ["", f"## Classifier ({prompt.prompt_version})", ""]
    slots, indicators = read_slots(), read_indicators()
    slot_ids, codes = [s.slot_id for s in slots], [i.code for i in indicators]
    for case in eval_answers.load("classifier.yaml"):
        user = eval_answers.classifier_user(case, slots, indicators)
        try:
            out, _ = await query_call(q, "classifier", prompt.system, user, ClassifierOutput)
        except PortError as exc:
            tally.failures += 1
            tally.lines.append(f"- {case['id']}: model call failed ({type(exc).__name__})")
            continue
        problems = eval_answers.classifier_problems(case, out, slot_ids, codes)
        tally.classifier_all += 1
        tally.classifier_ok += not problems
        tally.lines.append(f"- {case['id']}: {'; '.join(problems) or 'ok'}")


async def run_answerer(q: AskDeps, settings: Settings, tally: Tally) -> None:
    prompt = load_prompt("answerer")
    tally.versions["answerer"] = prompt.prompt_version
    tally.lines += ["", f"## Answerer ({prompt.prompt_version})", ""]
    slots = {s.slot_id: s for s in read_slots()}
    badge = BadgeParams(**settings.config.badge.model_dump())
    confidence = ConfidenceParams(**settings.config.confidence.model_dump())
    for case in eval_answers.load("answerer.yaml"):
        b = eval_answers.bundle(case, slots, badge, confidence)
        user = eval_answers.answerer_user(case, b)
        try:
            out, _ = await query_call(q, "answerer", prompt.system, user, AnswererOutput)
        except PortError as exc:
            tally.failures += 1
            tally.lines.append(f"- {case['id']}: model call failed ({type(exc).__name__})")
            continue
        checked = eval_answers.post_check(out, b)
        problems = eval_answers.answer_problems(case, checked)
        tally.answerer_all += 1
        tally.answerer_ok += not problems
        tally.survival.append(checked.first_pass_survival)
        actions = f"; post-check removed {len(checked.removed)}, repaired {len(checked.repaired)}"
        tally.lines.append(f"- {case['id']}: {'; '.join(problems) or 'ok'}{actions}")


async def main(max_usd: float, only: str | None) -> int:
    load_dotenv(".env", override=False)
    settings = load_settings()
    ledger = BudgetLedger(BudgetLimits(
        wall_clock_s=3600, searches=1, fetches=1, tokens=0,
        cost_micro_usd=int(max_usd * 1e6), wind_down_at=1.0,
    ))  # fmt: skip
    d = cast(RunDeps, EvalDeps(ledger, llm_adapters(settings), role_bindings(settings)))
    quote = QuoteParams(**settings.config.quote.model_dump())
    q = cast(AskDeps, QaDeps(ledger, llm_adapters(settings), roles_for(settings)))
    tally = Tally()
    try:
        if only in (None, "extractor"):
            await run_extractor(d, quote, tally)
        if only in (None, "checker"):
            await run_checker(d, tally)
        if only in (None, "planner"):
            await run_planner(d, settings, tally)
        if only in (None, "classifier"):
            await run_classifier(q, tally)
        if only in (None, "answerer"):
            await run_answerer(q, settings, tally)
    except BudgetExhaustedError:
        tally.lines.append(f"\nStopped: spend reached ${max_usd:.2f}.")
    agreement = tally.checker_ok / tally.checker_all if tally.checker_all else 0.0
    bar = settings.config.eval.checker_agreement_min
    recall = tally.found / tally.expected if tally.expected else 0.0
    recall_bar = settings.config.eval.recall_min
    classified = tally.classifier_ok / tally.classifier_all if tally.classifier_all else 0.0
    answered = tally.answerer_ok / tally.answerer_all if tally.answerer_all else 0.0
    survival = sum(tally.survival) / len(tally.survival) if tally.survival else 0.0
    eval_cfg = settings.config.eval
    passed = (
        (only not in (None, "checker") or agreement >= bar)
        and (only not in (None, "extractor") or recall >= recall_bar)
        and (only not in (None, "classifier") or classified >= eval_cfg.classifier_min)
        and (only not in (None, "answerer") or answered >= eval_cfg.answerer_min)
        and not tally.traps_accepted
        and not tally.planner_problems
    )
    roles = settings.config.llm.roles
    summary = [
        f"# Prompt golden set: {settings.env} profile",
        "",
        f"- extractor {roles.extractor.model}; checker {roles.checker.model}"
        f" ({roles.checker.effort or roles.checker.temperature})",
        *[f"- prompt {role}: {version}" for role, version in tally.versions.items()],
        f"- expected claims found: {tally.found}/{tally.expected} ({recall:.0%};"
        f" bar {recall_bar:.0%})",
        f"- expected fields correct: {tally.fields_ok}/{tally.fields_all}",
        f"- quotes located exactly: {tally.quotes_ok}/{tally.quotes_all}",
        f"- checker agreement: {tally.checker_ok}/{tally.checker_all} ({agreement:.0%};"
        f" bar {bar:.0%})",
        f"- trap claims mislabelled and then supported: {len(tally.traps_accepted)}"
        + (f" ({'; '.join(tally.traps_accepted)})" if tally.traps_accepted else ""),
        f"- planner problems: {len(tally.planner_problems)}",
        f"- classifier cases passed: {tally.classifier_ok}/{tally.classifier_all}"
        f" ({classified:.0%}; bar {eval_cfg.classifier_min:.0%})",
        f"- answerer cases passed: {tally.answerer_ok}/{tally.answerer_all} ({answered:.0%};"
        f" bar {eval_cfg.answerer_min:.0%}); first-pass survival {survival:.0%}"
        " (monitored: below 80% means revisit the prompt, LLD-5 §12.3)",
        f"- failed model calls: {tally.failures}",
        f"- cost: ${ledger.cost_micro_usd / 1e6:.4f} in {ledger.model_calls} calls",
        f"- **{'PASS' if passed else 'FAIL'}**",
    ]
    report = "\n".join(summary + tally.lines) + "\n"
    results = GOLDEN / "results"
    results.mkdir(exist_ok=True)
    # A run of one role writes its own file, so it never replaces the full run's record
    name = f"{settings.env}-latest.md" if only is None else f"{settings.env}-{only}-latest.md"
    (results / name).write_text(report, encoding="utf-8")
    print(report)
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument(
        "--only", choices=["extractor", "checker", "planner", "classifier", "answerer"]
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(asyncio.run(main(args.max_usd, args.only)))
