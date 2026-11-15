import json
from pathlib import Path

import httpx
import pytest

from storyquest.models.embedder import (
    CachedEmbedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
    OpenAICompatibleEmbedder,
    QueryPrefixEmbedder,
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


def make_openai(handler, dim: int = 2, batch_size: int = 16):  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    embedder = OpenAICompatibleEmbedder(
        "https://host:1035/v1/",
        "KEY",
        "bge-small-en-v1.5",
        dim,
        None,
        batch_size=batch_size,
        requests_per_minute=0,
        http=http,
        sleep=sleeps.append,
    )
    return embedder, sleeps


def openai_answer(request: httpx.Request, values: list[float]) -> httpx.Response:
    n = len(json.loads(request.content)["input"])
    data = [{"object": "embedding", "index": i, "embedding": values} for i in range(n)]
    return httpx.Response(200, json={"object": "list", "data": data})


def test_openai_sends_model_and_texts_and_returns_unit_vectors() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return openai_answer(request, [3.0, 4.0])

    embedder, _ = make_openai(handler)
    assert embedder.embed(["a passage"], query=False) == [[0.6, 0.8]]
    body = json.loads(seen[0].content)
    assert body == {"model": "bge-small-en-v1.5", "input": ["a passage"]}
    assert str(seen[0].url) == "https://host:1035/v1/embeddings"
    assert seen[0].headers["Authorization"] == "Bearer KEY"
    assert embedder.model_id == "bge-small-en-v1.5:2"


def test_openai_sends_batches_of_at_most_16_and_keeps_the_order() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(json.loads(request.content)["input"]))
        return openai_answer(request, [1.0, 0.0])

    embedder, _ = make_openai(handler)
    assert len(embedder.embed([f"t{i}" for i in range(40)], query=False)) == 40
    assert sizes == [16, 16, 8]

    # Answers out of order: the client must put them back by `index`.

    order: list[str] = []

    def echo(request: httpx.Request) -> httpx.Response:
        texts = json.loads(request.content)["input"]
        order.extend(texts)
        data = [{"index": i, "embedding": [1.0, float(i)]} for i in range(len(texts))]
        return httpx.Response(200, json={"data": list(reversed(data))})

    small, _ = make_openai(echo, batch_size=3)
    out = small.embed(["a", "b", "c"], query=False)
    assert order == ["a", "b", "c"]
    assert out == [normalise([1.0, 0.0]), normalise([1.0, 1.0]), normalise([1.0, 2.0])]


def test_openai_retries_capacity_errors_then_gives_up_on_other_errors() -> None:
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 200:
            return openai_answer(request, [1.0, 0.0])
        return httpx.Response(status, json={})

    embedder, sleeps = make_openai(handler)
    assert embedder.embed(["x"], query=True) == [[1.0, 0.0]]
    assert sleeps == [2.0, 4.0]

    bad, _ = make_openai(lambda request: httpx.Response(401, text="bad key"))
    with pytest.raises(EmbeddingError, match="HTTP 401"):
        bad.embed(["x"], query=True)


def test_openai_rejects_wrong_sizes_counts_and_shapes() -> None:
    wrong_size, _ = make_openai(lambda request: openai_answer(request, [1.0, 2.0, 3.0]))
    with pytest.raises(EmbeddingError, match="size"):
        wrong_size.embed(["x"], query=False)

    too_few, _ = make_openai(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(EmbeddingError, match="number"):
        too_few.embed(["x"], query=False)

    no_vector, _ = make_openai(lambda request: httpx.Response(200, json={"data": [{"index": 0}]}))
    with pytest.raises(EmbeddingError, match="shape"):
        no_vector.embed(["x"], query=False)

    with pytest.raises(EmbeddingError, match="BATCH_SIZE"):
        make_openai(lambda request: openai_answer(request, [1.0, 0.0]), batch_size=0)


def test_openai_cuts_long_texts_to_stay_under_the_token_limit() -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.extend(json.loads(request.content)["input"])
        return openai_answer(request, [1.0, 0.0])

    http = httpx.Client(transport=httpx.MockTransport(handler))
    embedder = OpenAICompatibleEmbedder(
        "https://h/v1", "K", "m", 2, None, max_chars=10, requests_per_minute=0, http=http
    )
    embedder.embed(["short", "a much longer paragraph"], query=False)
    assert sent == ["short", "a much lon"]
    with pytest.raises(EmbeddingError, match="MAX_CHARS"):
        OpenAICompatibleEmbedder("https://h/v1", "K", "m", 2, None, max_chars=0, http=http)


def test_the_query_prefix_goes_on_questions_only_and_is_cached_separately(
    tmp_path: Path,
) -> None:
    inner = FakeEmbedder()
    prefixed = QueryPrefixEmbedder(CachedEmbedder(inner, tmp_path), "Represent this: ")
    prefixed.embed(["who is akela"], query=True)
    prefixed.embed(["a passage"], query=False)
    assert inner.calls == [(["Represent this: who is akela"], True), (["a passage"], False)]

    plain = CachedEmbedder(inner, tmp_path)
    plain.embed(["who is akela"], query=True)
    assert inner.calls[-1] == (["who is akela"], True)  # no prefix: not served from that cache
    assert prefixed.model_id == inner.model_id and prefixed.dim == inner.dim


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
