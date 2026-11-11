import itertools
import sqlite3

import pytest
from store_helpers import add_book_with_chapters

from storyquest.domain.book import Chunk
from storyquest.domain.position import Position
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.search import search_chunks, to_match_query

pytestmark = pytest.mark.integration


def seed(repo: ContentRepo) -> None:
    """Chapter 0 has beats 0..2, chapter 1 has beats 0..1; every chunk mentions 'tiger'."""
    add_book_with_chapters(repo, 236, chapters=2)
    coords = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)]
    repo.replace_chunks(
        236,
        [Chunk(c, b, 0, f"the tiger limps in c{c}b{b}", 0, 10) for c, b in coords],
    )


def found(conn: sqlite3.Connection, position: Position, book_id: int = 236) -> set[tuple[int, int]]:
    hits = search_chunks(conn, book_id, "tiger", position, limit=50)
    return {(h.chapter_idx, h.beat_idx) for h in hits}


def test_spoiler_filter_hides_everything_after_the_position(
    repo: ContentRepo, conn: sqlite3.Connection
) -> None:
    seed(repo)
    assert found(conn, Position(0, 1)) == {(0, 0), (0, 1)}
    assert found(conn, Position(1, 0)) == {(0, 0), (0, 1), (0, 2), (1, 0)}
    assert found(conn, Position(0, 0)) == {(0, 0)}


def test_sql_filter_agrees_with_position_can_see(
    repo: ContentRepo, conn: sqlite3.Connection
) -> None:
    seed(repo)
    coords = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)]
    for pc, pb in itertools.product(range(3), range(4)):
        position = Position(pc, pb)
        expected = {(c, b) for c, b in coords if position.can_see(c, b)}
        assert found(conn, position) == expected


def test_search_never_crosses_books(repo: ContentRepo, conn: sqlite3.Connection) -> None:
    seed(repo)
    add_book_with_chapters(repo, 5)
    repo.replace_chunks(5, [Chunk(0, 0, 0, "another tiger story", 0, 5)])
    assert found(conn, Position(9, 9), book_id=5) == {(0, 0)}
    assert len(search_chunks(conn, 236, "tiger", Position(9, 9), limit=50)) == 5


def test_ranks_by_relevance_and_stems(repo: ContentRepo, conn: sqlite3.Connection) -> None:
    add_book_with_chapters(repo, 236, chapters=1)
    repo.replace_chunks(
        236,
        [
            Chunk(0, 0, 0, "Mowgli ate honey and slept.", 0, 5),
            Chunk(
                0,
                0,
                1,
                "Shere Khan was lame, and limped through the jungle. He limped again.",
                5,
                9,
            ),
            Chunk(0, 0, 2, "Akela led the pack.", 9, 12),
        ],
    )
    hits = search_chunks(conn, 236, "Why does Shere Khan limp?", Position(0, 0))
    assert [h.idx for h in hits] == [1]
    assert hits[0].score > 0


def test_punctuation_and_stopword_only_queries_are_safe(
    repo: ContentRepo, conn: sqlite3.Connection
) -> None:
    seed(repo)
    assert search_chunks(conn, 236, "", Position(9, 9)) == []
    assert search_chunks(conn, 236, "what is the?", Position(9, 9)) == []
    assert search_chunks(conn, 236, 'tiger" OR (NEAR* -', Position(9, 9))


def test_to_match_query() -> None:
    assert to_match_query("Who is Tabaqui?") == '"tabaqui"'
    assert to_match_query("man's cub, man's cub") == '"man" OR "cub"'
    assert to_match_query("?!") is None
