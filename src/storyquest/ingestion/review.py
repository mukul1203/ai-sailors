"""Stages 10 and 11: a human reviews generated beats, then the book is published.

Hand-written (spine) beats start out approved. Generated beats start as drafts; those with
validation flags are listed first and are never approved in bulk.
"""

import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

from storyquest.domain.book import Beat, Chapter
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.stores.content_repo import ContentRepo


@dataclass(frozen=True)
class ApproveResult:
    approved: int
    flagged_left: int  # drafts with flags that were not approved
    empty_left: int  # drafts with no generated content yet


def _story_chapters(repo: ContentRepo, book_id: int, chapter_idx: int | None) -> list[Chapter]:
    chapters = [c for c in repo.get_chapters(book_id) if c.included]
    if chapter_idx is not None:
        chapters = [c for c in chapters if c.idx == chapter_idx]
        if not chapters:
            raise IngestionError(f"Chapter {chapter_idx} is not a story chapter of book {book_id}")
    return chapters


def approve_beats(
    conn: sqlite3.Connection,
    book_id: int,
    *,
    chapter_idx: int | None = None,
    beat_idx: int | None = None,
    include_flagged: bool = False,
) -> ApproveResult:
    """Approve draft beats. Flagged ones need `include_flagged` (a deliberate choice, as when
    the reviewer has read the flags) or being named with `beat_idx`."""
    repo = ContentRepo(conn)
    approved = flagged = empty = 0
    for chapter in _story_chapters(repo, book_id, chapter_idx):
        for beat in repo.get_beats(book_id, chapter.idx):
            if beat.review_status == "approved" or (beat_idx is not None and beat.idx != beat_idx):
                continue
            if not beat.narration:
                empty += 1
            elif beat.flags and not include_flagged and beat_idx is None:
                flagged += 1
            else:
                repo.update_beat(book_id, replace(beat, review_status="approved"))
                approved += 1
    return ApproveResult(approved, flagged, empty)


def publish_problems(conn: sqlite3.Connection, book_id: int) -> list[str]:
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog")
    chapters = [c for c in repo.get_chapters(book_id) if c.included]
    if not chapters:
        return ["the book has no story chapters"]
    problems: list[str] = []
    for chapter in chapters:
        beats = repo.get_beats(book_id, chapter.idx)
        if not beats:
            problems.append(f"chapter {chapter.idx} ({chapter.title}) has no beats")
            continue
        waiting = [b.idx + 1 for b in beats if b.review_status != "approved"]
        if waiting:
            problems.append(
                f"chapter {chapter.idx} ({chapter.title}): beats {waiting} are not approved"
            )
        with_chunks = {c.beat_idx for c in repo.get_chunks(book_id, chapter.idx)}
        missing = [b.idx + 1 for b in beats if b.idx not in with_chunks]
        if missing:
            problems.append(f"chapter {chapter.idx}: beats {missing} have no chunks; run ingest")
    return problems


def publish(conn: sqlite3.Connection, book_id: int) -> list[str]:
    """Mark the book ready if every story chapter has approved beats and chunks. Returns the
    problems that stopped it, or an empty list on success."""
    problems = publish_problems(conn, book_id)
    if not problems:
        ContentRepo(conn).set_book_status(book_id, "ready")
    return problems


def render_review(
    conn: sqlite3.Connection, data_dir: Path, book_id: int, chapter_idx: int | None = None
) -> str:
    """Everything a reviewer needs: each beat's text range, content, flags and status."""
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog")
    cleaned = load_cleaned(data_dir, book)
    out = [f"Review of book {book.id}: {book.title}  (status {book.status})", ""]
    for chapter in _story_chapters(repo, book_id, chapter_idx):
        beats = repo.get_beats(book_id, chapter.idx)
        out.append(f"Chapter {chapter.idx}: {chapter.title}  ({len(beats)} beats)")
        for beat in sorted(beats, key=lambda b: (not b.flags, b.idx)):
            out += _render_beat(
                beat,
                cleaned.line_at(beat.start_char),
                cleaned.line_at(max(beat.start_char, beat.end_char - 1)),
            )
        out.append("")
    return "\n".join(out).rstrip()


def _render_beat(beat: Beat, first_line: int, last_line: int) -> list[str]:
    mark = "FLAGGED" if beat.flags else beat.review_status
    lines = [
        f"  B{beat.idx + 1}  {beat.title or '(no title)'}  [{mark}, {beat.source}]"
        f"  raw lines {first_line}-{last_line}"
    ]
    if beat.narration:
        lines.append(f"      {beat.narration}")
    for clue, quote in zip(beat.clues, beat.clue_quotes or [""] * len(beat.clues), strict=False):
        lines.append(f"      clue: {clue}" + (f'   <- "{quote[:70]}"' if quote else ""))
    if beat.vocabulary:
        lines.append(f"      words: {', '.join(beat.vocabulary)}")
    prompt = beat.choice.get("prompt") if beat.choice else None
    if prompt:
        options = [
            ("*" if c.get("canon") else "-") + " " + str(c.get("text"))
            for c in beat.choice.get("cards", [])
        ]
        lines.append(f"      choice: {prompt}  {'  '.join(options)}")
    lines += [f"      ! {flag}" for flag in beat.flags]
    return lines
