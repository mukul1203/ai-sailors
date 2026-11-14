"""Embedding vectors for the chunks that have none yet (hybrid search needs them)."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from storyquest.models.embedder import Embedder, EmbeddingError
from storyquest.stores.vector import chunks_without_vectors, store_vectors

EMBED_BATCH = 50


@dataclass(frozen=True)
class EmbedResult:
    done: int
    total: int  # chunks that needed a vector
    error: str = ""  # why it stopped early (for example the free quota ran out)


def embed_book(
    conn: sqlite3.Connection,
    embedder: Embedder,
    book_id: int,
    log: Callable[[str], None] = lambda _: None,
) -> EmbedResult:
    """Embed the book's chunks without a vector, earliest chapter first and stored batch by
    batch, so a stop (quota, network) keeps what was done and a re-run resumes."""
    todo = chunks_without_vectors(conn, book_id, embedder.model_id)
    done = 0
    for start in range(0, len(todo), EMBED_BATCH):
        part = todo[start : start + EMBED_BATCH]
        try:
            vectors = embedder.embed([text for _, text in part], query=False)
        except EmbeddingError as e:
            log(f"embed    stopped after {done} of {len(todo)} chunks: {e}")
            return EmbedResult(done, len(todo), str(e))
        store_vectors(
            conn,
            embedder.model_id,
            embedder.dim,
            [(cid, v) for (cid, _), v in zip(part, vectors, strict=True)],
        )
        done += len(part)
        log(f"embed    {done} of {len(todo)} chunks")
    return EmbedResult(done, len(todo))
