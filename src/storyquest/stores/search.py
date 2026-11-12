"""Search over chunks: BM25 keywords, and hybrid keywords plus meaning. Spoiler filter included."""

import re
import sqlite3
from dataclasses import dataclass

from storyquest.domain.position import Position
from storyquest.stores.vector import dense_search

STOPWORDS = frozenset(
    "a an and are as at be but by did do does for from had has have he her him his how i if in is "
    "it its me my no not of on or our she so than that the their them then there they this to "
    "us was we were what when where which who why will with you your s t".split()
)


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    chapter_idx: int
    beat_idx: int
    idx: int
    text: str
    start_char: int
    end_char: int
    score: float  # higher is better
    bm25_rank: int | None = None  # 1-based rank in the keyword results (hybrid search only)
    dense_rank: int | None = None  # 1-based rank in the meaning results (hybrid search only)
    source: str = "chunk"  # "chunk" (book text) or "entity" (a card; offsets are -1)


def to_match_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 query of quoted terms joined by OR."""
    seen: dict[str, None] = {}
    for token in re.findall(r"\w+", text.lower()):
        if token not in STOPWORDS:
            seen[token] = None
    if not seen:
        return None
    return " OR ".join(f'"{t}"' for t in seen)


def search_chunks(
    conn: sqlite3.Connection,
    book_id: int,
    query: str,
    position: Position,
    *,
    limit: int = 5,
) -> list[SearchHit]:
    match = to_match_query(query)
    if match is None:
        return []
    rows = conn.execute(
        "SELECT c.id, c.chapter_idx, c.beat_idx, c.idx, c.text, c.start_char, c.end_char,"
        " -bm25(chunks_fts) AS score"
        " FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid"
        " WHERE chunks_fts MATCH :match AND c.book_id = :book"
        " AND (c.chapter_idx < :chapter OR (c.chapter_idx = :chapter AND c.beat_idx <= :beat))"
        " ORDER BY score DESC, c.id LIMIT :limit",
        {
            "match": match,
            "book": book_id,
            "chapter": position.chapter_idx,
            "beat": position.beat_idx,
            "limit": limit,
        },
    )
    return [SearchHit(*tuple(r)) for r in rows]


def rrf_fuse(rankings: list[list[int]], k: int) -> dict[int, float]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) to the chunks it contains."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _hits_by_id(conn: sqlite3.Connection, ids: list[int]) -> dict[int, SearchHit]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        "SELECT id, chapter_idx, beat_idx, idx, text, start_char, end_char, 0.0"
        f" FROM chunks WHERE id IN ({marks})",
        ids,
    )
    return {int(r[0]): SearchHit(*tuple(r)) for r in rows}


def hybrid_search(
    conn: sqlite3.Connection,
    book_id: int,
    query: str,
    query_vector: list[float],
    model_id: str,
    position: Position,
    *,
    limit: int,
    candidates: int,
    rrf_k: int,
) -> list[SearchHit]:
    """Keywords and meaning each propose `candidates` visible chunks; fusion picks the top."""
    keyword = search_chunks(conn, book_id, query, position, limit=candidates)
    meaning = dense_search(conn, book_id, query_vector, position, model_id, limit=candidates)
    bm25_rank = {h.chunk_id: n for n, h in enumerate(keyword, 1)}
    dense_rank = {chunk_id: n for n, (chunk_id, _) in enumerate(meaning, 1)}
    fused = rrf_fuse([[h.chunk_id for h in keyword], [c for c, _ in meaning]], rrf_k)
    best = sorted(fused, key=lambda c: (-fused[c], c))[:limit]
    known = {h.chunk_id: h for h in keyword}
    known.update(_hits_by_id(conn, [c for c in best if c not in known]))
    return [
        SearchHit(
            known[c].chunk_id,
            known[c].chapter_idx,
            known[c].beat_idx,
            known[c].idx,
            known[c].text,
            known[c].start_char,
            known[c].end_char,
            fused[c],
            bm25_rank.get(c),
            dense_rank.get(c),
        )
        for c in best
    ]
