"""Vectors for chunks: storing them, and meaning-based search with the spoiler filter."""

import sqlite3
from array import array

from storyquest.domain.position import Position


def pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def unpack(blob: bytes) -> array[float]:
    values: array[float] = array("f")
    values.frombytes(blob)
    return values


def has_vectors(conn: sqlite3.Connection, book_id: int, model_id: str) -> bool:
    """True if at least one of the book's chunks has a vector for this model."""
    row = conn.execute(
        "SELECT 1 FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id"
        " WHERE c.book_id = ? AND e.model_id = ? LIMIT 1",
        (book_id, model_id),
    ).fetchone()
    return row is not None


def chunks_without_vectors(
    conn: sqlite3.Connection, book_id: int, model_id: str
) -> list[tuple[int, str]]:
    """(chunk id, text) of the book's chunks that have no vector for this model yet."""
    rows = conn.execute(
        "SELECT c.id, c.text FROM chunks c WHERE c.book_id = :book AND NOT EXISTS ("
        " SELECT 1 FROM chunk_embeddings e WHERE e.chunk_id = c.id AND e.model_id = :model)"
        " ORDER BY c.chapter_idx, c.beat_idx, c.id",
        {"book": book_id, "model": model_id},
    )
    return [(int(r[0]), str(r[1])) for r in rows]


def store_vectors(
    conn: sqlite3.Connection, model_id: str, dim: int, rows: list[tuple[int, list[float]]]
) -> None:
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, model_id, dim, vector)"
            " VALUES (?, ?, ?, ?)",
            [(chunk_id, model_id, dim, pack(v)) for chunk_id, v in rows],
        )


def dense_search(
    conn: sqlite3.Connection,
    book_id: int,
    query_vector: list[float],
    position: Position,
    model_id: str,
    *,
    limit: int,
) -> list[tuple[int, float]]:
    """(chunk id, cosine) of the closest visible chunks, best first. Vectors are unit length."""
    rows = conn.execute(
        "SELECT c.id, e.vector FROM chunks c JOIN chunk_embeddings e ON e.chunk_id = c.id"
        " WHERE c.book_id = :book AND e.model_id = :model"
        " AND (c.chapter_idx < :chapter OR (c.chapter_idx = :chapter AND c.beat_idx <= :beat))",
        {
            "book": book_id,
            "model": model_id,
            "chapter": position.chapter_idx,
            "beat": position.beat_idx,
        },
    ).fetchall()
    query = array("f", query_vector)
    scored = [
        (int(chunk_id), sum(a * b for a, b in zip(query, unpack(blob), strict=True)))
        for chunk_id, blob in rows
    ]
    scored.sort(key=lambda s: (-s[1], s[0]))
    return scored[:limit]
