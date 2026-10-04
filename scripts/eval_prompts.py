"""Prompt golden set against real models (LLD-3 §9). Costs money: ask the owner first.

Runs the extractor on every snippet in `tests/prompts/golden/extractor.yaml` and the
checker on every pair in `tests/prompts/golden/checker.yaml`, with the model bindings of
the active profile (APP_ENV) and the same role calls the workflow uses: budget reserved
first, one repair, the labelled checker fallback. Spend stops at `--max-usd`.

Pass bar: checker agreement with the expected verdicts of at least
`eval.checker_agreement_min`, and no trap claim that the extractor mislabelled and the
checker then supported. Writes `tests/prompts/golden/results/<profile>-latest.md`.

    uv run poe eval [--max-usd 1.0] [--only extractor|checker]
"""

import argparse
import asyncio
import importlib
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml
from dotenv import load_dotenv

from app.container import ADAPTERS
from app.domain.models import CityIdentity, Labels
from app.domain.params import QuoteParams
from app.domain.vocab import ClaimKind, PeriodType, VerdictLabel
from app.ports.errors import PortError
from app.ports.llm import LLMPort
from app.prompts.checker import context as checker_context
from app.prompts.checker.schema import CheckerOutput, final_label
from app.prompts.extractor import context as extractor_context
from app.prompts.extractor.schema import (
    ClaimOut,
    ExtractorOutput,
    keep_claim,
    repair_problems,
    to_labels,
)
from app.prompts.loader import load_prompt
from app.settings import Settings, load_settings
from app.workflow.budget import BudgetExhaustedError, BudgetLedger, BudgetLimits
from app.workflow.deps import RoleBinding, RunDeps
from app.workflow.llm import call_checker, call_role
from app.workflow.rules.label_evidence import locate_label_quotes
from app.workflow.rules.numbers import read_sample_size
from app.workflow.rules.quotes import QuoteDrop, match_quote, normalise_text
from app.workflow.runner import role_bindings
from scripts.reference.yaml_reference import read_indicators, read_slots

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "prompts" / "golden"
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
    for c in claims:
        value = c.statistic.value_as_written if c.statistic else None
        if "value" in expect and value and normalise_text(value) == normalise_text(expect["value"]):
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
                d, "extractor", prompt.system, user, ExtractorOutput, problems=repair_problems
            )
        except PortError as exc:
            tally.failures += 1
            tally.lines.append(
                f"- {case['id']}: model call failed ({type(exc).__name__}: {str(exc)[:160]})"
            )
            continue
        claims = [c for c in out.parsed.claims if keep_claim(c, set(case.get("slots", ["S04"])))]
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


async def main(max_usd: float, only: str | None) -> int:
    load_dotenv(".env", override=False)
    settings = load_settings()
    ledger = BudgetLedger(BudgetLimits(
        wall_clock_s=3600, searches=1, fetches=1, tokens=0,
        cost_micro_usd=int(max_usd * 1e6), wind_down_at=1.0,
    ))  # fmt: skip
    d = cast(RunDeps, EvalDeps(ledger, llm_adapters(settings), role_bindings(settings)))
    quote = QuoteParams(**settings.config.quote.model_dump())
    tally = Tally()
    try:
        if only in (None, "extractor"):
            await run_extractor(d, quote, tally)
        if only in (None, "checker"):
            await run_checker(d, tally)
    except BudgetExhaustedError:
        tally.lines.append(f"\nStopped: spend reached ${max_usd:.2f}.")
    agreement = tally.checker_ok / tally.checker_all if tally.checker_all else 0.0
    bar = settings.config.eval.checker_agreement_min
    passed = (only == "extractor" or agreement >= bar) and not tally.traps_accepted
    roles = settings.config.llm.roles
    summary = [
        f"# Prompt golden set: {settings.env} profile",
        "",
        f"- extractor {roles.extractor.model}; checker {roles.checker.model}"
        f" ({roles.checker.effort or roles.checker.temperature})",
        f"- expected claims found: {tally.found}/{tally.expected}",
        f"- expected fields correct: {tally.fields_ok}/{tally.fields_all}",
        f"- quotes located exactly: {tally.quotes_ok}/{tally.quotes_all}",
        f"- checker agreement: {tally.checker_ok}/{tally.checker_all} ({agreement:.0%};"
        f" bar {bar:.0%})",
        f"- trap claims mislabelled and then supported: {len(tally.traps_accepted)}"
        + (f" ({'; '.join(tally.traps_accepted)})" if tally.traps_accepted else ""),
        f"- failed model calls: {tally.failures}",
        f"- cost: ${ledger.cost_micro_usd / 1e6:.4f} in {ledger.model_calls} calls",
        f"- **{'PASS' if passed else 'FAIL'}**",
    ]
    report = "\n".join(summary + tally.lines) + "\n"
    results = GOLDEN / "results"
    results.mkdir(exist_ok=True)
    (results / f"{settings.env}-latest.md").write_text(report, encoding="utf-8")
    print(report)
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--only", choices=["extractor", "checker"])
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(asyncio.run(main(args.max_usd, args.only)))
