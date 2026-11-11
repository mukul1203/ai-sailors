"""Reads and writes for content.db: books, chapters, beats and chunks."""

import json
import sqlite3
from typing import Any

from storyquest.domain.book import Beat, Book, Chapter, Chunk
from storyquest.stores.db import transaction


class ContentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # books

    def upsert_book(self, book: Book) -> None:
        """Insert or update metadata. An existing book keeps its status."""
        self._conn.execute(
            "INSERT INTO books (id, title, author, language, age_band, summary, content_notes,"
            " visibility, status, raw_path, content_sha256)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET title = excluded.title, author = excluded.author,"
            " language = excluded.language, age_band = excluded.age_band,"
            " summary = excluded.summary, content_notes = excluded.content_notes,"
            " visibility = excluded.visibility, raw_path = excluded.raw_path,"
            " content_sha256 = excluded.content_sha256, updated_at = CURRENT_TIMESTAMP",
            (
                book.id, book.title, book.author, book.language, book.age_band, book.summary,
                book.content_notes, book.visibility, book.status, book.raw_path,
                book.content_sha256,
            ),
        )  # fmt: skip

    def get_book(self, book_id: int) -> Book | None:
        row = self._conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return _book(row) if row else None

    def list_books(self, *, status: str | None = None) -> list[Book]:
        if status is None:
            rows = self._conn.execute("SELECT * FROM books ORDER BY title")
        else:
            rows = self._conn.execute(
                "SELECT * FROM books WHERE status = ? ORDER BY title", (status,)
            )
        return [_book(r) for r in rows]

    def set_book_status(self, book_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE books SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, book_id),
        )

    # chapters (replacing them also removes the book's beats and chunks)

    def replace_chapters(self, book_id: int, chapters: list[Chapter]) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            self._conn.executemany(
                "INSERT INTO chapters (book_id, idx, title, kind, included, start_char, end_char)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (book_id, c.idx, c.title, c.kind, int(c.included), c.start_char, c.end_char)
                    for c in chapters
                ],
            )

    def get_chapters(self, book_id: int) -> list[Chapter]:
        rows = self._conn.execute(
            "SELECT * FROM chapters WHERE book_id = ? ORDER BY idx", (book_id,)
        )
        return [
            Chapter(
                r["idx"], r["title"], r["kind"], r["start_char"], r["end_char"], bool(r["included"])
            )
            for r in rows
        ]

    # beats

    def replace_beats(self, book_id: int, chapter_idx: int, beats: list[Beat]) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM beats WHERE book_id = ? AND chapter_idx = ?", (book_id, chapter_idx)
            )
            self._conn.executemany(
                "INSERT INTO beats (book_id, chapter_idx, idx, title, narration, clues, vocabulary,"
                " choice, spoiler_reveals, start_char, end_char, review_status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        book_id, b.chapter_idx, b.idx, b.title, b.narration, json.dumps(b.clues),
                        json.dumps(b.vocabulary), json.dumps(b.choice),
                        json.dumps(b.spoiler_reveals), b.start_char, b.end_char, b.review_status,
                    )
                    for b in beats
                ],
            )  # fmt: skip

    def get_beats(self, book_id: int, chapter_idx: int) -> list[Beat]:
        rows = self._conn.execute(
            "SELECT * FROM beats WHERE book_id = ? AND chapter_idx = ? ORDER BY idx",
            (book_id, chapter_idx),
        )
        return [_beat(r) for r in rows]

    # chunks

    def replace_chunks(self, book_id: int, chunks: list[Chunk]) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            self._conn.executemany(
                "INSERT INTO chunks (book_id, chapter_idx, beat_idx, idx, text, start_char,"
                " end_char) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (book_id, c.chapter_idx, c.beat_idx, c.idx, c.text, c.start_char, c.end_char)
                    for c in chunks
                ],
            )

    def get_chunks(self, book_id: int, chapter_idx: int) -> list[Chunk]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE book_id = ? AND chapter_idx = ? ORDER BY beat_idx, idx",
            (book_id, chapter_idx),
        )
        return [
            Chunk(
                r["chapter_idx"], r["beat_idx"], r["idx"], r["text"], r["start_char"], r["end_char"]
            )
            for r in rows
        ]

    def count_chunks(self, book_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE book_id = ?", (book_id,)
        ).fetchone()
        return int(row[0])


def _book(r: sqlite3.Row) -> Book:
    return Book(
        id=r["id"], title=r["title"], author=r["author"], raw_path=r["raw_path"],
        content_sha256=r["content_sha256"], language=r["language"], age_band=r["age_band"],
        summary=r["summary"], content_notes=r["content_notes"], visibility=r["visibility"],
        status=r["status"],
    )  # fmt: skip


def _beat(r: sqlite3.Row) -> Beat:
    choice: dict[str, Any] = json.loads(r["choice"])
    return Beat(
        chapter_idx=r["chapter_idx"], idx=r["idx"], title=r["title"], narration=r["narration"],
        start_char=r["start_char"], end_char=r["end_char"], clues=json.loads(r["clues"]),
        vocabulary=json.loads(r["vocabulary"]), choice=choice,
        spoiler_reveals=json.loads(r["spoiler_reveals"]), review_status=r["review_status"],
    )  # fmt: skip
