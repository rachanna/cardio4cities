"""Tracing and logs (E-09, BD-58): local trace files record spans and events per trace ID,
redact anything named like a secret and bound long text; a failing tracer never fails the
step it traces; trace files are opt-in (RAG_TRACE=1) and refused in the deployed profile.
Fictional text only."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.adapters.tracing.jsonl import JsonlTracer, clean
from app.logs import JsonFormatter, _TraceId
from app.ports.llm import LLMParams, LLMResult
from app.ports.tracing import TRACE_ID, NoTracing, Tracers, tracer_of
from app.settings import ConfigError, load_settings
from app.workflow.deps import Binding
from app.workflow.llm import _call_once


def _records(root: Path, trace_id: str) -> list[dict[str, Any]]:
    path = root / trace_id / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- what a record may hold ------------------------------------------------


def test_attributes_named_like_secrets_are_redacted_at_any_depth() -> None:
    cleaned = clean(
        {"api_key": "sk-x", "params": {"Authorization": "Bearer y", "model": "m"},
         "dsn": "postgresql://u:p@h/db", "refresh_token": "t", "password": "p"},
        limit=100,
    )  # fmt: skip

    assert cleaned == {
        "api_key": "[redacted]",
        "params": {"Authorization": "[redacted]", "model": "m"},
        "dsn": "[redacted]",
        "refresh_token": "[redacted]",
        "password": "[redacted]",
    }


def test_usage_counts_are_not_mistaken_for_secrets() -> None:
    usage = {"tokens_in": 10, "tokens_out": 2, "max_output_tokens": 900}

    assert clean(usage, limit=100) == usage


def test_long_text_keeps_its_start_and_its_length() -> None:
    cleaned = clean({"user": "Halden Bay " * 100}, limit=20)

    assert cleaned["user"] == {"text": "Halden Bay Halden Ba", "chars": 1100, "truncated": True}


def test_models_are_recorded_as_their_json() -> None:
    class Usage(BaseModel):
        tokens_in: int
        note: str

    assert clean(Usage(tokens_in=3, note="ok"), limit=10) == {"tokens_in": 3, "note": "ok"}


# --- the JSONL tracer ------------------------------------------------------


async def test_spans_nest_and_events_land_in_their_span(tmp_path: Path) -> None:
    tracer = JsonlTracer(tmp_path, max_text_chars=100)
    TRACE_ID.set("run_halden")
    async with tracer.span("node:extract", slot_id="S04"), tracer.span("llm:extractor", model="m"):
        tracer.event("llm.request", user="WINDOW TEXT")

    request, inner, outer = _records(tmp_path, "run_halden")
    assert (outer["name"], outer["parent"], outer["status"]) == ("node:extract", None, "ok")
    assert (inner["name"], inner["parent"]) == ("llm:extractor", outer["span"])
    assert (request["kind"], request["span"]) == ("event", inner["span"])
    assert request["attrs"] == {"user": "WINDOW TEXT"}


async def test_a_failed_step_is_recorded_and_its_error_still_raised(tmp_path: Path) -> None:
    tracer = JsonlTracer(tmp_path, max_text_chars=100)
    TRACE_ID.set("run_failing")
    with pytest.raises(ValueError, match="boom"):
        async with tracer.span("node:check"):
            raise ValueError("boom")

    (span,) = _records(tmp_path, "run_failing")
    assert span["status"] == "ValueError"


async def test_a_trace_id_cannot_leave_the_trace_directory(tmp_path: Path) -> None:
    TRACE_ID.set("../../outside")
    JsonlTracer(tmp_path, max_text_chars=100).event("x")

    assert [p.parent.parent for p in tmp_path.rglob("trace.jsonl")] == [tmp_path]


# --- fan-out: tracing never changes the work --------------------------------


class Broken:
    """A tracer whose every method fails: on opening, on closing, or on an event."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[None]:
        if self.fail_on == "open":
            raise OSError("disk full")
        yield
        if self.fail_on == "close":
            raise OSError("disk full")

    def event(self, name: str, **attrs: Any) -> None:
        raise OSError("disk full")


@pytest.mark.parametrize("fail_on", ["open", "close"])
async def test_a_failing_tracer_never_fails_the_step(tmp_path: Path, fail_on: str) -> None:
    TRACE_ID.set("run_fanout")
    tracer = Tracers([Broken(fail_on), JsonlTracer(tmp_path, max_text_chars=100)])
    done = []
    async with tracer.span("node:select"):
        tracer.event("note")
        done.append(True)

    assert done == [True]
    assert [r["name"] for r in _records(tmp_path, "run_fanout")] == ["note", "node:select"]


async def test_the_steps_own_error_is_what_the_caller_sees() -> None:
    tracer = Tracers([Broken("close")])
    with pytest.raises(KeyError):
        async with tracer.span("node:select"):
            raise KeyError("slot")


def test_no_tracer_configured_means_nothing_recorded() -> None:
    assert isinstance(tracer_of([]), NoTracing)


# --- a model call is traced with its prompt and output ----------------------


class OneReply:
    async def complete(
        self, role: str, system: str, user: str, schema: type[Any], params: LLMParams
    ) -> LLMResult:
        parsed = schema(answer="Halden Bay")
        return LLMResult(
            parsed=parsed, raw_text=parsed.model_dump_json(), model_id=params.model,
            family="openai", tokens_in=10, tokens_out=2, cost_micro_usd=0,
        )  # fmt: skip


class Answer(BaseModel):
    answer: str


class Ledger:
    async def reserve(self, kind: str) -> None:
        pass

    def time_left_s(self) -> float:
        return 60.0

    async def record_model(self, *_: Any) -> None:
        pass


async def _call(tracer: Any) -> tuple[Answer, str]:
    deps: Any = SimpleNamespace(ledger=Ledger(), llm={"openai": OneReply()}, tracer=tracer)
    binding = Binding("openai", "gpt-test", "openai")
    return await _call_once(deps, "planner", binding, "SYSTEM", "USER", Answer)


async def test_a_model_call_records_the_prompt_as_sent_and_the_output(tmp_path: Path) -> None:
    TRACE_ID.set("run_llm")
    await _call(tracer_of([JsonlTracer(tmp_path, max_text_chars=100)]))

    request, response, span = _records(tmp_path, "run_llm")
    assert (span["name"], span["attrs"]["model"]) == ("llm:planner", "gpt-test")
    assert (request["attrs"]["system"], request["attrs"]["user"]) == ("SYSTEM", "USER")
    assert json.loads(response["attrs"]["output"]) == {"answer": "Halden Bay"}
    assert response["attrs"]["usage"]["tokens_in"] == 10


async def test_tracing_does_not_change_a_model_calls_result(tmp_path: Path) -> None:
    TRACE_ID.set("run_same")
    traced = await _call(tracer_of([JsonlTracer(tmp_path, max_text_chars=100)]))

    assert traced == await _call(NoTracing())


# --- configuration -----------------------------------------------------------


def test_trace_files_are_off_unless_asked_for(valid_env: dict[str, str]) -> None:
    assert "jsonl" not in load_settings(valid_env).config.tracing.providers

    valid_env["RAG_TRACE"] = "1"
    assert "jsonl" in load_settings(valid_env).config.tracing.providers


def test_the_deployed_profile_refuses_trace_files(valid_env: dict[str, str]) -> None:
    valid_env.update(APP_ENV="deployed", RAG_TRACE="1")
    with pytest.raises(ConfigError) as exc:
        load_settings(valid_env)

    assert any("refused with APP_ENV=deployed (BD-58)" in p for p in exc.value.problems)


# --- logs -------------------------------------------------------------------


def test_json_log_lines_carry_the_trace_id() -> None:
    TRACE_ID.set("run_logs")
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "slot %s done", ("S04",), None)
    _TraceId().filter(record)

    line = json.loads(JsonFormatter().format(record))
    assert (line["trace_id"], line["msg"], line["level"]) == ("run_logs", "slot S04 done", "INFO")
