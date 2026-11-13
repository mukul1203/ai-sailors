"""The library: books found in BOOKS_DIR, their chapters, and preparing a chapter on demand.

A book appears as soon as its folder (raw.txt and book.yaml) is in BOOKS_DIR: listing the
library imports new folders and runs the model-free ingestion stages, so its chapters show at
once. A chapter becomes playable after the model stages have run for it; choosing "prepare"
queues that as an ingestion job, which a worker thread inside the API (or `make worker`) runs.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from storyquest.api.play import PlayError, chapter_beats
from storyquest.catalog.importer import scan_books
from storyquest.config import Settings
from storyquest.domain.book import Book, Chapter
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.run import LLM_STAGES, RunOptions, run_ingestion
from storyquest.ingestion.worker import options_to_json
from storyquest.stores.content_repo import ContentRepo

PLAYABLE, NOT_PREPARED, PREPARING, FAILED = "playable", "not_prepared", "preparing", "failed"


@dataclass(frozen=True)
class ChapterState:
    idx: int
    title: str
    state: str
    beats: int
    message: str = ""


def _jobs_for(repo: ContentRepo, book_id: int) -> dict[int, sqlite3.Row]:
    """The newest job per chapter for a book (jobs for the whole book are ignored here)."""
    newest: dict[int, sqlite3.Row] = {}
    for job in repo.list_jobs(book_id):  # newest first
        chapter = json.loads(job["options"]).get("chapter")
        if chapter is not None and chapter not in newest:
            newest[chapter] = job
    return newest


def _chapter_state(
    repo: ContentRepo,
    settings: Settings,
    book: Book,
    chapter: Chapter,
    jobs: dict[int, sqlite3.Row],
) -> ChapterState:
    beats = repo.get_beats(book.id, chapter.idx)
    if chapter_beats(repo, settings, book.id, chapter):
        return ChapterState(chapter.idx, chapter.title, PLAYABLE, len(beats))
    job = jobs.get(chapter.idx)
    if job is not None and job["status"] in ("queued", "running"):
        message = "Waiting for its turn..." if job["status"] == "queued" else job["message"]
        return ChapterState(chapter.idx, chapter.title, PREPARING, len(beats), message)
    if job is not None and job["status"] == "failed":
        return ChapterState(chapter.idx, chapter.title, FAILED, len(beats), job["message"])
    if job is not None and job["status"] == "done":
        why = "It finished, but the story is not complete yet: ask a grown-up to review it."
        return ChapterState(chapter.idx, chapter.title, FAILED, len(beats), why)
    return ChapterState(chapter.idx, chapter.title, NOT_PREPARED, len(beats))


def library(content: sqlite3.Connection, settings: Settings) -> list[dict[str, Any]]:
    """Every listed book with its story chapters and what state each is in."""
    scan_errors: list[str] = []
    for folder in settings.books_dirs:
        _, errors = scan_books(content, settings.data_dir, folder)
        scan_errors += errors
    repo = ContentRepo(content)
    out: list[dict[str, Any]] = []
    for book in repo.list_books():
        if book.visibility != "listed" and not settings.play_unpublished:
            continue
        entry: dict[str, Any] = {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "summary": book.summary,
            "content_notes": book.content_notes,
            "chapters": [],
            "error": "",
        }
        try:
            if not repo.get_chapters(book.id):  # first sight: the stages that need no model
                run_ingestion(content, settings, None, book.id, RunOptions())
        except IngestionError as e:
            entry["error"] = f"This book could not be read: {e}"
        jobs = _jobs_for(repo, book.id)
        entry["chapters"] = [
            _chapter_json(_chapter_state(repo, settings, book, c, jobs))
            for c in repo.get_chapters(book.id)
            if c.included
        ]
        out.append(entry)
    for message in scan_errors:  # a folder that could not be imported has no book row
        out.append({"id": None, "title": message.split(":")[0], "chapters": [], "error": message})
    return out


def _chapter_json(c: ChapterState) -> dict[str, Any]:
    return {
        "idx": c.idx,
        "title": c.title,
        "state": c.state,
        "beats": c.beats,
        "message": c.message,
    }


def prepare_chapter(
    content: sqlite3.Connection, settings: Settings, book_id: int, chapter_idx: int
) -> int:
    """Queue the model stages for one chapter. Asking twice returns the job already waiting."""
    repo = ContentRepo(content)
    book = repo.get_book(book_id)
    chapter = next((c for c in repo.get_chapters(book_id) if c.idx == chapter_idx), None)
    if book is None or chapter is None or not chapter.included:
        raise PlayError(404, "no_such_chapter", "That chapter is not in the library.")
    waiting = _jobs_for(repo, book_id).get(chapter_idx)
    if waiting is not None and waiting["status"] in ("queued", "running"):
        return int(waiting["id"])
    options = RunOptions(stages=LLM_STAGES, chapter=chapter_idx)
    return repo.enqueue_job(book_id, options_to_json(options))
