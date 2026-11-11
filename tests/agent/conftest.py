import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from storyquest.agent.context import AgentContext, load_context
from storyquest.catalog.importer import import_books
from storyquest.config import Settings, load_settings
from storyquest.ingestion.pipeline import run_deterministic
from storyquest.models.llm import LLMClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(tmp_path, environ={"DATA_DIR": str(tmp_path / "data")})


@pytest.fixture
def make_ctx(
    conn: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> Callable[[LLMClient], AgentContext]:
    import_books(conn, settings.data_dir, eval_dir / "books")
    run_deterministic(conn, settings, 236, spine_path=eval_dir / "spine_mowgli_brothers.json")

    def build(llm: LLMClient) -> AgentContext:
        return load_context(conn, llm, settings, 236)

    return build
