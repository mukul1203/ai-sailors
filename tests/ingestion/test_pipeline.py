import sqlite3
from pathlib import Path

import pytest

from storyquest.catalog.importer import import_books
from storyquest.config import Settings, load_settings
from storyquest.domain.position import Position
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.pipeline import IngestReport, load_cleaned, run_deterministic
from storyquest.stores.content_repo import ContentRepo
from storyquest.stores.search import search_chunks

pytestmark = pytest.mark.integration

BOOK = 236


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(tmp_path, environ={"DATA_DIR": str(tmp_path / "data")})


@pytest.fixture
def ingested(
    conn: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> tuple[sqlite3.Connection, Settings, IngestReport]:
    import_books(conn, settings.data_dir, eval_dir / "books")
    report = run_deterministic(
        conn, settings, BOOK, spine_path=eval_dir / "spine_mowgli_brothers.json"
    )
    return conn, settings, report


def test_report_counts(ingested: tuple[sqlite3.Connection, Settings, IngestReport]) -> None:
    _, _, report = ingested
    assert (report.chapters, report.story_chapters, report.beats) == (14, 7, 5)
    assert report.chunks > 20


def test_every_chunk_is_an_exact_slice_inside_its_beat(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport],
) -> None:
    conn, settings, _ = ingested
    repo = ContentRepo(conn)
    cleaned = load_cleaned(settings.data_dir, repo.get_book(BOOK))  # type: ignore[arg-type]
    beats = {b.idx: b for b in repo.get_beats(BOOK, 0)}
    chunks = repo.get_chunks(BOOK, 0)
    assert chunks
    for c in chunks:
        assert cleaned.text[c.start_char : c.end_char] == c.text
        assert (
            beats[c.beat_idx].start_char <= c.start_char < c.end_char <= beats[c.beat_idx].end_char
        )


def test_rerunning_without_the_spine_keeps_beats_and_rebuilds_chunks(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport],
) -> None:
    conn, settings, first = ingested
    again = run_deterministic(conn, settings, BOOK)
    assert (again.beats, again.chunks) == (first.beats, first.chunks)


def test_chunk_size_comes_from_settings(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport], tmp_path: Path
) -> None:
    conn, settings, first = ingested
    small = load_settings(
        tmp_path,
        environ={"DATA_DIR": str(settings.data_dir), "CHUNK_TARGET_CHARS": "400"},
    )
    again = run_deterministic(conn, small, BOOK)
    assert again.chunks > first.chunks


def test_a_changed_raw_file_is_refused(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport],
) -> None:
    conn, settings, _ = ingested
    (settings.data_dir / "books" / str(BOOK) / "raw.txt").write_text("tampered")
    with pytest.raises(IngestionError, match="hash"):
        run_deterministic(conn, settings, BOOK)


def test_unknown_book_is_refused(conn: sqlite3.Connection, settings: Settings) -> None:
    with pytest.raises(IngestionError, match="catalog import"):
        run_deterministic(conn, settings, 999)


def hits(conn: sqlite3.Connection, query: str, beat: int) -> list[int]:
    return [h.beat_idx for h in search_chunks(conn, BOOK, query, Position(0, beat), limit=20)]


def test_chapter_titles_are_not_part_of_any_chunk(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport],
) -> None:
    conn, _, _ = ingested
    chunks = ContentRepo(conn).get_chunks(BOOK, 0)
    assert not any(c.text.startswith("Mowgli\u2019s Brothers") for c in chunks)
    assert chunks[0].text.startswith("Now Rann the Kite")


def test_a_character_not_yet_met_has_no_passages(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport],
) -> None:
    conn, _, _ = ingested
    assert hits(conn, "Who is Mowgli?", beat=0) == []
    assert hits(conn, "Who is Mowgli?", beat=1)


def test_spoiler_filter_on_the_real_book(
    ingested: tuple[sqlite3.Connection, Settings, IngestReport],
) -> None:
    conn, _, _ = ingested
    assert hits(conn, "Red Flower", beat=1) == []
    found = hits(conn, "Red Flower", beat=3)
    assert found
    assert max(found) <= 3
    assert hits(conn, "Bagheera", beat=1) == []
    assert 2 in hits(conn, "Bagheera", beat=2)
    assert set(hits(conn, "Mowgli", beat=0)) <= {0}
