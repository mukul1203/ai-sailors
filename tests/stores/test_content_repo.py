import dataclasses
import sqlite3

import pytest
from store_helpers import add_book_with_chapters, make_book

from storyquest.domain.book import Beat, Chunk
from storyquest.stores.content_repo import ContentRepo

pytestmark = pytest.mark.integration


def test_book_round_trip_and_upsert_keeps_status(repo: ContentRepo) -> None:
    repo.upsert_book(make_book())
    repo.set_book_status(236, "ready")
    repo.upsert_book(dataclasses.replace(make_book(), title="Renamed"))
    book = repo.get_book(236)
    assert book is not None
    assert (book.title, book.status) == ("Renamed", "ready")
    assert repo.get_book(999) is None


def test_list_books_filters_by_status(repo: ContentRepo) -> None:
    repo.upsert_book(make_book(1, "B"))
    repo.upsert_book(make_book(2, "A"))
    repo.set_book_status(2, "ready")
    assert [b.id for b in repo.list_books()] == [2, 1]
    assert [b.id for b in repo.list_books(status="ready")] == [2]


def test_invalid_status_is_rejected(repo: ContentRepo) -> None:
    repo.upsert_book(make_book())
    with pytest.raises(sqlite3.IntegrityError):
        repo.set_book_status(236, "bogus")


def test_beats_round_trip_json_fields(repo: ContentRepo) -> None:
    add_book_with_chapters(repo)
    beat = Beat(
        0, 0, "A Warning", "Narration", 10, 99, clues=["c1"], vocabulary=["jackal"],
        choice={"prompt": "?", "cards": [{"id": "a", "next": "B2"}]}, spoiler_reveals=["Mowgli"],
    )  # fmt: skip
    repo.replace_beats(236, 0, [beat])
    assert repo.get_beats(236, 0) == [beat]
    repo.replace_beats(236, 0, [])
    assert repo.get_beats(236, 0) == []


def test_replacing_chapters_removes_beats_and_chunks(
    repo: ContentRepo, conn: sqlite3.Connection
) -> None:
    add_book_with_chapters(repo)
    repo.replace_beats(236, 0, [Beat(0, 0, "t", "n", 0, 5)])
    repo.replace_chunks(236, [Chunk(0, 0, 0, "wolf cave", 0, 9)])
    add_book_with_chapters(repo)
    assert repo.get_beats(236, 0) == []
    assert repo.count_chunks(236) == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'wolf'").fetchone()[0]
        == 0
    )


def test_replace_chunks_replaces_only_that_books_chunks(repo: ContentRepo) -> None:
    add_book_with_chapters(repo, 1)
    add_book_with_chapters(repo, 2)
    repo.replace_chunks(1, [Chunk(0, 0, 0, "a", 0, 1), Chunk(0, 0, 1, "b", 1, 2)])
    repo.replace_chunks(2, [Chunk(0, 0, 0, "c", 0, 1)])
    repo.replace_chunks(1, [Chunk(0, 0, 0, "d", 0, 1)])
    assert (repo.count_chunks(1), repo.count_chunks(2)) == (1, 1)
