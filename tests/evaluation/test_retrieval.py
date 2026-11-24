from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.evaluation.items import load_items
from storyquest.evaluation.retrieval import measurable, render_recall, retrieval_recall
from storyquest.ingestion.embed import embed_book
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.models.embedder import FakeEmbedder
from storyquest.models.llm import LLMClient
from storyquest.models.reranker import FakeReranker

pytestmark = pytest.mark.integration

MakeCtx = Callable[[LLMClient], AgentContext]


def dev_items(eval_dir: Path):  # type: ignore[no-untyped-def]
    return [i for i in load_items(eval_dir / "golden_v1.jsonl") if i.split == "dev"]


def test_only_questions_with_gold_lines_are_scored(eval_dir: Path) -> None:
    items = measurable(dev_items(eval_dir))
    assert items and all(i.input.strip() and not i.skip for i in items)
    assert all(i.gold_lines or i.fact_lines for i in items)


def test_keyword_recall_needs_no_embedder_and_grows_with_k(
    make_ctx: MakeCtx, eval_dir: Path
) -> None:
    ctx = make_ctx(ScriptedLLM())
    cleaned = load_cleaned(ctx.settings.data_dir, ctx.book)
    rows = retrieval_recall(ctx, cleaned, dev_items(eval_dir), [6, 3, 10])
    assert {r.method for r in rows} == {"bm25"}
    assert [r.k for r in rows] == [3, 6, 10]
    found = [r.passages_found for r in rows]
    assert found == sorted(found) and rows[-1].passages_found <= rows[-1].passage_questions
    assert len({(r.passage_questions, r.facts) for r in rows}) == 1
    table = render_recall(rows, top_k=6, embedding=None)
    assert "@6 (agent)" in table and "need the embedding key" in table


def test_meaning_and_hybrid_run_once_the_book_has_vectors(
    make_ctx: MakeCtx, eval_dir: Path
) -> None:
    ctx = make_ctx(ScriptedLLM())
    fake = FakeEmbedder()
    cleaned = load_cleaned(ctx.settings.data_dir, ctx.book)
    without = retrieval_recall(replace(ctx, embedder=fake), cleaned, dev_items(eval_dir), [6])
    assert {r.method for r in without} == {"bm25"}  # no vectors stored yet
    embed_book(ctx.conn, fake, ctx.book.id)
    rows = retrieval_recall(replace(ctx, embedder=fake), cleaned, dev_items(eval_dir), [6])
    assert [r.method for r in rows] == ["bm25", "dense", "hybrid"]
    assert "fake:64" in render_recall(rows, top_k=6, embedding=fake.model_id)


def test_with_a_reranker_the_hybrid_pool_is_reranked_too(make_ctx: MakeCtx, eval_dir: Path) -> None:
    ctx = make_ctx(ScriptedLLM())
    fake = FakeEmbedder()
    embed_book(ctx.conn, fake, ctx.book.id)
    reranking = replace(ctx, embedder=fake, reranker=FakeReranker())
    cleaned = load_cleaned(ctx.settings.data_dir, ctx.book)
    rows = retrieval_recall(reranking, cleaned, dev_items(eval_dir), [3, 6])
    assert [r.method for r in rows if r.k == 6] == ["bm25", "dense", "hybrid", "rerank"]
    assert "rerank" in render_recall(rows, top_k=6, embedding=fake.model_id)
