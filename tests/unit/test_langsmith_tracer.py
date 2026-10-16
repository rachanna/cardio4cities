"""LangSmith tracing (E-14, BD-59): spans become nested LangSmith runs, one trace per run,
question or report; model calls show their prompt, output and usage; what is sent is
redacted and bounded; root runs are capped per day; a failing client never fails the
step; LangSmith is opt-in, local only, and LangGraph's own tracing is refused. A fake
client stands in for LangSmith: no network. Fictional text only."""

from datetime import date
from typing import Any

import pytest

from app.adapters.tracing.langsmith import LangsmithTracer, make
from app.ports.tracing import TRACE_ID, Tracers
from app.settings import ConfigError, load_settings


class FakeClient:
    """Records what the SDK would send: runs created when a span opens, updated when it
    closes."""

    def __init__(self, fail: bool = False) -> None:
        self.created: dict[str, dict[str, Any]] = {}
        self.updated: dict[str, dict[str, Any]] = {}
        self.fail = fail

    def create_run(self, **run: Any) -> None:
        if self.fail:
            raise ConnectionError("no route")
        self.created[str(run["id"])] = run

    def update_run(self, **run: Any) -> None:
        if self.fail:
            raise ConnectionError("no route")
        self.updated[str(run["run_id"])] = run

    def flush(self, timeout: float | None = None) -> None:
        pass

    def named(self, name: str) -> dict[str, Any]:
        (run_id,) = [i for i, r in self.created.items() if r["name"] == name]
        return {**self.created[run_id], **self.updated[run_id]}


def tracer(client: FakeClient, max_traces_per_day: int = 10, limit: int = 4000) -> LangsmithTracer:
    return LangsmithTracer(client, "test-project", limit, max_traces_per_day, 1.0, ["local"])


async def _model_call(t: LangsmithTracer, user: str = "WINDOW TEXT") -> None:
    async with t.span("llm:extractor", provider="openai", model="gpt-test"):
        t.event("llm.request", system="SYSTEM", user=user, params={"model": "gpt-test"})
        t.event(
            "llm.response",
            output='{"claims": []}',
            usage={"model_id": "gpt-test", "tokens_in": 120, "tokens_out": 30, "cost_micro_usd": 0},
        )


async def test_a_run_its_nodes_and_its_model_calls_are_one_trace() -> None:
    client = FakeClient()
    t = tracer(client)
    TRACE_ID.set("run_halden")
    async with t.span("run", resumed=False), t.span("node:extract", slot_id="S04"):
        await _model_call(t)

    root, node, call = (
        client.named("run"),
        client.named("node:extract"),
        client.named("llm:extractor"),
    )
    assert root["session_name"] == "test-project"
    assert root["tags"] == ["local"]
    assert root["extra"]["metadata"]["trace_id"] == "run_halden"
    assert node["parent_run_id"] == root["id"]
    assert call["parent_run_id"] == node["id"]
    assert root["trace_id"] == node["trace_id"] == call["trace_id"]
    assert node["inputs"] == {"slot_id": "S04"}
    assert all(r["end_time"] is not None for r in (root, node, call))


async def test_a_model_call_shows_its_prompt_output_model_and_usage() -> None:
    client = FakeClient()
    t = tracer(client)
    async with t.span("ask", question="How many heart clinics does Halden Bay run?"):
        await _model_call(t)

    call = client.named("llm:extractor")
    assert call["run_type"] == "llm"
    assert call["inputs"]["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "WINDOW TEXT"},
    ]
    assert call["outputs"] == {"output": '{"claims": []}'}
    metadata = call["extra"]["metadata"]
    assert (metadata["ls_provider"], metadata["ls_model_name"]) == ("openai", "gpt-test")
    assert metadata["usage_metadata"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
    }


async def test_a_failed_step_is_sent_with_its_error_and_still_raised() -> None:
    client = FakeClient()
    t = tracer(client)
    with pytest.raises(ValueError, match="boom"):
        async with t.span("run"), t.span("node:check"):
            raise ValueError("boom")

    assert client.named("node:check")["error"] == "ValueError: boom"
    assert client.named("run")["error"] == "ValueError: boom"


async def test_secrets_are_redacted_and_long_text_bounded_before_sending() -> None:
    client = FakeClient()
    t = tracer(client, limit=20)
    async with t.span("run", api_key="sk-x"):
        await _model_call(t, user="Halden Bay " * 100)

    assert client.named("run")["inputs"] == {"api_key": "[redacted]"}
    user = client.named("llm:extractor")["inputs"]["messages"][1]["content"]
    assert user == "Halden Bay Halden Ba… [1100 characters, truncated]"


async def test_traces_past_the_daily_cap_are_not_sent_and_the_cap_resets_each_day() -> None:
    client = FakeClient()
    t = tracer(client, max_traces_per_day=1)
    async with t.span("run"):
        pass
    async with t.span("ask"):
        await _model_call(t)

    assert [r["name"] for r in client.created.values()] == ["run"]

    t._day = date(2000, 1, 1)  # a new day
    async with t.span("ask"):
        pass
    assert [r["name"] for r in client.created.values()] == ["run", "ask"]


async def test_an_unreachable_langsmith_never_fails_the_step() -> None:
    done = []
    fanout = Tracers([tracer(FakeClient(fail=True))])
    async with fanout.span("run"):
        fanout.event("llm.request", system="S", user="U")
        done.append(True)

    assert done == [True]


# --- configuration -----------------------------------------------------------


def test_langsmith_is_off_unless_asked_for(valid_env: dict[str, str]) -> None:
    assert "langsmith" not in load_settings(valid_env).config.tracing.providers

    valid_env.update(RAG_TRACE_LANGSMITH="1", LANGSMITH_ENDPOINT="https://api.smith.langchain.com")
    assert "langsmith" in load_settings(valid_env).config.tracing.providers


def test_langsmith_needs_its_key_and_its_regions_endpoint(valid_env: dict[str, str]) -> None:
    valid_env["RAG_TRACE_LANGSMITH"] = "1"
    del valid_env["LANGSMITH_API_KEY"]
    with pytest.raises(ConfigError) as exc:
        load_settings(valid_env)

    problems = "\n".join(exc.value.problems)
    assert "LANGSMITH_API_KEY is not set" in problems
    assert "LANGSMITH_ENDPOINT is not set" in problems


def test_the_deployed_profile_refuses_langsmith(valid_env: dict[str, str]) -> None:
    valid_env.update(APP_ENV="deployed", RAG_TRACE_LANGSMITH="1")
    with pytest.raises(ConfigError) as exc:
        load_settings(valid_env)

    assert any("refused with APP_ENV=deployed (BD-59)" in p for p in exc.value.problems)


@pytest.mark.parametrize("name", ["LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"])
def test_langgraphs_own_tracing_is_refused(valid_env: dict[str, str], name: str) -> None:
    valid_env[name] = "true"
    with pytest.raises(ConfigError) as exc:
        load_settings(valid_env)

    assert any(p.startswith(f"{name} must not be on") for p in exc.value.problems)


def test_the_adapter_is_built_from_the_profile_without_a_network_call(
    valid_env: dict[str, str],
) -> None:
    valid_env.update(RAG_TRACE_LANGSMITH="1", LANGSMITH_ENDPOINT="https://api.smith.langchain.com")
    built = make(load_settings(valid_env))
    try:
        assert isinstance(built, LangsmithTracer)
    finally:
        built._client.cleanup(timeout=0)
