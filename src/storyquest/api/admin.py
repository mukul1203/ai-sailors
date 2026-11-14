"""Grown-up workflows: add a book, review what the model wrote, publish.

There is no sign-in yet; the routes that call these are the ones to gate later.
"""

import re
import shutil
import sqlite3
from typing import Any

import yaml

from storyquest.api.play import PlayError
from storyquest.catalog.importer import CatalogError, import_book
from storyquest.config import Settings
from storyquest.ingestion.embed import embed_book
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.review import approve_beats, publish, publish_problems
from storyquest.models.embedder import Embedder
from storyquest.stores.content_repo import ContentRepo

MAX_BOOK_CHARS = 4_000_000


def add_book(
    content: sqlite3.Connection,
    settings: Settings,
    *,
    gutenberg_id: int,
    title: str,
    author: str,
    summary: str,
    content_notes: str,
    text: str,
) -> dict[str, Any]:
    """Save an uploaded Project Gutenberg text as a book folder, where the library finds it."""
    if "*** START OF" not in text or "*** END OF" not in text:
        raise PlayError(422, "bad_book", "This does not look like a Project Gutenberg text file.")
    if not settings.books_dirs:
        raise PlayError(503, "not_ready", "No books folder is set up (BOOKS_DIR).")
    root = settings.books_dirs[0]
    taken = ContentRepo(content).get_book(gutenberg_id) is not None
    if taken or any(root.glob(f"{gutenberg_id}-*")):
        raise PlayError(409, "book_exists", f"Book {gutenberg_id} is already in the library.")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "book"
    folder = root / f"{gutenberg_id}-{slug}"
    meta = {
        "gutenberg_id": gutenberg_id,
        "title": title,
        "author": author,
        "summary": summary,
        "content_notes": content_notes,
    }
    folder.mkdir(parents=True)
    try:
        (folder / "raw.txt").write_text(text, encoding="utf-8")
        (folder / "book.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True))
        book = import_book(ContentRepo(content), settings.data_dir, folder)
    except (CatalogError, OSError) as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise PlayError(422, "bad_book", str(e)) from e
    return {"id": book.id, "title": book.title}


def review_view(content: sqlite3.Connection, book_id: int) -> dict[str, Any]:
    """Everything a reviewer reads: each story chapter's beats with flags and the question."""
    repo = ContentRepo(content)
    book = repo.get_book(book_id)
    if book is None:
        raise PlayError(404, "no_such_book", "That book is not in the library.")
    chapters = []
    for chapter in repo.get_chapters(book_id):
        if not chapter.included:
            continue
        beats = []
        for b in repo.get_beats(book_id, chapter.idx):
            choice = b.choice or {}
            beats.append(
                {
                    "idx": b.idx,
                    "title": b.title,
                    "status": b.review_status,
                    "source": b.source,
                    "flags": b.flags,
                    "narration": b.narration,
                    "question": choice.get("prompt", ""),
                    "cards": [
                        {"text": c.get("text", ""), "right": bool(c.get("canon"))}
                        for c in choice.get("cards", [])
                    ],
                    "hints": choice.get("hints", []),
                }
            )
        chapters.append({"idx": chapter.idx, "title": chapter.title, "beats": beats})
    return {
        "id": book.id,
        "title": book.title,
        "status": book.status,
        "chapters": chapters,
        "problems": publish_problems(content, book_id) if book.status != "ready" else [],
    }


def approve(
    content: sqlite3.Connection,
    book_id: int,
    *,
    chapter_idx: int | None,
    beat_idx: int | None,
    include_flagged: bool,
) -> dict[str, int]:
    try:
        result = approve_beats(
            content,
            book_id,
            chapter_idx=chapter_idx,
            beat_idx=beat_idx,
            include_flagged=include_flagged,
        )
    except IngestionError as e:
        raise PlayError(404, "no_such_chapter", str(e)) from e
    return {
        "approved": result.approved,
        "flagged_left": result.flagged_left,
        "empty_left": result.empty_left,
    }


def publish_book(
    content: sqlite3.Connection, book_id: int, embedder: Embedder | None = None
) -> dict[str, Any]:
    """Publish a fully approved book and, now that its chunks are final, embed them once. If the
    embedding stops (the free quota), the book is still published and `embedding_error` says why."""
    try:
        problems = publish(content, book_id)
    except IngestionError as e:
        raise PlayError(404, "no_such_book", str(e)) from e
    out: dict[str, Any] = {"published": not problems, "problems": problems, "embedding_error": ""}
    if not problems and embedder is not None:
        out["embedding_error"] = embed_book(content, embedder, book_id).error
    return out
