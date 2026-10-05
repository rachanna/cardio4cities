"""Provider health probes (LLD-4 §7, BD-42) against a local stand-in server: no paid
calls. Each probe asks only for what is free (a model lookup) or what a run asks anyway
(one search for one link), and raises when the provider refuses."""

import asyncio
import http.server
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from app.adapters.embeddings.sentence_transformers import LocalEmbeddingsProbe
from app.adapters.llm.anthropic import AnthropicProbe
from app.adapters.llm.openai import OpenAIProbe
from app.adapters.search._common import PROBE_QUERY, SearchProbe
from app.ports.search import SearchHit

KNOWN = {"halden-model-a", "halden-model-b"}


@dataclass
class Stub:
    paths: list[str] = field(default_factory=list)
    port: int = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def stub() -> Iterator[Stub]:
    s = Stub()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            s.paths.append(self.path)
            model = self.path.rstrip("/").rsplit("/", 1)[-1]
            found = model in KNOWN
            body = (
                {"type": "model", "id": model, "display_name": model,
                 "created_at": "2026-01-01T00:00:00Z", "object": "model", "created": 0,
                 "owned_by": "test"}
                if found
                else {"type": "error", "error": {"type": "not_found_error", "message": "no"}}
            )  # fmt: skip
            data = json.dumps(body).encode()
            self.send_response(200 if found else 404)
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


async def _check_then_close(probe: AnthropicProbe | OpenAIProbe) -> None:
    try:
        await probe.check()
    finally:
        await probe.close()


def test_anthropic_probe_looks_up_every_model_and_spends_nothing(stub: Stub) -> None:
    probe = AnthropicProbe("test-key", sorted(KNOWN), base_url=stub.url)
    asyncio.run(_check_then_close(probe))

    assert probe.component == "llm_anthropic"
    assert stub.paths == [f"/v1/models/{m}" for m in sorted(KNOWN)]  # GET only: no tokens


def test_anthropic_probe_fails_on_an_unknown_model(stub: Stub) -> None:
    """A misspelt model ID in config shows in /health before a run fails on it."""
    probe = AnthropicProbe("test-key", ["halden-model-a", "halden-model-x"], base_url=stub.url)
    with pytest.raises(Exception, match=r"404|not_found|Not Found"):
        asyncio.run(_check_then_close(probe))


def test_openai_probe_looks_up_models_and_fails_on_an_unknown_one(stub: Stub) -> None:
    ok = OpenAIProbe("llm_openai", "test-key", sorted(KNOWN), base_url=f"{stub.url}/v1")
    asyncio.run(_check_then_close(ok))
    assert stub.paths == [f"/v1/models/{m}" for m in sorted(KNOWN)]

    bad = OpenAIProbe("embeddings", "test-key", ["halden-model-x"], base_url=f"{stub.url}/v1")
    with pytest.raises(Exception, match=r"404|not_found|Not Found"):
        asyncio.run(_check_then_close(bad))


class RecordingSearch:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.fail = fail

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        self.calls.append((query, lang, limit))
        if self.fail:
            raise ConnectionError("refused")
        return []


def test_search_probe_asks_for_one_link_with_a_query_naming_no_place() -> None:
    search = RecordingSearch()
    asyncio.run(SearchProbe(search).check())  # no results is still a working provider

    assert search.calls == [(PROBE_QUERY, "en", 1)]
    with pytest.raises(ConnectionError):
        asyncio.run(SearchProbe(RecordingSearch(fail=True)).check())


class FakeLocalModel:
    def __init__(self) -> None:
        self.texts: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.append(texts)
        return [[0.0]]


def test_local_embeddings_probe_embeds_one_word() -> None:
    model = FakeLocalModel()
    asyncio.run(LocalEmbeddingsProbe(model).check())  # type: ignore[arg-type]

    assert model.texts == [["health"]]
