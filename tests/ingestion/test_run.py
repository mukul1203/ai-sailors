import json
import sqlite3
from pathlib import Path

import pytest
from stage_llm import StageLLM

from storyquest.catalog.importer import import_books
from storyquest.config import Settings
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.review import (
    approve_beats,
    publish,
    publish_problems,
    render_review,
)
from storyquest.ingestion.run import RunOptions, parse_stages, run_ingestion
from storyquest.ingestion.status import render_entities, render_status
from storyquest.ingestion.worker import run_worker
from storyquest.stores.content_repo import ContentRepo

pytestmark = pytest.mark.integration

BOOK = 236
LLM = parse_stages("llm")


@pytest.fixture
def book(conn: sqlite3.Connection, settings: Settings, eval_dir: Path) -> sqlite3.Connection:
    import_books(conn, settings.data_dir, eval_dir / "books")
    return conn


def full_run(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path, llm: StageLLM, **kw: object
):  # type: ignore[no-untyped-def]
    options = RunOptions(
        stages=LLM,
        spine_path=eval_dir / "spine_mowgli_brothers.json",
        **kw,  # type: ignore[arg-type]
    )
    return run_ingestion(book, settings, llm, BOOK, options)


def test_stage_names_and_numbers() -> None:
    assert parse_stages("deterministic") == ()
    assert parse_stages("llm") == parse_stages("all") == ("segment", "generate", "entities")
    assert parse_stages("5,6") == ("segment", "generate")
    assert parse_stages("validate, entities") == ("validate", "entities")
    with pytest.raises(IngestionError, match="Unknown stage"):
        parse_stages("polish")


def test_llm_stages_build_beats_chunks_and_entities_but_keep_the_hand_written_chapter(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    llm = StageLLM()
    report = full_run(book, settings, eval_dir, llm)
    repo = ContentRepo(book)
    chapters = [c for c in repo.get_chapters(BOOK) if c.included]
    assert not report.failed and report.beats > 5 and report.chunks > 50

    spine = repo.get_beats(BOOK, 0)
    assert len(spine) == 5 and {b.source for b in spine} == {"spine"}
    assert {b.review_status for b in spine} == {"approved"}

    for chapter in chapters[1:]:
        beats = repo.get_beats(BOOK, chapter.idx)
        assert len(beats) >= 3, chapter.title
        assert all(b.source == "llm" and b.title.startswith("Scene ") for b in beats)
        assert all(b.review_status == "draft" and not b.flags for b in beats)
        assert beats[0].spoiler_reveals[-1] == chapters[-1].title or chapter is chapters[-1]
        assert {c.beat_idx for c in repo.get_chunks(BOOK, chapter.idx)} == {b.idx for b in beats}

    entities = {e.key: e for e in repo.get_entities(BOOK)}
    assert list(entities) == ["mowgli"]  # the made-up name was dropped
    assert entities["mowgli"].first_char < chapters[1].start_char
    assert ContentRepo(book).get_book(BOOK).status == "ingesting"  # type: ignore[union-attr]


def test_a_second_run_does_nothing_and_force_redoes_it(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    llm = StageLLM()
    full_run(book, settings, eval_dir, llm)
    first_calls = len(llm.calls)
    again = full_run(book, settings, eval_dir, llm)
    assert len(llm.calls) == first_calls and again.skipped and not again.ran
    forced = full_run(book, settings, eval_dir, llm, force=True, chapter=2)
    assert len(llm.calls) > first_calls and forced.ran


def test_changing_the_chapters_clears_what_was_built_on_them(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    full_run(book, settings, eval_dir, StageLLM())
    repo = ContentRepo(book)
    chapters = repo.get_chapters(BOOK)
    repo.replace_chapters(BOOK, chapters)
    assert repo.list_steps(BOOK) == [] and repo.get_entities(BOOK) == []


def test_only_the_chosen_chapter_is_processed(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    report = full_run(book, settings, eval_dir, StageLLM(), chapter=2)
    assert {s.split()[1] for s in report.ran} == {"ch2"}
    repo = ContentRepo(book)
    assert repo.get_beats(BOOK, 2) and not repo.get_beats(BOOK, 4)


def test_a_failure_is_recorded_and_the_next_run_resumes(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    llm = StageLLM()
    llm.mode = "down"
    report = full_run(book, settings, eval_dir, llm, chapter=2)
    repo = ContentRepo(book)
    assert report.failed and repo.get_book(BOOK).status == "failed"  # type: ignore[union-attr]
    assert {s["status"] for s in repo.list_steps(BOOK)} == {"failed"}

    llm.mode = "good"
    report = full_run(book, settings, eval_dir, llm, chapter=2)
    assert not report.failed and {s["status"] for s in repo.list_steps(BOOK)} == {"done"}


def test_a_dry_run_previews_boundaries_and_changes_nothing(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    llm = StageLLM()
    lines: list[str] = []
    options = RunOptions(
        stages=LLM,
        dry_run=True,
        chapter=0,
        spine_path=eval_dir / "spine_mowgli_brothers.json",
    )
    report = run_ingestion(book, settings, llm, BOOK, options, log=lines.append)
    assert {StageLLM._kind(c) for c in llm.calls} == {"segment"}
    assert any("compared with the 5 existing beats" in line for line in lines)
    repo = ContentRepo(book)
    assert report.chunks == 0 and repo.count_chunks(BOOK) == 0 and repo.list_steps(BOOK) == []
    assert repo.get_book(BOOK).status == "allowlisted"  # type: ignore[union-attr]


def test_flagged_beats_are_not_approved_in_bulk_and_block_publishing(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    llm = StageLLM()
    llm.mode = "bad_quotes"
    full_run(book, settings, eval_dir, llm, chapter=2)
    first = approve_beats(book, BOOK, chapter_idx=2)
    assert first.approved == 0 and first.flagged_left >= 3

    text = render_review(book, settings.data_dir, BOOK, 2)
    assert "FLAGGED" in text and "clue(s) dropped" in text

    named = approve_beats(book, BOOK, chapter_idx=2, beat_idx=0)
    assert named.approved == 1
    forced = approve_beats(book, BOOK, chapter_idx=2, include_flagged=True)
    assert forced.approved >= 2
    problems = publish_problems(book, BOOK)
    assert any("chapter 4" in p and "no beats" in p for p in problems)  # other chapters are empty


def test_a_fully_approved_book_can_be_published_and_is_then_protected(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    llm = StageLLM()
    full_run(book, settings, eval_dir, llm)
    assert publish(book, BOOK)  # drafts are not approved yet
    result = approve_beats(book, BOOK)
    assert result.approved > 10 and result.flagged_left == 0
    assert publish(book, BOOK) == []
    repo = ContentRepo(book)
    assert repo.get_book(BOOK).status == "ready"  # type: ignore[union-attr]
    with pytest.raises(IngestionError, match="published"):
        full_run(book, settings, eval_dir, llm)
    full_run(book, settings, eval_dir, llm, force=True, chapter=2)  # deliberate rebuild


def test_validate_stage_rechecks_stored_beats(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    full_run(book, settings, eval_dir, StageLLM(), chapter=2)
    repo = ContentRepo(book)
    beat = repo.get_beats(BOOK, 2)[0]
    book.execute(
        "UPDATE beats SET narration = 'Short.' WHERE book_id = ? AND chapter_idx = 2 AND idx = 0",
        (BOOK,),
    )
    options = RunOptions(stages=parse_stages("validate"), chapter=2)
    run_ingestion(book, settings, None, BOOK, options)
    after = repo.get_beats(BOOK, 2)
    assert beat.flags == [] and any("narration" in f for f in after[0].flags)
    assert after[1].flags == []


def test_the_worker_runs_queued_jobs(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    repo = ContentRepo(book)
    options = {
        "stages": list(LLM),
        "chapter": 2,
        "spine": str(eval_dir / "spine_mowgli_brothers.json"),
    }
    job = repo.enqueue_job(BOOK, options)
    bad = repo.enqueue_job(BOOK, {"stages": ["segment"], "chapter": 3})  # a poem
    lines: list[str] = []
    handled = run_worker(book, settings, StageLLM(), once=True, log=lines.append)
    assert handled == 2
    states = {j["id"]: j["status"] for j in book.execute("SELECT * FROM ingestion_jobs")}
    assert states == {job: "done", bad: "failed"}
    assert repo.get_beats(BOOK, 2)
    assert run_worker(book, settings, StageLLM(), once=True) == 0


def test_status_and_entity_views(
    book: sqlite3.Connection, settings: Settings, eval_dir: Path
) -> None:
    full_run(book, settings, eval_dir, StageLLM(), chapter=2)
    status = render_status(book, settings, BOOK)
    assert "segment" in status and "ch2" in status and "Pipeline version now: v" in status
    assert "Entities: 1" in status
    text = render_entities(book, settings, BOOK)
    assert "Mowgli [character]" in text and "A boy raised by wolves." in text
    assert json.loads(json.dumps(parse_stages("5")))
