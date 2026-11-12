"""The ingestion worker: runs queued jobs, and the options a job is stored with."""

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from storyquest.config import Settings
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.run import RunOptions, run_ingestion
from storyquest.models.llm import LLMClient, LLMError
from storyquest.stores.content_repo import ContentRepo

Log = Callable[[str], None]


def options_to_json(options: RunOptions) -> dict[str, Any]:
    return {
        "stages": list(options.stages),
        "chapter": options.chapter,
        "force": options.force,
        "dry_run": options.dry_run,
        "spine": str(options.spine_path) if options.spine_path else None,
    }


def options_from_json(data: dict[str, Any]) -> RunOptions:
    return RunOptions(
        stages=tuple(data.get("stages", [])),
        chapter=data.get("chapter"),
        force=bool(data.get("force")),
        dry_run=bool(data.get("dry_run")),
        spine_path=Path(data["spine"]) if data.get("spine") else None,
    )


def run_worker(
    conn: sqlite3.Connection,
    settings: Settings,
    llm: LLMClient | None,
    *,
    once: bool = False,
    poll_seconds: float = 5.0,
    log: Log = lambda _: None,
) -> int:
    """Process queued ingestion jobs one at a time. Returns how many it handled. With `once`
    it stops when the queue is empty; otherwise it waits for new jobs."""
    repo = ContentRepo(conn)
    handled = 0
    while True:
        job = repo.claim_job()
        if job is None:
            if once:
                return handled
            time.sleep(poll_seconds)
            continue
        log(f"job {job['id']}: book {job['book_id']}")
        try:
            options = options_from_json(json.loads(job["options"]))
            report = run_ingestion(conn, settings, llm, job["book_id"], options, log)
        except (IngestionError, LLMError, ValueError) as e:
            repo.finish_job(job["id"], "failed", str(e))
            log(f"job {job['id']} failed: {e}")
        else:
            summary = f"{len(report.ran)} steps run, {len(report.skipped)} skipped"
            repo.finish_job(job["id"], "failed" if report.failed else "done", summary)
            log(f"job {job['id']} finished: {summary}, {len(report.failed)} failed")
        handled += 1
