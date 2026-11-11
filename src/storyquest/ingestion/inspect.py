"""Text views of what ingestion produced, for humans."""

import sqlite3
from pathlib import Path

from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.ingestion.text import Cleaned
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.search import SearchHit


def _lines(cleaned: Cleaned, start: int, end: int) -> str:
    return f"{cleaned.line_at(start)}-{cleaned.line_at(max(start, end - 1))}"


def _preview(text: str, width: int = 70) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def render_book(
    conn: sqlite3.Connection, data_dir: Path, book_id: int, chapter_idx: int | None = None
) -> str:
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog")
    cleaned = load_cleaned(data_dir, book)
    chapters = repo.get_chapters(book_id)

    out = [f"Book {book.id}: {book.title} ({book.author}) status={book.status}", ""]
    out.append(" idx kind  used raw lines     chars  beats chunks  title")
    for c in chapters:
        beats = repo.get_beats(book_id, c.idx)
        chunks = repo.get_chunks(book_id, c.idx)
        out.append(
            f"{c.idx:4d} {c.kind:<5} {'yes' if c.included else 'no':<4} "
            f"{_lines(cleaned, c.start_char, c.end_char):<10} {c.end_char - c.start_char:>8} "
            f"{len(beats):>6} {len(chunks):>6}  {c.title}"
        )

    if chapter_idx is not None:
        chapter = next((c for c in chapters if c.idx == chapter_idx), None)
        if chapter is None:
            raise IngestionError(f"No chapter {chapter_idx}")
        out += ["", f"Chapter {chapter.idx}: {chapter.title}", "", "Beats:"]
        for b in repo.get_beats(book_id, chapter_idx):
            out.append(
                f"  B{b.idx + 1}  raw lines {_lines(cleaned, b.start_char, b.end_char):<9} "
                f"{b.end_char - b.start_char:>6} chars  {b.title}"
            )
        chapter_chunks = repo.get_chunks(book_id, chapter_idx)
        out += ["", f"Chunks ({len(chapter_chunks)}):"]
        for k in chapter_chunks:
            where = _lines(cleaned, k.start_char, k.end_char)
            out.append(
                f"  B{k.beat_idx + 1}.{k.idx}  raw lines {where:<9}"
                f" {k.end_char - k.start_char:>5} chars  {_preview(k.text)}"
            )
    return "\n".join(out)


def render_hits(cleaned: Cleaned, hits: list[SearchHit]) -> str:
    if not hits:
        return "No results."
    return "\n".join(
        f"{h.score:6.2f}  ch{h.chapter_idx} B{h.beat_idx + 1}.{h.idx}  raw lines "
        f"{_lines(cleaned, h.start_char, h.end_char):<9} {_preview(h.text, 90)}"
        for h in hits
    )
