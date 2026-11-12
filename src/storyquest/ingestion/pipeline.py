"""The deterministic ingestion stages: verify, clean, chapters, hand-written beats, chunks."""

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from storyquest.config import Settings
from storyquest.domain.book import Book, Chapter, Chunk
from storyquest.ingestion.chapters import detect_chapters
from storyquest.ingestion.chunking import chunk_span
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.names import find_names
from storyquest.ingestion.spine import load_spine
from storyquest.ingestion.text import Cleaned, clean
from storyquest.stores.content_repo import ContentRepo


@dataclass(frozen=True)
class IngestReport:
    chapters: int
    story_chapters: int
    beats: int
    chunks: int
    names: int


@dataclass(frozen=True)
class Prepared:
    book: Book
    cleaned: Cleaned
    chapters: list[Chapter]
    names: int

    @property
    def stories(self) -> list[Chapter]:
        return [c for c in self.chapters if c.included]


def load_cleaned(data_dir: Path, book: Book) -> Cleaned:
    """Read the stored raw file, check its hash against the book record, and clean it."""
    data = (data_dir / book.raw_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != book.content_sha256:
        raise IngestionError(f"{book.raw_path} does not match the hash recorded for book {book.id}")
    return clean(data.decode("utf-8-sig"))


def prepare(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    *,
    spine_path: Path | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> Prepared:
    """Stages 1 to 4 and the hand-written beats: verify, clean, chapters, names, spine."""
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog; run `catalog import` first")

    cleaned = load_cleaned(settings.data_dir, book)
    log(f"verify   hash ok for {book.raw_path}")
    log(
        f"clean    {len(cleaned.text):,} characters, raw lines {cleaned.first_line}"
        f"-{cleaned.line_at(len(cleaned.text) - 1)}"
    )

    chapters = detect_chapters(cleaned, short_chapter_chars=settings.short_chapter_chars)
    stories = [c for c in chapters if c.included]
    log(
        f"chapters {len(chapters)} found: {len(stories)} story, {len(chapters) - len(stories)} poem"
    )
    if repo.get_chapters(book_id) != chapters:
        repo.replace_chapters(book_id, chapters)
        log("         chapter list changed: stored chapters replaced (beats and chunks cleared)")

    names = find_names(cleaned.text, start=chapters[0].start_char if chapters else 0)
    repo.replace_names(book_id, names)
    log(f"names    {len(names)} proper names found, e.g. {', '.join(list(names)[:5])}")

    if spine_path is not None:
        chapter_idx, spine_beats = load_spine(spine_path, cleaned, chapters)
        repo.replace_beats(book_id, chapter_idx, spine_beats)
        log(f"beats    {len(spine_beats)} loaded from {spine_path.name} into chapter {chapter_idx}")
    return Prepared(book, cleaned, chapters, len(names))


def build_chunks(
    conn: sqlite3.Connection,
    settings: Settings,
    prepared: Prepared,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[int, int]:
    """Stage 9: cut every beat into chunks. Returns (beats, chunks). Changed chunks replace all
    chunks, and with them their embeddings, so run `embed` afterwards; identical chunks are left
    alone, embeddings included."""
    repo = ContentRepo(conn)
    cleaned = prepared.cleaned
    chunks: list[Chunk] = []
    total_beats = 0
    for chapter in prepared.stories:
        beats = repo.get_beats(prepared.book.id, chapter.idx)
        total_beats += len(beats)
        heading_end = cleaned.text.find("\n", chapter.start_char) + 1  # the title is not story text
        for beat in beats:
            spans = chunk_span(
                cleaned.text,
                max(beat.start_char, heading_end),
                beat.end_char,
                target=settings.chunk_target_chars,
                max_len=settings.chunk_max_chars,
            )
            chunks.extend(
                Chunk(chapter.idx, beat.idx, i, cleaned.text[a:b], a, b)
                for i, (a, b) in enumerate(spans)
            )
    if repo.get_all_chunks(prepared.book.id) == chunks:
        log(f"chunks   {len(chunks)} unchanged for {total_beats} beats; embeddings kept")
        return total_beats, len(chunks)
    repo.replace_chunks(prepared.book.id, chunks)
    log(f"chunks   {len(chunks)} written for {total_beats} beats (chapters with no beats skipped)")
    return total_beats, len(chunks)


def run_deterministic(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: int,
    *,
    spine_path: Path | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> IngestReport:
    prepared = prepare(conn, settings, book_id, spine_path=spine_path, log=log)
    beats, chunks = build_chunks(conn, settings, prepared, log)
    return IngestReport(
        len(prepared.chapters), len(prepared.stories), beats, chunks, prepared.names
    )
