"""Mode M5 in the game: session memory over the API, and no downgrade without embeddings."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_helpers import AgentLLM, plan
from storyquest.api.main import create_app
from storyquest.catalog.importer import import_books
from storyquest.config import Settings, load_settings
from storyquest.ingestion.pipeline import run_deterministic
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.db import connect, migrate, migrations_dir

pytestmark = pytest.mark.integration

BOOK = 236


@pytest.fixture
def agent_game(tmp_path: Path, eval_dir: Path) -> Settings:
    """The Jungle Book, published, played in mode M5 with a fake model and no embeddings."""
    settings = load_settings(
        tmp_path,
        environ={
            "DATA_DIR": str(tmp_path / "data"),
            "PLAY_MODE": "M5",
            "ASK_MIN_INTERVAL_SECONDS": "0",
            "LLM_PROVIDER": "fake",
            "API_DEBUG": "true",
        },
    )
    conn = connect(settings.data_dir / "content.db")
    migrate(conn, migrations_dir("content"))
    import_books(conn, settings.data_dir, eval_dir / "books")
    run_deterministic(conn, settings, BOOK, spine_path=eval_dir / "spine_mowgli_brothers.json")
    ContentRepo(conn).set_book_status(BOOK, "ready")
    conn.close()
    return settings


def test_the_game_remembers_earlier_story_questions_in_a_session(agent_game: Settings) -> None:
    llm = AgentLLM(plans=[plan("Why does Shere Khan limp?", ("search_book", "Shere Khan lame"))])
    client = TestClient(create_app(agent_game, llm=llm))
    sid = client.post("/api/sessions", json={"book_id": BOOK, "chapter_idx": 0}).json()["id"]

    first = client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Shere Khan?"}).json()
    assert first["reply"] == "Shere Khan was born lame in one foot."
    assert first["debug"]["mode"] == "M5"  # no embeddings: the agent keeps its mode
    client.post(f"/api/sessions/{sid}/ask", json={"text": "Why does he limp?"})

    first_plan, second_plan = (m[0]["content"] for m in llm.calls if AgentLLM.role(m) == "planner")
    assert "(none)" in first_plan
    assert "Child: Who is Shere Khan?\nGuide: Shere Khan was born lame in one foot." in second_plan


def test_a_personal_message_never_reaches_the_next_plan(agent_game: Settings) -> None:
    llm = AgentLLM(label="personal")
    client = TestClient(create_app(agent_game, llm=llm))
    sid = client.post("/api/sessions", json={"book_id": BOOK, "chapter_idx": 0}).json()["id"]
    client.post(f"/api/sessions/{sid}/ask", json={"text": "I live at 12 Rose Street"})
    llm.label = "story_question"
    client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Shere Khan?"})
    [planner_system] = [m[0]["content"] for m in llm.calls if AgentLLM.role(m) == "planner"]
    assert "Rose Street" not in planner_system and "(none)" in planner_system
