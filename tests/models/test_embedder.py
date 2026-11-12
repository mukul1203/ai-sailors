import json
from pathlib import Path

import httpx
import pytest

from storyquest.models.embedder import (
    CachedEmbedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
    normalise,
)


def make(handler, dim: int = 2):  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    embedder = GeminiEmbedder(
        "KEY", "gemini-embedding-001", dim, requests_per_minute=0, http=http, sleep=sleeps.append
    )
    return embedder, sleeps


def answer(request: httpx.Request, values: list[float]) -> httpx.Response:
    n = len(json.loads(request.content)["requests"])
    return httpx.Response(200, json={"embeddings": [{"values": values}] * n})


def test_gemini_sends_task_type_and_dimension_and_returns_unit_vectors() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer(request, [3.0, 4.0])

    embedder, _ = make(handler)
    assert embedder.embed(["a passage"], query=False) == [[0.6, 0.8]]
    embedder.embed(["a question"], query=True)
    first, second = (json.loads(r.content)["requests"][0] for r in seen)
    assert first["taskType"] == "RETRIEVAL_DOCUMENT" and second["taskType"] == "RETRIEVAL_QUERY"
    assert first["outputDimensionality"] == 2
    assert first["content"]["parts"][0]["text"] == "a passage"
    assert first["model"] == "models/gemini-embedding-001"
    assert str(seen[0].url).endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert seen[0].headers["x-goog-api-key"] == "KEY"
    assert embedder.model_id == "gemini-embedding-001:2"


def test_gemini_sends_large_inputs_in_batches_of_100() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(json.loads(request.content)["requests"]))
        return answer(request, [1.0, 0.0])

    embedder, _ = make(handler)
    assert len(embedder.embed([f"t{i}" for i in range(250)], query=False)) == 250
    assert sizes == [100, 100, 50]


def test_gemini_retries_rate_limits_then_gives_up_on_other_errors() -> None:
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return answer(request, [1.0, 0.0]) if status == 200 else httpx.Response(status, json={})

    embedder, sleeps = make(handler)
    assert embedder.embed(["x"], query=True) == [[1.0, 0.0]]
    assert sleeps == [2.0, 4.0]

    bad, _ = make(lambda request: httpx.Response(400, text="bad key"))
    with pytest.raises(EmbeddingError, match="HTTP 400"):
        bad.embed(["x"], query=True)


def test_gemini_rejects_vectors_of_the_wrong_size() -> None:
    embedder, _ = make(lambda request: answer(request, [1.0, 2.0, 3.0]))
    with pytest.raises(EmbeddingError, match="unexpected"):
        embedder.embed(["x"], query=True)


def test_the_fake_embedder_puts_synonyms_in_the_same_place() -> None:
    fake = FakeEmbedder(synonyms={"cry": "sob", "tears": "sob"})
    cry, tears, other = (fake.embed([t], query=False)[0] for t in ("cry", "tears", "bread"))
    assert cry == tears and cry != other
    assert abs(sum(x * x for x in cry) - 1.0) < 1e-9 and normalise([0.0, 0.0]) == [0.0, 0.0]


def test_the_cache_makes_repeat_calls_free_and_keeps_queries_and_documents_apart(
    tmp_path: Path,
) -> None:
    inner = FakeEmbedder()
    cached = CachedEmbedder(inner, tmp_path)
    first = cached.embed(["alpha", "beta"], query=False)
    assert cached.embed(["alpha", "beta"], query=False) == first
    assert len(inner.calls) == 1  # the second call never reached the embedder
    cached.embed(["alpha", "gamma"], query=False)
    assert inner.calls[-1][0] == ["gamma"]  # only the new text is sent
    cached.embed(["alpha"], query=True)
    assert inner.calls[-1] == (["alpha"], True)  # a query is cached separately
