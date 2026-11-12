import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from storyquest.agent.context import AgentContext, load_context
from storyquest.catalog.importer import import_books
from storyquest.config import Settings, load_settings
from storyquest.ingestion.pipeline import run_deterministic
from storyquest.models.llm import LLMClient
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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Pinned so the tests do not move when the production chunk size is tuned.
    environ = {
        "DATA_DIR": str(tmp_path / "data"),
        "CHUNK_TARGET_CHARS": "1200",
        "RETRIEVAL_TOP_K": "3",
    }
    return load_settings(tmp_path, environ=environ)


@pytest.fixture
def make_ctx(
    conn: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> Callable[[LLMClient], AgentContext]:
    """Ingest the Jungle Book (with the hand-written spine) and return a context factory."""
    import_books(conn, settings.data_dir, eval_dir / "books")
    run_deterministic(conn, settings, 236, spine_path=eval_dir / "spine_mowgli_brothers.json")

    def build(llm: LLMClient) -> AgentContext:
        return load_context(conn, llm, settings, 236)

    return build
