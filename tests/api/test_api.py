import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llm_helpers import ScriptedLLM
from storyquest.api.main import create_app
from storyquest.api.play import purge_sessions
from storyquest.catalog.importer import import_books
from storyquest.config import Settings, load_settings
from storyquest.ingestion.pipeline import run_deterministic
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.db import connect, migrate, migrations_dir

pytestmark = pytest.mark.integration

BOOK, CHAPTER = 236, 0


def make_settings(tmp_path: Path, **env: str) -> Settings:
    base = {
        "DATA_DIR": str(tmp_path / "data"),
        "CHUNK_TARGET_CHARS": "1200",
        "RETRIEVAL_TOP_K": "3",
        "PLAY_MODE": "M1",
        "ASK_MIN_INTERVAL_SECONDS": "0",
        "LLM_PROVIDER": "fake",
    }
    return load_settings(tmp_path, environ={**base, **env})


@pytest.fixture
def seeded(tmp_path: Path, eval_dir: Path) -> Settings:
    """A data folder with the Jungle Book ingested with its hand-written beats, unpublished."""
    settings = make_settings(tmp_path)
    conn = connect(settings.data_dir / "content.db")
    migrate(conn, migrations_dir("content"))
    import_books(conn, settings.data_dir, eval_dir / "books")
    run_deterministic(conn, settings, BOOK, spine_path=eval_dir / "spine_mowgli_brothers.json")
    conn.close()
    return settings


def publish(settings: Settings) -> None:
    conn = connect(settings.data_dir / "content.db")
    ContentRepo(conn).set_book_status(BOOK, "ready")
    conn.close()


@pytest.fixture
def client(seeded: Settings) -> TestClient:
    publish(seeded)
    return TestClient(create_app(seeded, llm=ScriptedLLM(answer="Shere Khan is lame.")))


def start(client: TestClient) -> dict:  # type: ignore[type-arg]
    r = client.post("/api/sessions", json={"book_id": BOOK, "chapter_idx": CHAPTER})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_only_published_books_have_missions(seeded: Settings) -> None:
    client = TestClient(create_app(seeded, llm=ScriptedLLM()))
    assert client.get("/api/missions").json() == []
    r = client.post("/api/sessions", json={"book_id": BOOK, "chapter_idx": CHAPTER})
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_such_mission"
    publish(seeded)
    missions = client.get("/api/missions").json()
    assert [(m["book"], m["chapter_idx"], m["beats"]) for m in missions] == [
        ("The Jungle Book", CHAPTER, 5)
    ]


def test_development_setting_lists_unpublished_books(tmp_path: Path, seeded: Settings) -> None:
    dev = make_settings(tmp_path, PLAY_UNPUBLISHED="true")
    missions = TestClient(create_app(dev, llm=ScriptedLLM())).get("/api/missions").json()
    assert [m["chapter_idx"] for m in missions] == [CHAPTER]


def test_a_session_starts_at_the_first_beat_without_leaking_the_answer_key(
    client: TestClient,
) -> None:
    view = start(client)
    assert view["status"] == "active" and view["progress"] == {"beat": 1, "total": 5}
    beat = view["beat"]
    assert beat["title"] == "A Warning at the Cave" and beat["narration"]
    assert beat["choice"]["prompt"] and len(beat["choice"]["cards"]) == 2
    assert all(set(c) == {"id", "text"} for c in beat["choice"]["cards"])  # no canon, no next
    assert client.get(f"/api/sessions/{view['id']}").json() == view  # resuming shows the same


def test_choosing_moves_through_the_beats_to_a_summary(client: TestClient) -> None:
    view = start(client)
    sid = view["id"]
    first = view["beat"]["choice"]["cards"][0]["id"]
    after = client.post(f"/api/sessions/{sid}/choice", json={"card_id": first}).json()
    assert after["progress"]["beat"] == 2 and after["feedback"]
    for _ in range(3):
        card = after["beat"]["choice"]["cards"][1]["id"]
        after = client.post(f"/api/sessions/{sid}/choice", json={"card_id": card}).json()
    assert after["progress"]["beat"] == 5
    last = after["beat"]["choice"]["cards"][0]["id"]
    done = client.post(f"/api/sessions/{sid}/choice", json={"card_id": last}).json()
    assert done["status"] == "completed" and "beat" not in done
    assert done["summary"]["beats_completed"] == 5 and done["summary"]["vocabulary"]
    again = client.post(f"/api/sessions/{sid}/choice", json={"card_id": last})
    assert again.status_code == 409 and again.json()["error"]["code"] == "quest_finished"


def test_the_book_choice_gets_different_feedback_from_another_idea(client: TestClient) -> None:
    sid = start(client)["id"]
    cards = client.get(f"/api/sessions/{sid}").json()["beat"]["choice"]["cards"]
    a = client.post(f"/api/sessions/{sid}/choice", json={"card_id": cards[0]["id"]}).json()
    sid2 = start(client)["id"]
    b = client.post(f"/api/sessions/{sid2}/choice", json={"card_id": cards[1]["id"]}).json()
    assert {a["feedback"], b["feedback"]} == {
        "That is just what happened in the book!",
        "Good idea! Here is what happened in the book.",
    }


def test_a_card_that_is_not_on_screen_is_refused(client: TestClient) -> None:
    sid = start(client)["id"]
    r = client.post(f"/api/sessions/{sid}/choice", json={"card_id": "B4-a"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_such_card"
    assert client.get(f"/api/sessions/{sid}").json()["progress"]["beat"] == 1  # nothing moved


def test_unknown_sessions_and_bad_bodies(client: TestClient) -> None:
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions", json={"book_id": "x"}).status_code == 422
    sid = start(client)["id"]
    assert client.post(f"/api/sessions/{sid}/ask", json={"text": "x" * 3000}).status_code == 422


def test_a_question_is_answered_at_the_childs_position(client: TestClient) -> None:
    sid = start(client)["id"]
    out = client.post(f"/api/sessions/{sid}/ask", json={"text": "Why does Shere Khan limp?"})
    assert out.status_code == 200
    body = out.json()
    assert body["reply"] == "Shere Khan is lame." and body["questions_left"] == 9
    assert body["back"].startswith("Ready to go back to the quest?")
    assert "debug" not in body  # the child never sees internals
    # Baloo first appears in the third beat, so at the start nothing may be found about him.
    late = client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Baloo?"}).json()
    assert late["reply"] == "I don't know that yet. Let's keep reading and find out together!"


def test_questions_are_capped_and_rate_limited(tmp_path: Path, seeded: Settings) -> None:
    publish(seeded)
    capped = make_settings(tmp_path, MAX_QUESTIONS_PER_SESSION="2")
    client = TestClient(create_app(capped, llm=ScriptedLLM()))
    sid = start(client)["id"]
    for _ in range(2):
        assert (
            client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Tabaqui?"}).status_code
            == 200
        )
    r = client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Tabaqui?"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_questions_left"

    slow = make_settings(tmp_path, ASK_MIN_INTERVAL_SECONDS="60")
    client = TestClient(create_app(slow, llm=ScriptedLLM()))
    sid = start(client)["id"]
    assert (
        client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Tabaqui?"}).status_code == 200
    )
    r = client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Tabaqui?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_fast"


def test_without_a_model_the_app_still_plays_but_the_sidekick_rests(
    tmp_path: Path, seeded: Settings
) -> None:
    publish(seeded)
    no_model = make_settings(tmp_path, LLM_PROVIDER="openai_compatible", LLM_BASE_URL="")
    client = TestClient(create_app(no_model))
    assert client.get("/api/health").json()["model"] is False
    sid = start(client)["id"]
    r = client.post(f"/api/sessions/{sid}/ask", json={"text": "Who is Tabaqui?"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "not_ready"
    card = client.get(f"/api/sessions/{sid}").json()["beat"]["choice"]["cards"][0]["id"]
    assert client.post(f"/api/sessions/{sid}/choice", json={"card_id": card}).status_code == 200


def test_a_hybrid_mode_without_embeddings_becomes_its_keyword_twin(
    tmp_path: Path, seeded: Settings
) -> None:
    hybrid = make_settings(tmp_path, PLAY_MODE="M2S", EMBEDDING_PROVIDER="gemini")
    client = TestClient(create_app(hybrid, llm=ScriptedLLM()))
    assert client.get("/api/health").json()["mode"] == "M1S"


def test_debug_details_only_when_switched_on(tmp_path: Path, seeded: Settings) -> None:
    publish(seeded)
    debug = make_settings(tmp_path, API_DEBUG="true")
    client = TestClient(create_app(debug, llm=ScriptedLLM(answer="Shere Khan is lame.")))
    sid = start(client)["id"]
    body = client.post(
        f"/api/sessions/{sid}/ask", json={"text": "Why does Shere Khan limp?"}
    ).json()
    assert body["debug"]["mode"] == "M1" and body["debug"]["route"] == "story_question"


def test_the_ui_is_served_with_safe_headers(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "StoryQuest" in page.text
    assert client.get("/app.js").status_code == 200 and client.get("/style.css").status_code == 200
    assert page.headers["content-security-policy"] == "default-src 'self'"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/docs").status_code == 404  # no API explorer unless debugging


def test_old_sessions_can_be_purged(client: TestClient, seeded: Settings) -> None:
    old = start(client)["id"]
    keep = start(client)["id"]
    conn = connect(seeded.data_dir / "app.db")
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time() - 40 * 86400, old))
    assert purge_sessions(conn, 30) == 1
    assert client.get(f"/api/sessions/{old}").status_code == 404
    assert client.get(f"/api/sessions/{keep}").status_code == 200
    conn.close()
