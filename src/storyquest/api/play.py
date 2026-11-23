"""The play service: missions, sessions, choices and the child's questions. No HTTP in here.

The server owns the state. A session is a chapter's beats played in order; choosing a card
needs no model (the feedback is fixed and the next beat comes from ingestion), and only a free
text question runs the live agent, at the child's position, so its answer cannot spoil what
comes later.
"""

import json
import logging
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from storyquest.agent.context import AgentError, load_context
from storyquest.agent.modes import Mode
from storyquest.agent.turn import run_turn
from storyquest.config import Settings
from storyquest.domain.book import Beat, Chapter
from storyquest.domain.position import Position
from storyquest.models.embedder import Embedder
from storyquest.models.llm import LLMClient
from storyquest.models.reranker import Reranker
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.traces import save_trace

log = logging.getLogger(__name__)

BACK_TO_QUEST = "Ready to go back to the quest?"
MAX_WRONG_TRIES = 2  # after this many wrong answers the right one is shown and the quest goes on


class PlayError(Exception):
    """A problem the client should be told about, with the HTTP status that fits it."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Mission:
    book_id: int
    book_title: str
    chapter_idx: int
    chapter_title: str
    beats: int


def chapter_beats(repo: ContentRepo, book_id: int, chapter: Chapter) -> list[Beat] | None:
    """The beats a child may play: every one written, approved and chunked."""
    beats = repo.get_beats(book_id, chapter.idx)
    chunk_beats = {c.beat_idx for c in repo.get_chunks(book_id, chapter.idx)}
    ok = bool(beats) and all(
        b.review_status == "approved" and b.narration and b.idx in chunk_beats for b in beats
    )
    return beats if chapter.included and ok else None


def list_missions(content: sqlite3.Connection) -> list[Mission]:
    """Chapters a child can play: published books whose beats are all approved."""
    repo = ContentRepo(content)
    missions: list[Mission] = []
    for book in repo.list_books(status="ready"):
        if book.visibility != "listed":
            continue
        for chapter in repo.get_chapters(book.id):
            beats = chapter_beats(repo, book.id, chapter)
            if beats:
                missions.append(
                    Mission(book.id, book.title, chapter.idx, chapter.title, len(beats))
                )
    return missions


def _row(app: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row: sqlite3.Row | None = app.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise PlayError(404, "no_such_session", "That quest was not found. Start a new one!")
    return row


def start_session(
    app: sqlite3.Connection,
    content: sqlite3.Connection,
    settings: Settings,
    *,
    book_id: int,
    chapter_idx: int,
    mode: str,
) -> str:
    if not any(
        m.book_id == book_id and m.chapter_idx == chapter_idx for m in list_missions(content)
    ):
        raise PlayError(404, "no_such_mission", "That story is not ready to play yet.")
    session_id = secrets.token_urlsafe(16)
    now = time.time()
    app.execute(
        "INSERT INTO sessions (id, book_id, chapter_idx, mode, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, book_id, chapter_idx, mode, now, now),
    )
    return session_id


def _beats(content: sqlite3.Connection, session: sqlite3.Row) -> list[Beat]:
    return ContentRepo(content).get_beats(session["book_id"], session["chapter_idx"])


def _beat_view(beat: Beat) -> dict[str, Any]:
    cards = beat.choice.get("cards", []) if beat.choice else []
    return {
        "title": beat.title,
        "narration": beat.narration,
        "clues": beat.clues,
        "vocabulary": beat.vocabulary,
        "choice": {
            "prompt": beat.choice.get("prompt", "") if beat.choice else "",
            "cards": [{"id": c["id"], "text": c["text"]} for c in cards],
        },
    }


def _summary(app: sqlite3.Connection, session: sqlite3.Row, beats: list[Beat]) -> dict[str, Any]:
    vocabulary = list(dict.fromkeys(w for b in beats for w in b.vocabulary))
    first: dict[int, str] = {}
    for beat_idx, result in app.execute(
        "SELECT beat_idx, route FROM session_events WHERE session_id = ? AND kind = 'choice'"
        " ORDER BY id",
        (session["id"],),
    ):
        first.setdefault(beat_idx, result)
    return {
        "beats_completed": len(beats),
        "first_try": sum(1 for r in first.values() if r == "correct"),
        "questions_asked": session["questions"],
        "vocabulary": vocabulary,
    }


def view_session(
    app: sqlite3.Connection, content: sqlite3.Connection, settings: Settings, session_id: str
) -> dict[str, Any]:
    session = _row(app, session_id)
    repo = ContentRepo(content)
    book = repo.get_book(session["book_id"])
    chapter = next(
        (c for c in repo.get_chapters(session["book_id"]) if c.idx == session["chapter_idx"]),
        None,
    )
    beats = _beats(content, session)
    if book is None or chapter is None or not beats:
        raise PlayError(404, "no_such_mission", "That story is not available any more.")
    view: dict[str, Any] = {
        "id": session_id,
        "status": session["status"],
        "book": book.title,
        "chapter": chapter.title,
        "progress": {"beat": min(session["beat_idx"], len(beats) - 1) + 1, "total": len(beats)},
        "questions_left": max(0, settings.max_questions_per_session - session["questions"]),
    }
    if session["status"] == "completed":
        view["summary"] = _summary(app, session, beats)
    else:
        beat = beats[session["beat_idx"]]
        wrong = json.loads(session["wrong_cards"])
        view["beat"] = _beat_view(beat)
        view["wrong_cards"] = wrong
        if wrong:
            view["hint"] = _hint(beat, len(wrong))
    return view


def _event(
    app: sqlite3.Connection,
    session_id: str,
    kind: str,
    beat_idx: int,
    text: str,
    reply: str = "",
    route: str = "",
    flags: list[str] | None = None,
) -> int:
    cur = app.execute(
        "INSERT INTO session_events (session_id, kind, beat_idx, text, reply, route, flags,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, kind, beat_idx, text, reply, route, json.dumps(flags or []), time.time()),
    )
    return cur.lastrowid or 0


def _hint(beat: Beat, tries: int) -> str:
    """The hint for a child's n-th wrong answer: the written hints, or a clue if there are none."""
    hints = [h for h in (beat.choice.get("hints", []) if beat.choice else []) if h]
    if not hints:
        hints = [f"Think about this: {c}." for c in beat.clues] or ["Read the story again!"]
    return str(hints[min(tries, len(hints)) - 1])


def choose(
    app: sqlite3.Connection,
    content: sqlite3.Connection,
    settings: Settings,
    session_id: str,
    card_id: str,
) -> dict[str, Any]:
    """Answer the beat's question. The right card moves the quest on; a wrong one gives a hint
    and another try, and after MAX_WRONG_TRIES wrong ones the answer is shown and it moves on."""
    session = _row(app, session_id)
    if session["status"] != "active":
        raise PlayError(409, "quest_finished", "This quest is finished. Start a new one!")
    beats = _beats(content, session)
    beat = beats[session["beat_idx"]]
    cards = beat.choice.get("cards", []) if beat.choice else []
    card = next((c for c in cards if c["id"] == card_id), None)
    if card is None:
        raise PlayError(422, "no_such_card", "Pick one of the cards on the screen.")
    wrong: list[str] = json.loads(session["wrong_cards"])
    if card_id in wrong:
        raise PlayError(409, "already_tried", "You already tried that one. Pick another!")
    right = next((c for c in cards if c.get("canon")), card)  # no marked answer: any card is fine

    if card is right:
        result, feedback = "correct", f"Yes! {right['text']}."
    elif len(wrong) + 1 >= MAX_WRONG_TRIES:
        result, feedback = "revealed", f"Nice try! The answer was: {right['text']}."
    else:
        result, feedback = "wrong", ""
    _event(app, session_id, "choice", beat.idx, card_id, route=result)

    if result == "wrong":
        wrong.append(card_id)
        app.execute(
            "UPDATE sessions SET wrong_cards = ?, updated_at = ? WHERE id = ?",
            (json.dumps(wrong), time.time(), session_id),
        )
        view = view_session(app, content, settings, session_id)
        view["result"] = result
        return view

    last = session["beat_idx"] + 1 >= len(beats)
    app.execute(
        "UPDATE sessions SET beat_idx = ?, status = ?, wrong_cards = '[]', updated_at = ?"
        " WHERE id = ?",
        (
            session["beat_idx"] if last else session["beat_idx"] + 1,
            "completed" if last else "active",
            time.time(),
            session_id,
        ),
    )
    view = view_session(app, content, settings, session_id)
    view["result"], view["feedback"] = result, feedback
    return view


def ask(
    app: sqlite3.Connection,
    content: sqlite3.Connection,
    settings: Settings,
    llm: LLMClient,
    embedder: Embedder | None,
    mode: Mode,
    session_id: str,
    text: str,
    *,
    reranker: Reranker | None = None,
) -> dict[str, Any]:
    """A child's free-text question, answered at their position in the book."""
    session = _row(app, session_id)
    if session["status"] != "active":
        raise PlayError(409, "quest_finished", "This quest is finished. Start a new one!")
    if session["questions"] >= settings.max_questions_per_session:
        raise PlayError(
            409,
            "no_questions_left",
            "That was a lot of good questions! Let's get back to the quest.",
        )
    last_ask = app.execute(
        "SELECT MAX(created_at) FROM session_events WHERE session_id = ? AND kind = 'ask'",
        (session_id,),
    ).fetchone()[0]
    if last_ask is not None and time.time() - last_ask < settings.ask_min_interval_seconds:
        raise PlayError(429, "too_fast", "One moment! Let the sidekick think, then ask again.")

    try:
        ctx = load_context(
            content,
            llm,
            settings,
            session["book_id"],
            embedder,
            reranker=reranker,
        )
    except AgentError as e:
        raise PlayError(503, "not_ready", str(e)) from e
    beats = _beats(content, session)
    beat = beats[session["beat_idx"]]
    result = run_turn(ctx, text, Position(session["chapter_idx"], beat.idx), mode=mode)
    event_id = _event(
        app, session_id, "ask", beat.idx, text, result.reply, result.route, result.flags
    )
    if settings.trace_store != "off":
        try:  # a trace is for the grown-ups: failing to save one must never fail the child's reply
            save_trace(app, session_id, event_id, result, settings.trace_store)
        except Exception:
            log.exception("could not save the trace for session %s", session_id)
    app.execute(
        "UPDATE sessions SET questions = questions + 1, updated_at = ? WHERE id = ?",
        (time.time(), session_id),
    )
    out: dict[str, Any] = {
        "reply": result.reply,
        "back": f"{BACK_TO_QUEST} {beat.choice.get('prompt', '')}".strip(),
        "questions_left": max(0, settings.max_questions_per_session - session["questions"] - 1),
    }
    if settings.api_debug:
        out["debug"] = {"route": result.route, "flags": result.flags, "mode": mode.name}
    return out


def purge_sessions(app: sqlite3.Connection, older_than_days: float) -> int:
    """Delete sessions (and their events) not touched for this many days. Returns how many."""
    cutoff = time.time() - older_than_days * 86400
    cur = app.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
    return cur.rowcount
