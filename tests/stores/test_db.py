import sqlite3
from pathlib import Path

import pytest

from storyquest.stores.db import connect, migrate, migrations_dir, transaction

pytestmark = pytest.mark.integration


def test_migrate_creates_tables_and_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "content.db")
    first = migrate(conn, migrations_dir("content"))
    assert first == ["0001_init.sql", "0002_names.sql", "0003_embeddings.sql"]
    assert migrate(conn, migrations_dir("content")) == []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"books", "chapters", "beats", "chunks", "chunks_fts", "names"} <= tables


def test_connection_settings(tmp_path: Path) -> None:
    conn = connect(tmp_path / "nested" / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_failed_migration_rolls_back_and_is_not_recorded(tmp_path: Path) -> None:
    source = tmp_path / "migrations"
    source.mkdir()
    (source / "0001_ok.sql").write_text("CREATE TABLE a (x INTEGER);")
    (source / "0002_bad.sql").write_text("CREATE TABLE b (x INTEGER); CREATE TABLE a (x INTEGER);")
    conn = connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.Error):
        migrate(conn, source)
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert done == {"0001_ok.sql"}
    assert "b" not in tables


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
