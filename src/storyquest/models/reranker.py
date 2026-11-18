"""Cross-encoder reranking providers."""

import math
from collections.abc import Sequence
from dataclasses import replace
from importlib import import_module
from typing import Protocol

from storyquest.stores.search import SearchHit


class RerankerError(Exception):
    pass


class Reranker(Protocol):
    model_id: str

    def rerank(self, query: str, passages: list[SearchHit]) -> list[SearchHit]:
        """Score query/passage pairs and return passages in relevance order."""
        ...


class _CrossEncoderModel(Protocol):
    def predict(
        self,
        sentences: list[list[str]],
        *,
        batch_size: int,
        convert_to_numpy: bool,
    ) -> Sequence[float]: ...


class FakeReranker:
    """Deterministic query-term-overlap reranker for tests and offline development."""

    model_id = "fake-reranker"

    def rerank(self, query: str, passages: list[SearchHit]) -> list[SearchHit]:
        terms = {term.lower() for term in query.split() if len(term) > 2}
        scored = [(hit, sum(1.0 for term in terms if term in hit.text.lower())) for hit in passages]
        ranked = sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))
        return [
            replace(hit, rerank_score=score, rerank_rank=rank)
            for rank, (hit, score) in enumerate(ranked, 1)
        ]


class CrossEncoderReranker:
    """Local cross encoder loaded lazily through sentence-transformers."""

    def __init__(self, model_name: str, *, batch_size: int = 32, max_length: int = 512) -> None:
        if batch_size < 1:
            raise ValueError("reranker batch_size must be positive")
        if max_length < 1:
            raise ValueError("reranker max_length must be positive")
        self.model_name = model_name
        self.model_id = model_name
        self.batch_size = batch_size
        self.max_length = max_length
        self._model: _CrossEncoderModel | None = None

    def _load(self) -> _CrossEncoderModel:
        if self._model is not None:
            return self._model
        try:
            CrossEncoder = import_module("sentence_transformers").CrossEncoder
        except (ImportError, AttributeError) as e:
            raise RerankerError(
                "cross-encoder reranking needs the sentence-transformers package"
            ) from e
        try:
            self._model = CrossEncoder(self.model_name, max_length=self.max_length)
        except Exception as e:
            raise RerankerError(f"could not load cross-encoder {self.model_name}: {e}") from e
        return self._model

    def rerank(self, query: str, passages: list[SearchHit]) -> list[SearchHit]:
        if not passages:
            return []
        model = self._load()
        try:
            scores = model.predict(
                [[query, passage.text] for passage in passages],
                batch_size=self.batch_size,
                convert_to_numpy=True,
            )
            scored = [(hit, float(score)) for hit, score in zip(passages, scores, strict=True)]
        except Exception as e:
            raise RerankerError(f"cross-encoder scoring failed: {e}") from e
        if any(not math.isfinite(score) for _, score in scored):
            raise RerankerError("cross-encoder returned a non-finite score")

        ranked = sorted(
            enumerate(scored),
            key=lambda item: (-item[1][1], item[0]),
        )
        return [
            replace(hit, rerank_score=score, rerank_rank=rank)
            for rank, (_, (hit, score)) in enumerate(ranked, 1)
        ]
