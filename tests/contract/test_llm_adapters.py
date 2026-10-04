"""LLM adapters against a local stand-in server (no paid calls): what each adapter sends
(BD-05, BD-08) and how it maps answers and failures onto the LLMPort contract."""

import http.server
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import BaseModel

from app.adapters.llm.anthropic import AnthropicLLM
from app.adapters.llm.openai import OpenAILLM
from app.ports.errors import LLMOutputValidationError, ProviderUnavailableError
from app.ports.llm import LLMParams


class Verdict(BaseModel):
    label: str
    reason: str


GOOD = json.dumps({"label": "supported", "reason": "Halden Bay figure stated"})


@dataclass
class Stub:
    status: int = 200
    body: dict[str, Any] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    port: int = 0


@pytest.fixture
def stub() -> Iterator[Stub]:
    s = Stub()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", 0))
            s.requests.append({"path": self.path, **json.loads(self.rfile.read(length))})
            data = json.dumps(s.body).encode()
            self.send_response(s.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    s.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield s
    finally:
        server.shutdown()
        server.server_close()


def claude_message(text: str, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test", "type": "message", "role": "assistant",
        "model": "claude-haiku-4-5-20251001", "content": [{"type": "text", "text": text}],
        "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
    }  # fmt: skip


def openai_response(text: str) -> dict[str, Any]:
    return {
        "id": "resp_test", "object": "response", "created_at": 0, "model": "gpt-6-luna",
        "status": "completed", "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
        "output": [{
            "type": "message", "id": "msg_test", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }],
        "usage": {
            "input_tokens": 900, "output_tokens": 300, "total_tokens": 1200,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 250},
        },
    }  # fmt: skip


def claude(stub: Stub) -> AnthropicLLM:
    return AnthropicLLM("test-key", base_url=f"http://127.0.0.1:{stub.port}", max_retries=0)


def gpt(stub: Stub) -> OpenAILLM:
    return OpenAILLM("test-key", base_url=f"http://127.0.0.1:{stub.port}/v1", max_retries=0)


HAIKU = LLMParams(model="claude-haiku-4-5-20251001", max_output_tokens=4000, temperature=0)
OPUS = LLMParams(model="claude-opus-5-5", max_output_tokens=8000, effort="high")
LUNA = LLMParams(model="gpt-6-luna", max_output_tokens=8000, effort="low")


async def test_claude_returns_parsed_output_with_tokens_and_cost(stub: Stub) -> None:
    stub.body = claude_message(GOOD)
    result = await claude(stub).complete("checker", "system text", "user text", Verdict, HAIKU)
    assert result.parsed == Verdict(label="supported", reason="Halden Bay figure stated")
    assert (result.model_id, result.family) == ("claude-haiku-4-5-20251001", "anthropic")
    assert (result.tokens_in, result.tokens_out) == (1200, 80)
    assert result.cost_micro_usd > 0


async def test_claude_sends_temperature_or_effort_never_a_forced_tool(stub: Stub) -> None:
    stub.body = claude_message(GOOD)
    await claude(stub).complete("extractor", "s", "u", Verdict, HAIKU)
    await claude(stub).complete("checker", "s", "u", Verdict, OPUS)
    haiku, opus = stub.requests
    assert haiku["path"] == "/v1/messages"
    assert haiku["temperature"] == 0
    assert "effort" not in json.dumps(haiku.get("output_config", {}))
    assert opus["output_config"]["effort"] == "high"
    assert "temperature" not in opus
    for body in stub.requests:
        assert "tool_choice" not in body
        assert "tools" not in body
        assert body["output_config"]["format"]["type"] == "json_schema"


async def test_claude_output_outside_the_schema_is_a_validation_error(stub: Stub) -> None:
    stub.body = claude_message(json.dumps({"label": "supported"}))
    with pytest.raises(LLMOutputValidationError):
        await claude(stub).complete("checker", "s", "u", Verdict, HAIKU)


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_claude_overload_and_outages_are_provider_unavailable(
    stub: Stub, status: int
) -> None:
    stub.status = status
    stub.body = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    with pytest.raises(ProviderUnavailableError):
        await claude(stub).complete("checker", "s", "u", Verdict, HAIKU)


async def test_claude_refusal_is_provider_unavailable(stub: Stub) -> None:
    stub.body = claude_message(GOOD, stop="refusal")
    with pytest.raises(ProviderUnavailableError):
        await claude(stub).complete("checker", "s", "u", Verdict, HAIKU)


async def test_openai_returns_parsed_output_and_sends_effort_without_storing(
    stub: Stub,
) -> None:
    stub.body = openai_response(GOOD)
    result = await gpt(stub).complete("checker", "system text", "user text", Verdict, LUNA)
    assert result.parsed == Verdict(label="supported", reason="Halden Bay figure stated")
    assert (result.family, result.tokens_in, result.tokens_out) == ("openai", 900, 300)
    (body,) = stub.requests
    assert body["path"] == "/v1/responses"
    assert body["reasoning"] == {"effort": "low"}
    assert body["store"] is False
    assert body["instructions"] == "system text"
    assert body["text"]["format"]["type"] == "json_schema"
    assert "temperature" not in body


async def test_openai_out_of_credit_is_provider_unavailable(stub: Stub) -> None:
    """No credit left must hand over to the labelled fallback, not fail the run."""
    stub.status = 429
    stub.body = {"error": {"type": "insufficient_quota", "code": "insufficient_quota",
                           "message": "You exceeded your current quota."}}  # fmt: skip
    with pytest.raises(ProviderUnavailableError, match="insufficient_quota"):
        await gpt(stub).complete("checker", "s", "u", Verdict, LUNA)


async def test_openai_output_outside_the_schema_is_a_validation_error(stub: Stub) -> None:
    stub.body = openai_response("not json at all")
    with pytest.raises(LLMOutputValidationError):
        await gpt(stub).complete("checker", "s", "u", Verdict, LUNA)


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_any_other_http_error_is_a_port_error_from_both_adapters(
    stub: Stub, status: int
) -> None:
    """BD-21 (code review RV-011): an unmapped vendor error used to escape the port and
    abort the whole node; now it is ProviderUnavailableError, so the checker falls back."""
    stub.status = status
    stub.body = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    with pytest.raises(ProviderUnavailableError, match=f"HTTP {status}"):
        await claude(stub).complete("checker", "s", "u", Verdict, HAIKU)
    stub.body = {"error": {"type": "invalid_request_error", "code": None, "message": "bad"}}
    with pytest.raises(ProviderUnavailableError, match=f"HTTP {status}"):
        await gpt(stub).complete("checker", "s", "u", Verdict, LUNA)


# --- usage and prompt caching (BD-30) -----------------------------------------------------


async def test_claude_caches_the_system_prompt_and_prices_cache_tokens(stub: Stub) -> None:
    message = claude_message(GOOD)
    message["usage"] = {
        "input_tokens": 200,
        "output_tokens": 80,
        "cache_read_input_tokens": 4000,
        "cache_creation_input_tokens": 0,
    }
    stub.body = message
    llm = AnthropicLLM("test-key", base_url=f"http://127.0.0.1:{stub.port}", max_retries=0,
                       prompt_cache=True)  # fmt: skip
    result = await llm.complete("extractor", "system text", "u", Verdict, HAIKU)
    (body,) = stub.requests
    assert body["system"] == [
        {"type": "text", "text": "system text", "cache_control": {"type": "ephemeral"}}
    ]
    assert (result.tokens_in, result.cached_tokens) == (4200, 4000)
    # Haiku $1 per million in, $5 out: 200 plain + 4000 read at a tenth, 80 out
    assert result.cost_micro_usd == round(200 * 1.0 + 4000 * 0.1 + 80 * 5.0)


async def test_openai_sends_a_cache_key_and_reports_cached_and_reasoning_tokens(
    stub: Stub,
) -> None:
    response = openai_response(GOOD)
    response["usage"]["input_tokens_details"] = {"cached_tokens": 700}
    stub.body = response
    llm = OpenAILLM("test-key", base_url=f"http://127.0.0.1:{stub.port}/v1", max_retries=0,
                    prompt_cache=True)  # fmt: skip
    result = await llm.complete("extractor", "s", "u", Verdict, LUNA)
    (body,) = stub.requests
    assert body["prompt_cache_key"] == "c4c-extractor"
    assert (result.cached_tokens, result.reasoning_tokens) == (700, 250)
    # cached input is billed at the full rate until its published rate is confirmed (owner)
    assert result.cost_micro_usd == round(900 * 0.10 + 300 * 0.50)


async def test_no_cache_fields_are_sent_when_caching_is_off(stub: Stub) -> None:
    stub.body = claude_message(GOOD)
    await claude(stub).complete("extractor", "system text", "u", Verdict, HAIKU)
    assert stub.requests[0]["system"] == "system text"
    stub.body = openai_response(GOOD)
    await gpt(stub).complete("extractor", "s", "u", Verdict, LUNA)
    assert "prompt_cache_key" not in stub.requests[1]


async def test_a_call_that_returns_no_output_still_reports_its_usage(stub: Stub) -> None:
    """RV-049: failed calls added nothing to the cap or the summary."""
    message = claude_message(GOOD, stop="refusal")
    stub.body = message
    with pytest.raises(ProviderUnavailableError) as declined:
        await claude(stub).complete("checker", "s", "u", Verdict, HAIKU)
    assert declined.value.usage is not None
    assert declined.value.usage.tokens_in == 1200
