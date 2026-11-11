"""BM25 search over chunks with the spoiler filter applied inside the query."""

import re
import sqlite3
from dataclasses import dataclass

from storyquest.domain.position import Position

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
