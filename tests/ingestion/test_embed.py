from collections.abc import Callable
from pathlib import Path

import certifi
import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.config import load_settings
from storyquest.ingestion.embed import embed_book, with_scene_context
from storyquest.models.build import build_embedder
from storyquest.models.embedder import EmbeddingError, FakeEmbedder, SceneContextEmbedder
from storyquest.models.llm import LLMClient
from storyquest.stores.vector import book_chunks, chunks_without_vectors

pytestmark = pytest.mark.integration

MakeCtx = Callable[[LLMClient], AgentContext]


def middle_of_a_scene(rows: list[tuple[int, int, int, str]]) -> int:
    """Index of a chunk with a neighbour on both sides in its own beat."""
    return next(
        n for n in range(1, len(rows) - 1) if rows[n - 1][1:3] == rows[n][1:3] == rows[n + 1][1:3]
    )


def test_without_context_each_chunk_is_embedded_alone(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    todo = chunks_without_vectors(ctx.conn, ctx.book.id, "any:1")[:5]
    assert with_scene_context(ctx.conn, ctx.book.id, todo, 0) == [t for _, t in todo]


def test_context_adds_the_neighbours_ends_within_the_limit(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    rows = book_chunks(ctx.conn, ctx.book.id)
    n = middle_of_a_scene(rows)
    before, (cid, _, _, text), after = rows[n - 1][3], rows[n], rows[n + 1][3]
    [out] = with_scene_context(ctx.conn, ctx.book.id, [(cid, text)], len(text) + 200)
    assert out == f"{before[-100:]} {text} {after[:100]}"
    [alone] = with_scene_context(ctx.conn, ctx.book.id, [(cid, text)], len(text))
    assert alone == text  # no room left: the chunk itself is never cut


def test_context_never_crosses_into_another_scene(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    rows = book_chunks(ctx.conn, ctx.book.id)
    firsts = [n for n in range(1, len(rows)) if rows[n - 1][1:3] != rows[n][1:3]]
    for n in firsts:  # the first chunk of every beat after the first
        cid, _, _, text = rows[n]
        [out] = with_scene_context(ctx.conn, ctx.book.id, [(cid, text)], 5000)
        previous_scene = rows[n - 1][3]
        assert out.startswith(text) and previous_scene[-40:] not in out


def test_context_vectors_are_stored_apart_from_plain_ones(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    plain = FakeEmbedder()
    windowed = SceneContextEmbedder(FakeEmbedder(), 1200)
    assert windowed.model_id == "fake:64+ctx1200" and windowed.context_chars == 1200
    total = len(book_chunks(ctx.conn, ctx.book.id))
    assert embed_book(ctx.conn, plain, ctx.book.id).done == total
    # The plain vectors do not count for the windowed model: everything is embedded again.
    assert embed_book(ctx.conn, windowed, ctx.book.id).done == total
    assert chunks_without_vectors(ctx.conn, ctx.book.id, windowed.model_id) == []
    with pytest.raises(EmbeddingError, match="CONTEXT_CHARS"):
        SceneContextEmbedder(FakeEmbedder(), 0)


def test_the_setting_turns_scene_context_on(tmp_path: Path) -> None:
    cert = certifi.where()
    env = {
        "EMBEDDING_PROVIDER": "openai_compatible",
        "EMBEDDING_MODEL": "bge-small-en-v1.5",
        "EMBEDDING_DIM": "384",
        "EMBEDDING_BASE_URL": "https://h:1035/v1",
        "EMBEDDING_API_KEY": "k",
        "EMBEDDING_CA_CERT_PATH": cert,
    }
    plain = build_embedder(load_settings(tmp_path, environ=env))
    assert plain.context_chars == 0 and plain.model_id == "bge-small-en-v1.5:384"
    windowed = build_embedder(
        load_settings(tmp_path, environ={**env, "EMBEDDING_CONTEXT_CHARS": "1200"})
    )
    assert windowed.context_chars == 1200
    assert windowed.model_id == "bge-small-en-v1.5:384+ctx1200"
