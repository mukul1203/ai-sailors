"""Reads and writes for content.db: books, chapters, beats and chunks."""

import json
import sqlite3
from typing import Any

from storyquest.domain.book import Beat, Book, Chapter, Chunk, Entity
from storyquest.stores.db import transaction

BOOK_STEP = -1  # chapter index used for steps that concern the whole book


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

    # chapters (replacing them also removes the book's beats, chunks, entities and steps)

    def replace_chapters(self, book_id: int, chapters: list[Chapter]) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
            self._conn.execute("DELETE FROM entities WHERE book_id = ?", (book_id,))
            self._conn.execute("DELETE FROM ingestion_steps WHERE book_id = ?", (book_id,))
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
                " choice, spoiler_reveals, start_char, end_char, review_status, source,"
                " clue_quotes, flags, pipeline_version)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        book_id, b.chapter_idx, b.idx, b.title, b.narration, json.dumps(b.clues),
                        json.dumps(b.vocabulary), json.dumps(b.choice),
                        json.dumps(b.spoiler_reveals), b.start_char, b.end_char, b.review_status,
                        b.source, json.dumps(b.clue_quotes), json.dumps(b.flags),
                        b.pipeline_version,
                    )
                    for b in beats
                ],
            )  # fmt: skip

    def update_beat(self, book_id: int, beat: Beat) -> None:
        """Rewrite the content of one existing beat (not its position)."""
        self._conn.execute(
            "UPDATE beats SET title = ?, narration = ?, clues = ?, vocabulary = ?, choice = ?,"
            " spoiler_reveals = ?, review_status = ?, clue_quotes = ?, flags = ?,"
            " pipeline_version = ? WHERE book_id = ? AND chapter_idx = ? AND idx = ?",
            (
                beat.title, beat.narration, json.dumps(beat.clues), json.dumps(beat.vocabulary),
                json.dumps(beat.choice), json.dumps(beat.spoiler_reveals), beat.review_status,
                json.dumps(beat.clue_quotes), json.dumps(beat.flags), beat.pipeline_version,
                book_id, beat.chapter_idx, beat.idx,
            ),
        )  # fmt: skip

    def get_beats(self, book_id: int, chapter_idx: int) -> list[Beat]:
        rows = self._conn.execute(
            "SELECT * FROM beats WHERE book_id = ? AND chapter_idx = ? ORDER BY idx",
            (book_id, chapter_idx),
        )
        return [_beat(r) for r in rows]

    # entities

    def replace_entities_from_chapter(
        self, book_id: int, chapter_idx: int, entities: list[Entity]
    ) -> None:
        """Drop the cards written from this chapter, then add the given ones."""
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM entities WHERE book_id = ? AND card_chapter = ?",
                (book_id, chapter_idx),
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO entities (book_id, key, name, kind, aliases, card,"
                " first_char, card_chapter, card_beat) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        book_id, e.key, e.name, e.kind, json.dumps(e.aliases), e.card,
                        e.first_char, e.card_chapter, e.card_beat,
                    )
                    for e in entities
                ],
            )  # fmt: skip

    def update_entity_aliases(self, book_id: int, key: str, aliases: list[str]) -> None:
        self._conn.execute(
            "UPDATE entities SET aliases = ? WHERE book_id = ? AND key = ?",
            (json.dumps(aliases), book_id, key),
        )

    def get_entities(self, book_id: int) -> list[Entity]:
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE book_id = ? ORDER BY first_char", (book_id,)
        )
        return [
            Entity(
                key=r["key"], name=r["name"], kind=r["kind"], card=r["card"],
                first_char=r["first_char"], aliases=json.loads(r["aliases"]),
                card_chapter=r["card_chapter"], card_beat=r["card_beat"],
            )
            for r in rows
        ]  # fmt: skip

    # steps (what the pipeline has finished, so a rerun can skip it)

    def get_step(self, book_id: int, chapter_idx: int, step: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT * FROM ingestion_steps WHERE book_id = ? AND chapter_idx = ? AND step = ?",
            (book_id, chapter_idx, step),
        ).fetchone()
        return row

    def record_step(
        self,
        book_id: int,
        chapter_idx: int,
        step: str,
        *,
        pipeline_version: str,
        input_hash: str,
        status: str,
        detail: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT INTO ingestion_steps (book_id, chapter_idx, step, pipeline_version,"
            " input_hash, status, detail) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (book_id, chapter_idx, step) DO UPDATE SET"
            " pipeline_version = excluded.pipeline_version, input_hash = excluded.input_hash,"
            " status = excluded.status, detail = excluded.detail,"
            " updated_at = CURRENT_TIMESTAMP",
            (book_id, chapter_idx, step, pipeline_version, input_hash, status, detail),
        )

    def list_steps(self, book_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM ingestion_steps WHERE book_id = ? ORDER BY chapter_idx, step",
            (book_id,),
        ).fetchall()

    # jobs (queued ingestion runs for the worker)

    def enqueue_job(self, book_id: int, options: dict[str, Any]) -> int:
        cur = self._conn.execute(
            "INSERT INTO ingestion_jobs (book_id, options) VALUES (?, ?)",
            (book_id, json.dumps(options)),
        )
        return int(cur.lastrowid or 0)

    def claim_job(self) -> sqlite3.Row | None:
        """Take the oldest queued job and mark it running, or None if there is none."""
        with transaction(self._conn):
            row: sqlite3.Row | None = self._conn.execute(
                "SELECT * FROM ingestion_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "UPDATE ingestion_jobs SET status = 'running', started_at = CURRENT_TIMESTAMP"
                " WHERE id = ?",
                (row["id"],),
            )
        return row

    def finish_job(self, job_id: int, status: str, message: str = "") -> None:
        self._conn.execute(
            "UPDATE ingestion_jobs SET status = ?, message = ?, finished_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (status, message, job_id),
        )

    def list_jobs(self, book_id: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM ingestion_jobs WHERE book_id = ? ORDER BY id DESC LIMIT 10", (book_id,)
        ).fetchall()

    # names

    def replace_names(self, book_id: int, names: dict[str, int]) -> None:
        with transaction(self._conn):
            self._conn.execute("DELETE FROM names WHERE book_id = ?", (book_id,))
            self._conn.executemany(
                "INSERT INTO names (book_id, name, first_char) VALUES (?, ?, ?)",
                [(book_id, name, offset) for name, offset in names.items()],
            )

    def get_names(self, book_id: int) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT name, first_char FROM names WHERE book_id = ?", (book_id,)
        )
        return {r["name"]: r["first_char"] for r in rows}

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
        source=r["source"], clue_quotes=json.loads(r["clue_quotes"]),
        flags=json.loads(r["flags"]), pipeline_version=r["pipeline_version"],
    )  # fmt: skip
