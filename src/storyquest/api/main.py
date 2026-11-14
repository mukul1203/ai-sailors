"""The HTTP API and the web UI: `create_app()` is the app factory (run with `uvicorn --factory`)."""

import sqlite3
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from storyquest.agent.modes import Mode, get_mode
from storyquest.api import admin, library, play
from storyquest.config import Settings, load_settings
from storyquest.ingestion.worker import run_worker
from storyquest.models.build import build_embedder, build_llm
from storyquest.models.embedder import Embedder, EmbeddingError
from storyquest.models.llm import LLMClient, LLMError
from storyquest.stores.db import connect, migrate, migrations_dir

# Without the embeddings (no key, or none yet) a hybrid mode becomes its keyword twin.
_KEYWORD_TWIN = {"M2": "M1", "M2S": "M1S", "M3": "M1", "M3S": "M1S"}


@dataclass
class AppState:
    settings: Settings
    llm: LLMClient | None
    llm_error: str
    embedder: Embedder | None
    mode: Mode


class StartBody(BaseModel):
    book_id: int
    chapter_idx: int


class ChoiceBody(BaseModel):
    card_id: str = Field(min_length=1, max_length=40)


class AskBody(BaseModel):
    text: str = Field(max_length=2000)


class AddBookBody(BaseModel):
    gutenberg_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    content_notes: str = Field(default="", max_length=1000)
    text: str = Field(max_length=admin.MAX_BOOK_CHARS)


class ApproveBody(BaseModel):
    chapter_idx: int | None = None
    beat_idx: int | None = None
    include_flagged: bool = False


def _choose_mode(settings: Settings, embedder: Embedder | None) -> Mode:
    mode = get_mode(settings.play_mode)
    if mode.hybrid and embedder is None:
        return get_mode(_KEYWORD_TWIN[mode.name])
    return mode


def _work(settings: Settings, llm: LLMClient, stop: threading.Event) -> None:
    conn = connect(settings.data_dir / "content.db")
    try:
        run_worker(conn, settings, llm, poll_seconds=1.0, stop=stop)
    finally:
        conn.close()


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    """Build the app. Tests pass a fake `llm` and `embedder`; otherwise they come from settings,
    and if the model is not configured the app still starts (the sidekick says it is resting)."""
    settings = settings or load_settings()
    llm_error = ""
    if llm is None:
        try:
            llm = build_llm(settings)
        except LLMError as e:
            llm_error = str(e)
    mode = get_mode(settings.play_mode)
    if mode.hybrid and embedder is None:
        try:
            embedder = build_embedder(settings)
        except EmbeddingError:
            embedder = None
    state = AppState(settings, llm, llm_error, embedder, _choose_mode(settings, embedder))

    for name in ("content", "app"):
        conn = connect(settings.data_dir / f"{name}.db")
        migrate(conn, migrations_dir(name))
        conn.close()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Run queued ingestion jobs (a chapter being prepared) in a thread for as long as the
        app lives. The model serves one request at a time, so this shares it with the children."""
        stop = threading.Event()
        if settings.ingest_in_api and state.llm is not None:
            threading.Thread(
                target=_work, args=(settings, state.llm, stop), name="ingestion", daemon=True
            ).start()
        yield
        stop.set()

    app = FastAPI(
        title="StoryQuest",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.api_debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.api_debug else None,
    )
    app.state.play = state

    def content_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(settings.data_dir / "content.db")
        try:
            yield conn
        finally:
            conn.close()

    def app_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(settings.data_dir / "app.db")
        try:
            yield conn
        finally:
            conn.close()

    Content = Depends(content_conn)
    App = Depends(app_conn)

    @app.exception_handler(play.PlayError)
    def play_error(_: Request, e: play.PlayError) -> JSONResponse:
        return JSONResponse(
            status_code=e.status, content={"error": {"code": e.code, "message": e.message}}
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "model": state.llm is not None, "mode": state.mode.name}

    @app.get("/api/library")
    def books(content: sqlite3.Connection = Content) -> list[dict[str, Any]]:
        return library.library(content, settings)

    @app.post("/api/library/{book_id}/chapters/{chapter_idx}/prepare", status_code=202)
    def prepare(
        book_id: int, chapter_idx: int, content: sqlite3.Connection = Content
    ) -> dict[str, Any]:
        if state.llm is None:
            raise play.PlayError(503, "not_ready", "The story helper is resting. Try again later!")
        return {"job": library.prepare_chapter(content, settings, book_id, chapter_idx)}

    @app.post("/api/admin/books", status_code=201)
    def add_book(body: AddBookBody, content: sqlite3.Connection = Content) -> dict[str, Any]:
        return admin.add_book(content, settings, **body.model_dump())

    @app.get("/api/admin/books/{book_id}/review")
    def review(book_id: int, content: sqlite3.Connection = Content) -> dict[str, Any]:
        return admin.review_view(content, book_id)

    @app.post("/api/admin/books/{book_id}/approve")
    def approve(
        book_id: int, body: ApproveBody, content: sqlite3.Connection = Content
    ) -> dict[str, int]:
        return admin.approve(content, book_id, **body.model_dump())

    @app.post("/api/admin/books/{book_id}/publish")
    def publish_book(book_id: int, content: sqlite3.Connection = Content) -> dict[str, Any]:
        return admin.publish_book(content, book_id, state.embedder)

    @app.get("/api/missions")
    def missions(content: sqlite3.Connection = Content) -> list[dict[str, Any]]:
        return [
            {
                "book_id": m.book_id,
                "book": m.book_title,
                "chapter_idx": m.chapter_idx,
                "chapter": m.chapter_title,
                "beats": m.beats,
            }
            for m in play.list_missions(content)
        ]

    @app.post("/api/sessions", status_code=201)
    def start(
        body: StartBody,
        content: sqlite3.Connection = Content,
        app_db: sqlite3.Connection = App,
    ) -> dict[str, Any]:
        session_id = play.start_session(
            app_db, content, settings,
            book_id=body.book_id, chapter_idx=body.chapter_idx, mode=state.mode.name,
        )  # fmt: skip
        return play.view_session(app_db, content, settings, session_id)

    @app.get("/api/sessions/{session_id}")
    def session(
        session_id: str,
        content: sqlite3.Connection = Content,
        app_db: sqlite3.Connection = App,
    ) -> dict[str, Any]:
        return play.view_session(app_db, content, settings, session_id)

    @app.post("/api/sessions/{session_id}/choice")
    def choice(
        session_id: str,
        body: ChoiceBody,
        content: sqlite3.Connection = Content,
        app_db: sqlite3.Connection = App,
    ) -> dict[str, Any]:
        return play.choose(app_db, content, settings, session_id, body.card_id)

    @app.post("/api/sessions/{session_id}/ask")
    def ask(
        session_id: str,
        body: AskBody,
        content: sqlite3.Connection = Content,
        app_db: sqlite3.Connection = App,
    ) -> dict[str, Any]:
        if state.llm is None:
            raise play.PlayError(503, "not_ready", "The sidekick is resting. Try again later!")
        return play.ask(
            app_db, content, settings, state.llm, state.embedder, state.mode, session_id, body.text
        )

    static = files("storyquest.api") / "static"
    app.mount("/", StaticFiles(directory=str(static), html=True), name="ui")
    return app
