"""Embedding vectors for the chunks that have none yet (hybrid search needs them)."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from storyquest.models.embedder import Embedder, EmbeddingError
from storyquest.stores.vector import book_chunks, chunks_without_vectors, store_vectors

EMBED_BATCH = 50


@dataclass(frozen=True)
class EmbedResult:
    done: int
    total: int  # chunks that needed a vector
    error: str = ""  # why it stopped early (for example the free quota ran out)


def with_scene_context(
    conn: sqlite3.Connection, book_id: int, todo: list[tuple[int, str]], context_chars: int
) -> list[str]:
    """The text to embed for each chunk: the chunk, with the end of the chunk before it and the
    start of the chunk after it from the same beat, up to `context_chars` in all. A chunk longer
    than that, or with no neighbours in its beat, is embedded alone."""
    if context_chars <= 0:
        return [text for _, text in todo]
    rows = book_chunks(conn, book_id)
    where = {cid: n for n, (cid, _, _, _) in enumerate(rows)}

    def neighbour(n: int, m: int) -> str:
        """Chunk m's text if it is in the same beat as chunk n, else nothing."""
        return rows[m][3] if 0 <= m < len(rows) and rows[m][1:3] == rows[n][1:3] else ""

    out = []
    for cid, text in todo:
        n = where[cid]
        half = max(0, context_chars - len(text)) // 2
        before, after = neighbour(n, n - 1), neighbour(n, n + 1)
        parts = [before[len(before) - half :] if half else "", text, after[:half]]
        out.append(" ".join(p for p in parts if p))
    return out


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
            texts = with_scene_context(conn, book_id, part, embedder.context_chars)
            vectors = embedder.embed(texts, query=False)
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
