"""What the sidekick remembers within one play session, so a follow-up question makes sense.

"Why did he do that?" means nothing on its own; with the last question ("Who is Shere Khan?")
the planner can rewrite it as "Why did Shere Khan come to the cave?". Only questions the router
treated as story questions are remembered: a message about feelings, something unsafe or
something personal never comes back into a prompt.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

MEMORY_TURNS = 3


@dataclass(frozen=True)
class PastTurn:
    question: str
    reply: str


def recent_turns(
    app: sqlite3.Connection, session_id: str, limit: int = MEMORY_TURNS
) -> list[PastTurn]:
    """The session's last `limit` story questions and their replies, oldest first."""
    rows = app.execute(
        "SELECT text, reply FROM session_events"
        " WHERE session_id = ? AND kind = 'ask' AND route = 'story_question'"
        " ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [PastTurn(str(text), str(reply)) for text, reply in reversed(rows)]


def describe(history: Sequence[PastTurn]) -> str:
    """The conversation so far as plain lines, for a prompt; empty when there is none."""
    return "\n".join(f"Child: {t.question}\nGuide: {t.reply}" for t in history)
