"""Embeddings adapters (AT-35). OpenAI against a local stand-in (no paid call);
Sentence Transformers only where its optional group is installed."""

import http.server
import importlib.util
import json
import threading
from collections.abc import Iterator

import pytest

from app.adapters.embeddings.openai import OpenAIEmbeddings


@pytest.fixture
def fake_openai() -> Iterator[tuple[list[dict[str, object]], str]]:
    seen: list[dict[str, object]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append(request)
            data = [
                {"object": "embedding", "index": i, "embedding": [float(i), 0.5, 0.25]}
                for i, _ in enumerate(request["input"])
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield seen, f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


async def test_openai_embeddings_keep_input_order(
    fake_openai: tuple[list[dict[str, object]], str],
) -> None:
    seen, base = fake_openai
    adapter = OpenAIEmbeddings("test-key", "text-embedding-3-small", 3, "openai_small_v1", base)

    vectors = await adapter.embed(["first chunk", "second chunk"])

    assert vectors == [[0.0, 0.5, 0.25], [1.0, 0.5, 0.25]]
    assert seen[0]["model"] == "text-embedding-3-small"
    assert (adapter.dimension, adapter.key) == (3, "openai_small_v1")


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is None,
    reason="optional group: uv sync --group local-embeddings",
)
async def test_sentence_transformers_dimension_matches_config() -> None:
    from app.adapters.embeddings.sentence_transformers import SentenceTransformerEmbeddings

    model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    adapter = SentenceTransformerEmbeddings(model, 384, "st_multiling_minilm_v1")

    vectors = await adapter.embed(["Halden Bay heart health", "salud cardiaca en Halden Bay"])

    assert adapter.reported_dimension() == 384
    assert [len(v) for v in vectors] == [384, 384]
