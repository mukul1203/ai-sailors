import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingestion"))
from stage_llm import StageLLM  # noqa: E402
from test_library import TINY, make_settings, write_book  # noqa: E402

from storyquest.api.library import library, prepare_chapter  # noqa: E402
from storyquest.api.main import create_app  # noqa: E402
from storyquest.config import Settings  # noqa: E402
from storyquest.ingestion.worker import run_worker  # noqa: E402
from storyquest.models.embedder import EmbeddingError, FakeEmbedder  # noqa: E402
from storyquest.stores.db import connect, migrate, migrations_dir  # noqa: E402
from storyquest.stores.vector import chunks_without_vectors  # noqa: E402

pytestmark = pytest.mark.integration


def book_body(source: Path, **over: object) -> dict:  # type: ignore[type-arg]
    body = {
        "gutenberg_id": 9100,
        "title": "Uploaded Tales",
        "author": "A. Writer",
        "summary": "Uploaded by an admin.",
        "text": (source / "raw.txt").read_text(),
    }
    return {**body, **over}


@pytest.fixture
def source(tmp_path: Path) -> Path:
    write_book(tmp_path / "source")
    return tmp_path / "source"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_settings(tmp_path), llm=StageLLM(every=3)))


def test_an_uploaded_book_lands_in_the_books_folder_and_shows_in_the_library(
    tmp_path: Path, client: TestClient, source: Path
) -> None:
    r = client.post("/api/admin/books", json=book_body(source))
    assert r.status_code == 201 and r.json() == {"id": 9100, "title": "Uploaded Tales"}
    folder = tmp_path / "books" / "9100-uploaded-tales"
    assert (folder / "raw.txt").is_file() and "Uploaded Tales" in (folder / "book.yaml").read_text()
    listed = {b["id"]: b for b in client.get("/api/library").json()}
    assert [c["state"] for c in listed[9100]["chapters"]] == ["not_prepared", "not_prepared"]
    assert listed[9100]["status"] == "allowlisted"


def test_an_upload_that_is_not_a_gutenberg_text_or_is_a_repeat_is_refused(
    tmp_path: Path, client: TestClient, source: Path
) -> None:
    r = client.post("/api/admin/books", json=book_body(source, text="just some words"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_book"
    assert not list((tmp_path / "books").glob("9100-*"))  # nothing was left behind
    assert client.post("/api/admin/books", json=book_body(source)).status_code == 201
    again = client.post("/api/admin/books", json=book_body(source, title="Other"))
    assert again.status_code == 409 and again.json()["error"]["code"] == "book_exists"


def test_a_book_goes_from_prepared_to_reviewed_to_published_and_playable(
    tmp_path: Path,
) -> None:
    write_book(tmp_path / "books" / "9001-tiny-tales")
    settings: Settings = make_settings(tmp_path)
    client = TestClient(create_app(settings, llm=StageLLM(every=3)))
    conn = connect(settings.data_dir / "content.db")
    library(conn, settings)
    for chapter in (0, 1):
        prepare_chapter(conn, settings, TINY, chapter)
    assert run_worker(conn, settings, StageLLM(every=3), once=True) == 2
    conn.close()

    assert client.get("/api/missions").json() == []  # prepared is not yet published
    review = client.get(f"/api/admin/books/{TINY}/review").json()
    assert [c["title"] for c in review["chapters"]] == ["The Fox", "The Owl"]
    beat = review["chapters"][0]["beats"][0]
    assert beat["narration"] and beat["question"] and sum(c["right"] for c in beat["cards"]) == 1
    assert review["problems"]  # draft beats block publishing

    refused = client.post(f"/api/admin/books/{TINY}/publish").json()
    assert refused["published"] is False and refused["problems"]

    one = client.post(f"/api/admin/books/{TINY}/approve", json={"chapter_idx": 0, "beat_idx": 0})
    assert one.json()["approved"] == 1
    client.post(f"/api/admin/books/{TINY}/approve", json={"include_flagged": True})
    done = client.get(f"/api/admin/books/{TINY}/review").json()
    assert done["problems"] == [] and all(
        b["status"] == "approved" for c in done["chapters"] for b in c["beats"]
    )

    assert client.post(f"/api/admin/books/{TINY}/publish").json() == {
        "published": True,
        "problems": [],
        "embedding_error": "",
    }
    assert client.get(f"/api/admin/books/{TINY}/review").json()["status"] == "ready"
    assert {m["chapter"] for m in client.get("/api/missions").json()} == {"The Fox", "The Owl"}


def test_flagged_beats_are_not_approved_in_bulk(tmp_path: Path) -> None:
    write_book(tmp_path / "books" / "9001-tiny-tales")
    settings = make_settings(tmp_path)
    client = TestClient(create_app(settings, llm=StageLLM(every=3)))
    conn = connect(settings.data_dir / "content.db")
    library(conn, settings)
    prepare_chapter(conn, settings, TINY, 0)
    run_worker(conn, settings, StageLLM(every=3), once=True)
    conn.execute(
        "UPDATE beats SET flags = ? WHERE book_id = ? AND chapter_idx = 0 AND idx = 0",
        ('["checked by a test"]', TINY),
    )
    conn.close()
    out = client.post(f"/api/admin/books/{TINY}/approve", json={"chapter_idx": 0}).json()
    assert out["flagged_left"] >= 1
    first = client.get(f"/api/admin/books/{TINY}/review").json()["chapters"][0]["beats"][0]
    assert first["status"] == "draft" and first["flags"] == ["checked by a test"]


def test_an_unknown_book_gives_not_found(client: TestClient) -> None:
    assert client.get("/api/admin/books/12345/review").status_code == 404
    assert client.post("/api/admin/books/12345/publish").status_code == 404


def prepared_book(tmp_path: Path) -> Settings:
    write_book(tmp_path / "books" / "9001-tiny-tales")
    settings = make_settings(tmp_path)
    conn = connect(settings.data_dir / "content.db")
    migrate(conn, migrations_dir("content"))
    library(conn, settings)
    for chapter in (0, 1):
        prepare_chapter(conn, settings, TINY, chapter)
    run_worker(conn, settings, StageLLM(every=3), once=True)
    conn.close()
    return settings


def test_publishing_embeds_the_whole_book_once(tmp_path: Path) -> None:
    settings = prepared_book(tmp_path)
    embedder = FakeEmbedder()
    client = TestClient(create_app(settings, llm=StageLLM(every=3), embedder=embedder))
    client.post(f"/api/admin/books/{TINY}/approve", json={"include_flagged": True})
    out = client.post(f"/api/admin/books/{TINY}/publish").json()
    assert out["published"] and out["embedding_error"] == ""
    conn = connect(settings.data_dir / "content.db")
    assert not chunks_without_vectors(conn, TINY, embedder.model_id)
    conn.close()


def test_a_book_with_problems_is_not_embedded(tmp_path: Path) -> None:
    settings = prepared_book(tmp_path)
    embedder = FakeEmbedder()
    client = TestClient(create_app(settings, llm=StageLLM(every=3), embedder=embedder))
    assert client.post(f"/api/admin/books/{TINY}/publish").json()["published"] is False
    assert embedder.calls == []


def test_running_out_of_embedding_quota_still_publishes_the_book(tmp_path: Path) -> None:
    class OutOfQuota(FakeEmbedder):
        def embed(self, texts: list[str], *, query: bool) -> list[list[float]]:
            raise EmbeddingError("quota exceeded")

    settings = prepared_book(tmp_path)
    client = TestClient(create_app(settings, llm=StageLLM(every=3), embedder=OutOfQuota()))
    client.post(f"/api/admin/books/{TINY}/approve", json={"include_flagged": True})
    out = client.post(f"/api/admin/books/{TINY}/publish").json()
    assert out["published"] and "quota exceeded" in out["embedding_error"]
