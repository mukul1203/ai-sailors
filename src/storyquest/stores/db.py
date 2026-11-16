"""SQLite connections and numbered SQL migrations."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the API opens a connection per request, but FastAPI may run the
    # dependency and the endpoint on different worker threads. A connection is never shared by
    # two requests at once, so moving between threads is safe.
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrations_dir(kind: str) -> Traversable:
    return files("storyquest.stores") / "migrations" / kind


def migrate(conn: sqlite3.Connection, source: Traversable) -> list[str]:
    """Apply any migration files not yet recorded, in name order. Returns the ones applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[str] = []
    for item in sorted(source.iterdir(), key=lambda p: p.name):
        if not item.name.endswith(".sql") or item.name in done:
            continue
        script = (
            f"BEGIN;\n{item.read_text()}\n"
            f"INSERT INTO schema_migrations (version) VALUES ('{item.name}');\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(item.name)
    return applied
