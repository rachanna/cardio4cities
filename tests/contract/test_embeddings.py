"""Embeddings adapters (AT-35): every adapter runs the same contract tests. OpenAI against
a local stand-in (no paid call). Sentence Transformers runs its real model where its
optional group is installed; elsewhere (CI, the image) a stand-in module takes the
package's place, so the adapter's own code still runs (code review RV-102)."""

import functools
import hashlib
import http.server
import importlib.util
import json
import math
import sys
import threading
import types
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.adapters.embeddings.openai import OpenAIEmbeddings
from app.ports.embeddings import EmbeddingsPort
from app.ports.errors import ProviderUnavailableError

INSTALLED = importlib.util.find_spec("sentence_transformers") is not None
ST_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TEXTS = ["Halden Bay heart health", "salud cardiaca en Halden Bay", "Norvania clinics"]


def text_vector(text: str, dimension: int) -> list[float]:
    """A vector that depends on the text only, so order can be checked."""
    digest = hashlib.sha256(text.encode()).digest()
    return [digest[i % len(digest)] / 255 for i in range(dimension)]


@dataclass
class OpenAIStub:
    base: str = ""
    seen: list[dict[str, Any]] = field(default_factory=list)
    status: int = 200  # any other status: the server fails with it


@pytest.fixture
def fake_openai() -> Iterator[OpenAIStub]:
    stub = OpenAIStub()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            stub.seen.append(request)
            if stub.status != 200:
                self.send_response(stub.status)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            data = [
                {"object": "embedding", "index": i, "embedding": text_vector(t, 3)}
                for i, t in enumerate(request["input"])
            ][::-1]  # out of order on purpose
            body = json.dumps(
                {
                    "object": "list",
                    "data": data,
                    "model": request["model"],
                    "usage": {"prompt_tokens": 3, "total_tokens": 3},
                }
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stub.base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield stub
    server.shutdown()
    server.server_close()


def stand_in_sentence_transformers(dimension: int) -> types.ModuleType:
    """The package's surface the adapter uses: the model class, encode, the dimension."""

    class SentenceTransformer:
        def __init__(self, name: str, device: str) -> None:
            self.name, self.device = name, device

        def encode(self, texts: list[str], **_: Any) -> list[list[float]]:
            return [text_vector(t, dimension) for t in texts]

        def get_embedding_dimension(self) -> int:
            return dimension

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = SentenceTransformer  # type: ignore[attr-defined]
    return module


@pytest.fixture(params=["openai", "sentence_transformers"])
def embeddings(
    request: pytest.FixtureRequest,
    fake_openai: OpenAIStub,
    monkeypatch: pytest.MonkeyPatch,
) -> EmbeddingsPort:
    if request.param == "openai":
        return openai(fake_openai)
    if INSTALLED:
        return real_sentence_transformers()
    monkeypatch.setitem(sys.modules, "sentence_transformers", stand_in_sentence_transformers(384))
    from app.adapters.embeddings.sentence_transformers import SentenceTransformerEmbeddings

    return SentenceTransformerEmbeddings(ST_MODEL, 384, "st_multiling_minilm_v1")


@functools.cache
def real_sentence_transformers() -> EmbeddingsPort:
    """The real model, loaded once for the module (it takes seconds)."""
    from app.adapters.embeddings.sentence_transformers import SentenceTransformerEmbeddings

    return SentenceTransformerEmbeddings(ST_MODEL, 384, "st_multiling_minilm_v1")


# --- the shared EmbeddingsPort contract --------------------------------------------------


async def test_one_vector_per_text_of_the_configured_dimension(embeddings: EmbeddingsPort) -> None:
    vectors = await embeddings.embed(TEXTS)

    assert len(vectors) == len(TEXTS)
    assert all(len(v) == embeddings.dimension for v in vectors)
    assert all(isinstance(x, float) for v in vectors for x in v)


async def test_vectors_keep_the_order_of_the_texts(embeddings: EmbeddingsPort) -> None:
    forward = await embeddings.embed(TEXTS)
    backward = await embeddings.embed(TEXTS[::-1])

    for a, b in zip(forward, backward[::-1], strict=True):
        assert all(math.isclose(x, y, abs_tol=1e-5) for x, y in zip(a, b, strict=True))


async def test_no_texts_give_no_vectors(embeddings: EmbeddingsPort) -> None:
    assert await embeddings.embed([]) == []


def test_the_key_names_the_model_that_made_the_vectors(embeddings: EmbeddingsPort) -> None:
    """R-82 (BD-14): the key is what the graph and the collection are marked with."""
    assert embeddings.key in {"openai_small_v1", "st_multiling_minilm_v1"}


# --- adapter specifics -----------------------------------------------------------------------


def openai(stub: OpenAIStub) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        "test-key", "text-embedding-3-small", 3, "openai_small_v1", stub.base, max_retries=0
    )


async def test_openai_embeddings_send_the_configured_model(fake_openai: OpenAIStub) -> None:
    await openai(fake_openai).embed(["first chunk"])

    assert fake_openai.seen[0]["model"] == "text-embedding-3-small"


async def test_openai_embeddings_failure_is_the_port_error(fake_openai: OpenAIStub) -> None:
    fake_openai.status = 503

    with pytest.raises(ProviderUnavailableError, match="openai embeddings"):
        await openai(fake_openai).embed(["first chunk"])


@pytest.mark.skipif(not INSTALLED, reason="optional group: uv sync --group local-embeddings")
async def test_sentence_transformers_model_reports_the_configured_dimension() -> None:
    adapter = real_sentence_transformers()

    assert adapter.reported_dimension() == 384  # type: ignore[attr-defined]
