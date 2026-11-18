from pathlib import Path

import pytest

from storyquest.config import load_settings
from storyquest.models.build import build_reranker
from storyquest.models.reranker import CrossEncoderReranker, FakeReranker, RerankerError
from storyquest.stores.search import SearchHit


def hit(chunk_id: int, text: str) -> SearchHit:
    return SearchHit(chunk_id, 0, 0, chunk_id, text, 0, len(text), 0.0)


def test_fake_reranker_orders_query_matches_and_records_scores() -> None:
    hits = [hit(1, "Mowgli walks away"), hit(2, "Mowgli cries tears")]

    ranked = FakeReranker().rerank("tears Mowgli", hits)

    assert [item.chunk_id for item in ranked] == [2, 1]
    assert [item.rerank_rank for item in ranked] == [1, 2]
    assert [item.rerank_score for item in ranked] == [2.0, 1.0]


def test_cross_encoder_scores_query_passage_pairs_in_rank_order() -> None:
    class Model:
        def predict(
            self,
            sentences: list[list[str]],
            *,
            batch_size: int,
            convert_to_numpy: bool,
        ) -> list[float]:
            assert sentences == [["what happened", "first"], ["what happened", "second"]]
            assert batch_size == 32 and convert_to_numpy
            return [0.1, 0.9]

    reranker = CrossEncoderReranker("unused-model")
    reranker._model = Model()

    ranked = reranker.rerank("what happened", [hit(1, "first"), hit(2, "second")])

    assert [item.chunk_id for item in ranked] == [2, 1]
    assert [item.rerank_rank for item in ranked] == [1, 2]
    assert [item.rerank_score for item in ranked] == [0.9, 0.1]


def test_build_reranker_is_optional_and_provider_is_configured(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, environ={})
    assert build_reranker(settings) is None

    settings = load_settings(tmp_path, environ={"RERANKER_PROVIDER": "cross_encoder"})
    assert isinstance(build_reranker(settings), CrossEncoderReranker)

    settings = load_settings(tmp_path, environ={"RERANKER_PROVIDER": "unknown"})
    with pytest.raises(RerankerError, match="unknown RERANKER_PROVIDER"):
        build_reranker(settings)
