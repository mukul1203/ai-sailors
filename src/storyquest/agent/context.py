import sqlite3
from dataclasses import dataclass

from storyquest.config import Settings
from storyquest.domain.book import Beat, Book, Chapter
from storyquest.domain.position import Position
from storyquest.models.llm import LLMClient
from storyquest.stores.content_repo import ContentRepo


class AgentError(Exception):
    pass


@dataclass(frozen=True)
class Where:
    """What the child has reached, in words, and the text offset where that part ends."""

    chapter_title: str
    beat_title: str
    boundary: int


@dataclass(frozen=True)
class AgentContext:
    conn: sqlite3.Connection
    llm: LLMClient
    settings: Settings
    book: Book
    chapters: list[Chapter]
    beats: dict[int, list[Beat]]
    names: dict[str, int]

    def where(self, position: Position) -> Where:
        chapter = next((c for c in self.chapters if c.idx == position.chapter_idx), None)
        if chapter is None:  # beyond the last chapter: the child has finished the book
            end = self.chapters[-1].end_char if self.chapters else 0
            return Where("the end of the book", "", end)
        beat = next(
            (b for b in self.beats.get(chapter.idx, []) if b.idx == position.beat_idx), None
        )
        if beat is None:
            return Where(chapter.title, "", chapter.end_char)
        return Where(chapter.title, beat.title, beat.end_char)


def load_context(
    conn: sqlite3.Connection, llm: LLMClient, settings: Settings, book_id: int
) -> AgentContext:
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise AgentError(f"Book {book_id} is not in the catalog; run `make seed` first")
    chapters = repo.get_chapters(book_id)
    if not chapters:
        raise AgentError(f"Book {book_id} has not been ingested; run `make ingest` first")
    beats = {c.idx: repo.get_beats(book_id, c.idx) for c in chapters if c.included}
    return AgentContext(conn, llm, settings, book, chapters, beats, repo.get_names(book_id))
