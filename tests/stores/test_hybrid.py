from collections.abc import Callable
from dataclasses import replace

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext, AgentError
from storyquest.agent.modes import describe_steps, get_mode
from storyquest.agent.retrieval import retrieve
from storyquest.agent.turn import run_turn
from storyquest.domain.position import Position
from storyquest.models.embedder import EmbeddingError, FakeEmbedder
from storyquest.models.llm import LLMClient
from storyquest.models.reranker import FakeReranker, RerankerError
from storyquest.stores.search import hybrid_search, rrf_fuse, search_chunks
from storyquest.stores.vector import (
    chunks_without_vectors,
    dense_search,
    pack,
    store_vectors,
    unpack,
)

pytestmark = pytest.mark.integration

MakeCtx = Callable[[LLMClient], AgentContext]
SYNONYMS = {"cry": "sob", "cried": "sob", "sobbed": "sob", "tears": "sob"}
START = Position(0, 0)


def embedded(
    make_ctx: MakeCtx, llm: LLMClient | None = None, embedder: FakeEmbedder | None = None
) -> tuple[AgentContext, FakeEmbedder]:
    """A context whose chunks all have vectors from `embedder` (a plain fake by default)."""
    ctx = make_ctx(llm or ScriptedLLM())
    fake = embedder or FakeEmbedder(synonyms=SYNONYMS)
    todo = chunks_without_vectors(ctx.conn, ctx.book.id, fake.model_id)
    vectors = fake.embed([text for _, text in todo], query=False)
    rows = [(c, v) for (c, _), v in zip(todo, vectors, strict=True)]
    store_vectors(ctx.conn, fake.model_id, fake.dim, rows)
    return replace(ctx, embedder=fake), fake


class MeaningEmbedder(FakeEmbedder):
    """Puts the question and the passage about tears at the same point, everything else apart."""

    def _vector(self, text: str) -> list[float]:
        close = "tears such as men use" in text or text == "Why did Mowgli cry?"
        return [1.0, 0.0] if close else [0.0, 1.0]

    def __init__(self) -> None:
        super().__init__(dim=2)


def test_vectors_round_trip_and_are_only_stored_once(make_ctx: MakeCtx) -> None:
    assert list(unpack(pack([0.5, -0.25]))) == [0.5, -0.25]
    ctx, fake = embedded(make_ctx)
    assert chunks_without_vectors(ctx.conn, ctx.book.id, fake.model_id) == []
    assert chunks_without_vectors(ctx.conn, ctx.book.id, "another-model:8")  # per model


def test_search_by_meaning_never_returns_chunks_the_child_has_not_reached(
    make_ctx: MakeCtx,
) -> None:
    ctx, fake = embedded(make_ctx)
    vector = fake.embed(["Who is Kaa the python?"], query=True)[0]
    hits = dense_search(ctx.conn, ctx.book.id, vector, START, fake.model_id, limit=50)
    assert hits
    chunk_beats = {
        r[0]: (r[1], r[2]) for r in ctx.conn.execute("SELECT id, chapter_idx, beat_idx FROM chunks")
    }
    assert all(chunk_beats[c] == (0, 0) for c, _ in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    scores = rrf_fuse([[1, 2, 3], [2, 4]], k=60)
    assert max(scores, key=lambda c: scores[c]) == 2
    assert scores[2] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[1] == pytest.approx(1 / 61) and scores[4] == pytest.approx(1 / 62)


def test_meaning_finds_the_passage_that_keywords_miss(make_ctx: MakeCtx) -> None:
    ctx, fake = embedded(make_ctx, embedder=MeaningEmbedder())
    question, at = "Why did Mowgli cry?", Position(0, 4)
    target = ctx.conn.execute(
        "SELECT id FROM chunks WHERE text LIKE '%tears such as men use%'"
    ).fetchone()[0]

    keywords = search_chunks(ctx.conn, ctx.book.id, question, at, limit=3)
    assert target not in [h.chunk_id for h in keywords]  # the book says "tears", not "cry"

    vector = fake.embed([question], query=True)[0]
    hybrid = hybrid_search(
        ctx.conn, ctx.book.id, question, vector, fake.model_id, at, limit=3, candidates=20, rrf_k=60
    )
    assert hybrid[0].chunk_id == target  # keywords ranked it low, meaning ranked it first
    assert hybrid[0].dense_rank == 1 and (hybrid[0].bm25_rank or 99) > 3
    assert [h.score for h in hybrid] == sorted((h.score for h in hybrid), reverse=True)


def test_hybrid_still_respects_the_spoiler_filter(make_ctx: MakeCtx) -> None:
    ctx, fake = embedded(make_ctx)
    vector = fake.embed(["Why did Mowgli cry?"], query=True)[0]
    hits = hybrid_search(
        ctx.conn, ctx.book.id, "Why did Mowgli cry?", vector, fake.model_id, START,
        limit=3, candidates=20, rrf_k=60,
    )  # fmt: skip
    assert hits and all((h.chapter_idx, h.beat_idx) == (0, 0) for h in hits)


def test_m2_gives_the_model_hybrid_passages(make_ctx: MakeCtx) -> None:
    ctx, _ = embedded(make_ctx, ScriptedLLM(answer="He is lame."))
    result = run_turn(ctx, "Why does Shere Khan limp?", START, mode=get_mode("M2"))
    assert result.reply == "He is lame." and result.flags == []
    assert result.passages and all(p.dense_rank is not None for p in result.passages)


def test_m4_reranks_candidate_pool_before_trimming_to_top_k(make_ctx: MakeCtx) -> None:
    ctx, _ = embedded(make_ctx)
    ctx = replace(ctx, reranker=FakeReranker())

    hits, flags = retrieve(ctx, get_mode("M4"), "Why did Mowgli cry?", Position(0, 4))

    chunks = [hit for hit in hits if hit.source == "chunk"]
    assert flags == []
    assert len(chunks) == ctx.settings.retrieval_top_k
    assert all(hit.rerank_rank is not None and hit.rerank_score is not None for hit in chunks)
    assert all((hit.chapter_idx, hit.beat_idx) <= (0, 4) for hit in chunks)


def test_reranker_failure_keeps_hybrid_order_and_sets_flag(make_ctx: MakeCtx) -> None:
    class BrokenReranker:
        model_id = "broken"

        def rerank(self, query: str, passages):
            raise RerankerError("model unavailable")

    ctx, _ = embedded(make_ctx)
    ctx = replace(ctx, reranker=BrokenReranker())

    hits, flags = retrieve(ctx, get_mode("M4"), "Why did Mowgli cry?", Position(0, 4))

    assert hits
    assert flags == ["reranker_error:model unavailable"]
    assert len([hit for hit in hits if hit.source == "chunk"]) == ctx.settings.retrieval_top_k


def test_a_hybrid_mode_without_an_embedder_is_an_error(make_ctx: MakeCtx) -> None:
    with pytest.raises(AgentError, match="embedder"):
        run_turn(make_ctx(ScriptedLLM()), "Who is Tabaqui?", START, mode=get_mode("M2"))


class BrokenEmbedder(FakeEmbedder):
    def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
        raise EmbeddingError("quota exceeded")


def test_if_embedding_fails_the_turn_falls_back_to_keywords(make_ctx: MakeCtx) -> None:
    ctx = replace(make_ctx(ScriptedLLM(answer="He is lame.")), embedder=BrokenEmbedder())
    result = run_turn(ctx, "Why does Shere Khan limp?", START, mode=get_mode("M2"))
    assert result.reply == "He is lame." and result.passages
    assert result.flags == ["embedding_error:quota exceeded"]
    assert all(p.dense_rank is None for p in result.passages)


def test_without_vectors_hybrid_falls_back_to_keywords_and_says_so(make_ctx: MakeCtx) -> None:
    ctx = replace(make_ctx(ScriptedLLM(answer="He is lame.")), embedder=FakeEmbedder())
    result = run_turn(ctx, "Why does Shere Khan limp?", START, mode=get_mode("M2"))
    assert result.reply == "He is lame." and result.passages
    assert len(result.flags) == 1 and result.flags[0].startswith("no_vectors")
    assert all(p.dense_rank is None for p in result.passages)


def test_the_modes_describe_how_they_search() -> None:
    assert "reciprocal rank fusion" in " ".join(describe_steps(get_mode("M2"), 3))
    assert "reciprocal rank fusion" not in " ".join(describe_steps(get_mode("M1"), 3))
    assert get_mode("M2S").hybrid and get_mode("M2S").grounded and not get_mode("M1S").hybrid


def test_retrieval_diagnostics_use_the_modes_own_search(make_ctx: MakeCtx, eval_dir) -> None:  # type: ignore[no-untyped-def]
    from storyquest.evaluation.items import load_items
    from storyquest.evaluation.runner import run_eval

    ctx, _ = embedded(make_ctx, ScriptedLLM(answer="He is lame."))
    items = [i for i in load_items(eval_dir / "golden_v1.jsonl") if i.id == "CAN-003"]
    [row] = run_eval(ctx, items, get_mode("M2"), log=lambda _: None)
    assert row["passages"] and row["passages"][0]["dense_rank"] is not None
    assert row["fact_found"] is not None
