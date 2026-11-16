"""The embedding layer: turning text into vectors for the meaning half of hybrid search."""

import hashlib
import json
import math
import os
import re
import ssl
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

import httpx

BATCH_SIZE = 100  # texts per request
OPENAI_BATCH_SIZE = 16  # the course's embedding endpoint accepts at most 16 texts per request
# Its model takes at most 512 tokens per text. Measured on the Jungle Book, long passages run
# about 4.2 characters a token (1,522 characters = 347 tokens; 2,400 characters = 579 tokens,
# refused), so 1,600 characters (about 385 tokens) leaves a safe margin.
OPENAI_MAX_CHARS = 1600
RETRY_DELAYS = (2.0, 4.0, 8.0, 16.0)
_RETRYABLE = (429, 503)
_OPENAI_RETRYABLE = (429, 502, 503, 504)  # "capacity error": wait briefly and retry the batch
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    model_id: str
    dim: int
    # Characters of surrounding scene text embedded with each chunk (0 = the chunk alone). The
    # search still returns the chunk itself; only its vector carries the extra context.
    context_chars: int

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        """One unit-length vector per text. `query` marks a search question, not a document."""
        ...


def normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


class GeminiEmbedder:
    """Google's Gemini embedding API (gemini-embedding-001: a task type per request)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        dim: int,
        *,
        requests_per_minute: int = 30,
        timeout: float = 60.0,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        self.model_id = f"{model}:{dim}"
        self.dim = dim
        self.context_chars = 0
        self._model = model
        self._url = f"{_ENDPOINT}/{model}:batchEmbedContents"
        self._headers = {"x-goog-api-key": api_key}
        self._sleep = sleep
        self._delays = retry_delays
        self._min_gap = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._last = 0.0
        self._http = http or httpx.Client(verify=ssl.create_default_context(), timeout=timeout)

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            out.extend(self._batch(texts[start : start + BATCH_SIZE], query))
        return out

    def _batch(self, texts: list[str], query: bool) -> list[list[float]]:
        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
        payload = {
            "requests": [
                {
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": task,
                    "outputDimensionality": self.dim,
                }
                for t in texts
            ]
        }
        data = self._post(payload)
        vectors = [e["values"] for e in data.get("embeddings", [])]
        if len(vectors) != len(texts) or any(len(v) != self.dim for v in vectors):
            raise EmbeddingError(
                "the embedding API returned an unexpected number or size of vectors"
            )
        return [normalise(v) for v in vectors]

    def _post(self, payload: Mapping[str, object]) -> dict[str, list[dict[str, list[float]]]]:
        for delay in (*self._delays, None):
            wait = self._min_gap - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self._http.post(self._url, json=payload, headers=self._headers)
            except httpx.HTTPError as e:
                raise EmbeddingError(f"request failed: {type(e).__name__}: {e}") from e
            if resp.status_code == 200:
                body: dict[str, list[dict[str, list[float]]]] = resp.json()
                return body
            if resp.status_code in _RETRYABLE and delay is not None:
                self._sleep(delay)
                continue
            raise EmbeddingError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        raise EmbeddingError("unreachable")


class OpenAICompatibleEmbedder:
    """An OpenAI-style `/embeddings` endpoint, such as the course's bge-small-en-v1.5 service.

    The model has no query/document task type, so `query` is ignored here; a query prefix, if
    wanted, is added by `QueryPrefixEmbedder` around the cache.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        ca_cert_path: Path | None,
        *,
        batch_size: int = OPENAI_BATCH_SIZE,
        max_chars: int = OPENAI_MAX_CHARS,
        requests_per_minute: int = 30,
        timeout: float = 60.0,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        if batch_size < 1:
            raise EmbeddingError(f"EMBEDDING_BATCH_SIZE must be at least 1, not {batch_size}")
        if max_chars < 1:
            raise EmbeddingError(f"EMBEDDING_MAX_CHARS must be at least 1, not {max_chars}")
        self.model_id = f"{model}:{dim}"
        self.dim = dim
        self.context_chars = 0
        self._model = model
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._batch_size = batch_size
        self._max_chars = max_chars
        self._sleep = sleep
        self._delays = retry_delays
        self._min_gap = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._last = 0.0
        if http is None:
            cafile = str(ca_cert_path) if ca_cert_path else None
            http = httpx.Client(verify=ssl.create_default_context(cafile=cafile), timeout=timeout)
        self._http = http

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            out.extend(self._batch(texts[start : start + self._batch_size]))
        return out

    def _batch(self, texts: list[str]) -> list[list[float]]:
        # The endpoint refuses (HTTP 422) any text over 512 model tokens instead of trimming
        # it, so a long paragraph is cut to its opening, which carries most of its meaning.
        texts = [t[: self._max_chars] for t in texts]
        data = self._post({"model": self._model, "input": texts})
        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError("the embedding API returned an unexpected number of vectors")
        try:
            ordered = sorted(items, key=lambda item: int(item["index"]))
            vectors = [[float(x) for x in item["embedding"]] for item in ordered]
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError(f"the embedding API returned an unexpected shape: {e}") from e
        if [int(item["index"]) for item in ordered] != list(range(len(texts))):
            raise EmbeddingError("the embedding API returned unexpected vector indexes")
        if any(len(v) != self.dim for v in vectors):
            raise EmbeddingError(
                f"the embedding API returned an unexpected size of vectors (expected {self.dim})"
            )
        return [normalise(v) for v in vectors]

    def _post(self, payload: Mapping[str, object]) -> dict[str, object]:
        for delay in (*self._delays, None):
            wait = self._min_gap - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self._http.post(self._url, json=payload, headers=self._headers)
            except httpx.HTTPError as e:
                raise EmbeddingError(f"request failed: {type(e).__name__}: {e}") from e
            if resp.status_code == 200:
                body = resp.json()
                if not isinstance(body, dict):
                    raise EmbeddingError("the embedding API returned an unexpected shape")
                return body
            if resp.status_code in _OPENAI_RETRYABLE and delay is not None:
                self._sleep(delay)
                continue
            raise EmbeddingError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        raise EmbeddingError("unreachable")


class SceneContextEmbedder:
    """Says that chunks are embedded with up to `context_chars` of text around them, taken from
    the same scene (beat) only, and tags the vectors so they never mix with plain ones.

    A 500-character chunk often lacks who "he" is or where the scene is; with its surroundings
    the small bge model finds the right passage more often. Because the context never leaves the
    chunk's beat, a chunk the child cannot see yet never lends its words to one they can.
    """

    def __init__(self, inner: Embedder, context_chars: int) -> None:
        if context_chars < 1:
            raise EmbeddingError(f"EMBEDDING_CONTEXT_CHARS must be positive, not {context_chars}")
        self._inner = inner
        self.model_id = f"{inner.model_id}+ctx{context_chars}"
        self.dim = inner.dim
        self.context_chars = context_chars

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        return self._inner.embed(texts, query=query)


class QueryPrefixEmbedder:
    """Adds an instruction in front of search questions only (documents are left as they are).

    BGE models are trained to match "<instruction> <question>" against plain passages. It wraps
    the cache, so a prefixed question is cached under its prefixed text.
    """

    def __init__(self, inner: Embedder, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix.strip()
        self.model_id = inner.model_id
        self.dim = inner.dim
        self.context_chars = inner.context_chars

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        if query and self._prefix:
            texts = [f"{self._prefix} {t}" for t in texts]
        return self._inner.embed(texts, query=query)


class FakeEmbedder:
    """Deterministic bag-of-words vectors for tests. `synonyms` maps a word to a shared token."""

    def __init__(self, dim: int = 64, synonyms: dict[str, str] | None = None) -> None:
        self.model_id = f"fake:{dim}"
        self.dim = dim
        self.context_chars = 0
        self.calls: list[tuple[list[str], bool]] = []
        self._synonyms = synonyms or {}

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        self.calls.append((texts, query))
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for word in re.findall(r"[a-z]+", text.lower()):
            token = self._synonyms.get(word, word[:5])
            slot = int(hashlib.sha256(token.encode()).hexdigest(), 16) % self.dim
            vector[slot] += 1.0
        return normalise(vector)


class CachedEmbedder:
    """Disk cache keyed by model, task and text, so repeated eval runs make no API calls."""

    def __init__(self, inner: Embedder, cache_dir: Path) -> None:
        self._inner = inner
        self._dir = cache_dir
        self.model_id = inner.model_id
        self.dim = inner.dim
        self.context_chars = inner.context_chars

    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        paths = [self._path(t, query) for t in texts]
        found: dict[int, list[float]] = {
            i: json.loads(p.read_text()) for i, p in enumerate(paths) if p.is_file()
        }
        missing = [i for i in range(len(texts)) if i not in found]
        if missing:
            fresh = self._inner.embed([texts[i] for i in missing], query=query)
            for i, vector in zip(missing, fresh, strict=True):
                found[i] = vector
                paths[i].parent.mkdir(parents=True, exist_ok=True)
                tmp = paths[i].with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(vector))
                tmp.replace(paths[i])
        return [found[i] for i in range(len(texts))]

    def _path(self, text: str, query: bool) -> Path:
        key = json.dumps([self.model_id, query, text])
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._dir / digest[:2] / f"{digest}.json"
