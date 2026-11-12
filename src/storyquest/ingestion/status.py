"""Text views `ingest-status` and `entities` print."""

import sqlite3

from storyquest.config import Settings
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.ingestion.version import pipeline_version
from storyquest.stores.content_repo import BOOK_STEP, ContentRepo


def render_status(conn: sqlite3.Connection, settings: Settings, book_id: int) -> str:
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog")
    out = [
        f"Book {book.id}: {book.title}  status={book.status}",
        f"Pipeline version now: {pipeline_version(settings)}",
        "",
        "Beats by chapter (generated beats need review; flagged ones first):",
    ]
    for chapter in (c for c in repo.get_chapters(book_id) if c.included):
        beats = repo.get_beats(book_id, chapter.idx)
        approved = sum(b.review_status == "approved" for b in beats)
        flagged = sum(bool(b.flags) for b in beats)
        source = ", ".join(sorted({b.source for b in beats})) or "none"
        out.append(
            f"  ch{chapter.idx} {chapter.title:<28} {len(beats):>2} beats, {approved} approved, "
            f"{flagged} flagged  [{source}]"
        )
    steps = repo.list_steps(book_id)
    out += ["", "Steps:" if steps else "Steps: none recorded yet"]
    for s in steps:
        where = "book" if s["chapter_idx"] == BOOK_STEP else f"ch{s['chapter_idx']}"
        out.append(
            f"  {s['step']:<9} {where:<5} {s['status']:<6} {s['pipeline_version']}  "
            f"{s['updated_at']}  {s['detail'][:60]}"
        )
    jobs = repo.list_jobs(book_id)
    if jobs:
        out += ["", "Recent jobs:"]
        out += [
            f"  #{j['id']} {j['status']:<8} {j['created_at']}  {j['message'][:60]}" for j in jobs
        ]
    out += ["", f"Entities: {len(repo.get_entities(book_id))}"]
    return "\n".join(out)


def render_entities(conn: sqlite3.Connection, settings: Settings, book_id: int) -> str:
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog")
    cleaned = load_cleaned(settings.data_dir, book)
    entities = repo.get_entities(book_id)
    if not entities:
        return "No entity cards yet: run `make ingest-llm` (stage entities)."
    out = [f"{len(entities)} entity cards for {book.title}", ""]
    for e in entities:
        aka = f" (also {', '.join(e.aliases)})" if e.aliases else ""
        out.append(f"{e.name} [{e.kind}]{aka}  first at raw line {cleaned.line_at(e.first_char)}")
        out.append(f"    {e.card}")
    return "\n".join(out)
