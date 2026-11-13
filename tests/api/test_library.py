import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from stage_llm import StageLLM  # noqa: E402

from storyquest.api.library import library, prepare_chapter  # noqa: E402
from storyquest.api.main import create_app  # noqa: E402
from storyquest.config import Settings, load_settings  # noqa: E402
from storyquest.ingestion.worker import run_worker  # noqa: E402
from storyquest.stores.db import connect, migrate, migrations_dir  # noqa: E402

pytestmark = pytest.mark.integration

TINY = 9001


def story_text(topic: str) -> str:
    """A chapter long enough to be a story and to need several beats."""
    sentences = [
        f"The {topic} walked slowly along the river and looked at the tall green trees. "
        f"Then the {topic} met a friend near the old stone bridge number {n} and they talked. "
        for n in range(1, 81)
    ]
    paragraphs = ["".join(sentences[i : i + 4]).strip() for i in range(0, 80, 4)]
    return "\n\n".join(paragraphs)


def write_book(folder: Path, *, book_id: int = TINY, with_sha: bool = False) -> None:
    folder.mkdir(parents=True)
    text = (
        "Header line\n\n*** START OF THE PROJECT GUTENBERG EBOOK TINY TALES ***\n\n"
        "Tiny Tales\n\nContents\n\nThe Fox\nThe Owl\n\n\n"
        f"The Fox\n\n{story_text('fox')}\n\nThe Owl\n\n{story_text('owl')}\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK TINY TALES ***\n"
    )
    (folder / "raw.txt").write_text(text)
    yaml = (
        f"gutenberg_id: {book_id}\ntitle: Tiny Tales\nauthor: A. Writer\n"
        "summary: Two short animal stories.\n"
    )
    (folder / "book.yaml").write_text(yaml)


def make_settings(tmp_path: Path, **env: str) -> Settings:
    base = {
        "DATA_DIR": str(tmp_path / "data"),
        "BOOKS_DIR": f"{tmp_path / 'books'},{tmp_path / 'more'}",
        "PLAY_UNPUBLISHED": "true",
        "INGEST_IN_API": "false",
        "CHUNK_TARGET_CHARS": "1200",
        "LLM_PROVIDER": "fake",
    }
    return load_settings(tmp_path, environ={**base, **env})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    write_book(tmp_path / "books" / "9001-tiny-tales")
    s = make_settings(tmp_path)
    conn = connect(s.data_dir / "content.db")
    migrate(conn, migrations_dir("content"))
    conn.close()
    return s


def chapters(books: list[dict]) -> dict[str, dict]:  # type: ignore[type-arg]
    tiny = next(b for b in books if b["id"] == TINY)
    return {c["title"]: c for c in tiny["chapters"]}


def test_a_dropped_in_book_shows_up_with_its_chapters_not_yet_prepared(settings: Settings) -> None:
    conn = connect(settings.data_dir / "content.db")
    books = library(conn, settings)
    tiny = next(b for b in books if b["id"] == TINY)
    assert tiny["title"] == "Tiny Tales" and tiny["summary"] == "Two short animal stories."
    assert [(c["title"], c["state"]) for c in tiny["chapters"]] == [
        ("The Fox", "not_prepared"),
        ("The Owl", "not_prepared"),
    ]
    assert tiny["error"] == ""  # book.yaml needs no sha256: it is computed
    conn.close()


def test_a_broken_folder_is_reported_without_hiding_the_others(
    tmp_path: Path, settings: Settings
) -> None:
    bad = tmp_path / "books" / "9002-broken"
    bad.mkdir()
    (bad / "book.yaml").write_text("gutenberg_id: 9002\ntitle: Broken\nauthor: Nobody\n")  # no text
    notes = tmp_path / "books" / "9003-notes"
    notes.mkdir()
    (notes / "raw.txt").write_text("text\n")
    (notes / "book.yaml").write_text("title: no id\n")
    conn = connect(settings.data_dir / "content.db")
    books = library(conn, settings)
    assert any(b["id"] == TINY for b in books)
    errors = [b["error"] for b in books if b["id"] is None]
    assert any("raw.txt is missing" in e for e in errors) and any(
        "needs gutenberg_id" in e for e in errors
    )
    conn.close()


def test_a_book_that_cannot_be_read_says_so(tmp_path: Path, settings: Settings) -> None:
    flat = tmp_path / "books" / "9004-flat"
    flat.mkdir()
    (flat / "raw.txt").write_text("just some text with no gutenberg markers\n")
    (flat / "book.yaml").write_text("gutenberg_id: 9004\ntitle: Flat\nauthor: Nobody\n")
    conn = connect(settings.data_dir / "content.db")
    flat_entry = next(b for b in library(conn, settings) if b["id"] == 9004)
    assert "could not be read" in flat_entry["error"] and flat_entry["chapters"] == []
    conn.close()


def test_preparing_a_chapter_queues_a_job_once_and_the_worker_makes_it_playable(
    settings: Settings,
) -> None:
    conn = connect(settings.data_dir / "content.db")
    library(conn, settings)
    job = prepare_chapter(conn, settings, TINY, 0)
    assert prepare_chapter(conn, settings, TINY, 0) == job  # asking again joins the same job
    waiting = chapters(library(conn, settings))["The Fox"]
    assert waiting["state"] == "preparing" and "Waiting" in waiting["message"]

    assert run_worker(conn, settings, StageLLM(every=3), once=True) == 1
    fox = chapters(library(conn, settings))["The Fox"]
    assert fox["state"] == "playable" and fox["beats"] >= 2
    assert chapters(library(conn, settings))["The Owl"]["state"] == "not_prepared"
    conn.close()


def test_progress_shows_the_latest_line_of_the_running_job(settings: Settings) -> None:
    conn = connect(settings.data_dir / "content.db")
    library(conn, settings)
    job = prepare_chapter(conn, settings, TINY, 1)
    conn.execute(
        "UPDATE ingestion_jobs SET status = 'running', message = 'generate ch1 B2 ok' WHERE id = ?",
        (job,),
    )
    owl = chapters(library(conn, settings))["The Owl"]
    assert owl["state"] == "preparing" and owl["message"] == "generate ch1 B2 ok"
    conn.close()


def test_a_failed_preparation_can_be_tried_again(settings: Settings) -> None:
    conn = connect(settings.data_dir / "content.db")
    library(conn, settings)
    broken = StageLLM()
    broken.mode = "down"
    prepare_chapter(conn, settings, TINY, 0)
    run_worker(conn, settings, broken, once=True)
    fox = chapters(library(conn, settings))["The Fox"]
    assert fox["state"] == "failed" and fox["message"]

    prepare_chapter(conn, settings, TINY, 0)  # "Try again"
    run_worker(conn, settings, StageLLM(every=3), once=True)
    assert chapters(library(conn, settings))["The Fox"]["state"] == "playable"
    conn.close()


def test_preparing_something_that_is_not_a_chapter_is_refused(settings: Settings) -> None:
    from storyquest.api.play import PlayError

    conn = connect(settings.data_dir / "content.db")
    library(conn, settings)
    with pytest.raises(PlayError) as e:
        prepare_chapter(conn, settings, TINY, 99)
    assert e.value.status == 404
    conn.close()


def test_the_api_lists_prepares_and_plays_a_new_book(tmp_path: Path, settings: Settings) -> None:
    app = create_app(settings, llm=StageLLM(every=3))
    with TestClient(app) as client:
        books = client.get("/api/library").json()
        assert chapters(books)["The Fox"]["state"] == "not_prepared"
        assert client.post(f"/api/library/{TINY}/chapters/0/prepare").status_code == 202
        # the worker inside the API prepares it in the background
    conn = connect(settings.data_dir / "content.db")
    run_worker(conn, settings, StageLLM(every=3), once=True)  # in case the thread did not finish
    conn.close()
    client = TestClient(create_app(settings, llm=StageLLM(every=3)))
    assert chapters(client.get("/api/library").json())["The Fox"]["state"] == "playable"
    view = client.post("/api/sessions", json={"book_id": TINY, "chapter_idx": 0}).json()
    assert view["status"] == "active" and view["beat"]["narration"]


def test_the_background_worker_in_the_api_prepares_a_chapter(tmp_path: Path) -> None:
    write_book(tmp_path / "books" / "9001-tiny-tales")
    settings = make_settings(tmp_path, INGEST_IN_API="true")
    with TestClient(create_app(settings, llm=StageLLM(every=3))) as client:
        client.get("/api/library")
        assert client.post(f"/api/library/{TINY}/chapters/0/prepare").status_code == 202
        deadline = time.time() + 20
        state = ""
        while time.time() < deadline:
            state = chapters(client.get("/api/library").json())["The Fox"]["state"]
            if state == "playable":
                break
            time.sleep(0.3)
        assert state == "playable"


def test_preparing_needs_the_model(tmp_path: Path, settings: Settings) -> None:
    no_model = make_settings(tmp_path, LLM_PROVIDER="openai_compatible", LLM_BASE_URL="")
    client = TestClient(create_app(no_model))
    client.get("/api/library")
    r = client.post(f"/api/library/{TINY}/chapters/0/prepare")
    assert r.status_code == 503 and r.json()["error"]["code"] == "not_ready"
