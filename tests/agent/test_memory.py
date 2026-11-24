import sqlite3
import time
from pathlib import Path

from storyquest.agent.memory import PastTurn, describe, recent_turns
from storyquest.stores.db import connect, migrate, migrations_dir


def app_db(tmp_path: Path) -> sqlite3.Connection:
    app = connect(tmp_path / "app.db")
    migrate(app, migrations_dir("app"))
    now = time.time()
    app.execute(
        "INSERT INTO sessions (id, book_id, chapter_idx, mode, created_at, updated_at)"
        " VALUES ('s1', 236, 0, 'M5', ?, ?)",
        (now, now),
    )
    return app


def ask(app: sqlite3.Connection, text: str, reply: str, route: str = "story_question") -> None:
    app.execute(
        "INSERT INTO session_events (session_id, kind, beat_idx, text, reply, route, created_at)"
        " VALUES ('s1', 'ask', 0, ?, ?, ?, ?)",
        (text, reply, route, time.time()),
    )


def test_the_last_story_questions_come_back_oldest_first(tmp_path: Path) -> None:
    app = app_db(tmp_path)
    for n in range(1, 5):
        ask(app, f"question {n}", f"reply {n}")
    assert recent_turns(app, "s1") == [PastTurn(f"question {n}", f"reply {n}") for n in (2, 3, 4)]
    assert recent_turns(app, "s1", limit=1) == [PastTurn("question 4", "reply 4")]
    assert recent_turns(app, "nobody") == []


def test_feelings_unsafe_and_personal_messages_are_never_remembered(tmp_path: Path) -> None:
    app = app_db(tmp_path)
    ask(app, "Who is Akela?", "The leader of the pack.")
    ask(app, "I live at 12 Rose Street", "Let's keep that secret.", route="personal")
    ask(app, "I'm scared", "It's okay.", route="feelings")
    assert recent_turns(app, "s1") == [PastTurn("Who is Akela?", "The leader of the pack.")]


def test_the_history_reads_as_a_short_conversation() -> None:
    history = [PastTurn("Who is Tabaqui?", "A jackal.")]
    assert describe(history) == "Child: Who is Tabaqui?\nGuide: A jackal."
    assert describe([]) == ""
