import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.db import connect, migrate, migrations_dir


@pytest.fixture(scope="session")
def eval_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "eval"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(tmp_path / "content.db")
    migrate(c, migrations_dir("content"))
    yield c
    c.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> ContentRepo:
    return ContentRepo(conn)
