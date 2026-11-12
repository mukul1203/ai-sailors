"""The ingestion run: deterministic stages, then the optional LLM stages, then chunking.

Every LLM stage is recorded per chapter in `ingestion_steps` with a hash of its input, so a
rerun skips finished work and resumes after a failure. Hand-written (spine) beats and beats a
human approved are never overwritten unless `force` is set, and a published book needs `force`
for any LLM stage.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from storyquest.config import Settings
from storyquest.domain.book import Beat, Chapter, Entity
from storyquest.ingestion.beatgen import generate_beat, next_hint, with_spoilers
from storyquest.ingestion.entities import extract_from_beat, merge_into
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.pipeline import Prepared, build_chunks, prepare
from storyquest.ingestion.segment import compare_boundaries, segment_chapter
from storyquest.ingestion.validate import check_beat
from storyquest.ingestion.version import pipeline_version
from storyquest.models.llm import LLMClient, LLMError
from storyquest.stores.content_repo import ContentRepo

SEGMENT, GENERATE, VALIDATE, ENTITIES = "segment", "generate", "validate", "entities"
LLM_STAGES = (SEGMENT, GENERATE, ENTITIES)  # validation runs inside generation
_BY_NUMBER = {"5": SEGMENT, "6": GENERATE, "7": VALIDATE, "8": ENTITIES}
_ALL_NAMES = {SEGMENT, GENERATE, VALIDATE, ENTITIES}

Log = Callable[[str], None]


@dataclass(frozen=True)
class RunOptions:
    stages: tuple[str, ...] = ()  # the LLM stages to run; the deterministic ones always run
    chapter: int | None = None  # only this chapter
    force: bool = False  # redo finished steps and overwrite approved or hand-written beats
    dry_run: bool = False  # preview the segmentation; change no beats or chunks
    spine_path: Path | None = None


@dataclass
class RunReport:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    beats: int = 0
    chunks: int = 0


def parse_stages(text: str) -> tuple[str, ...]:
    """'deterministic' (none), 'llm' or 'all' (segment, generate, entities), a stage name or its
    number (5 segment, 6 generate, 7 validate, 8 entities), or a comma-separated list."""
    chosen: list[str] = []
    for part in (p.strip().lower() for p in text.split(",") if p.strip()):
        if part == "deterministic":
            continue
        if part in ("llm", "all"):
            chosen += LLM_STAGES
            continue
        name = _BY_NUMBER.get(part, part)
        if name not in _ALL_NAMES:
            raise IngestionError(
                f"Unknown stage {part!r}; use deterministic, llm, all, segment (5), generate (6), "
                "validate (7) or entities (8)"
            )
        chosen.append(name)
    return tuple(dict.fromkeys(chosen))


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def scene_text(text: str, chapter: Chapter, beat: Beat) -> str:
    """The beat's words, without the chapter's title line."""
    start = beat.start_char
    if start <= chapter.start_char:
        newline = text.find("\n", chapter.start_char)
        start = newline + 1 if newline >= 0 else start
    return text[start : beat.end_char].strip()


class _Run:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        llm: LLMClient | None,
        prepared: Prepared,
        options: RunOptions,
        log: Log,
    ) -> None:
        self.repo = ContentRepo(conn)
        self.settings = settings
        self.llm = llm
        self.prepared = prepared
        self.book = prepared.book
        self.text = prepared.cleaned.text
        self.options = options
        self.log = log
        self.version = pipeline_version(settings)
        self.report = RunReport()

    # helpers

    def _lines(self, start: int, end: int) -> str:
        c = self.prepared.cleaned
        return f"{c.line_at(start)}-{c.line_at(max(start, end - 1))}"

    def _already_done(self, chapter: Chapter, step: str, input_hash: str) -> bool:
        row = self.repo.get_step(self.book.id, chapter.idx, step)
        done = row is not None and row["status"] == "done" and row["input_hash"] == input_hash
        if done and not self.options.force:
            self.report.skipped.append(f"{step} ch{chapter.idx}")
            self.log(f"{step:<8} ch{chapter.idx} {chapter.title!r}: already done, skipped")
            return True
        return False

    def _record(
        self, chapter: Chapter, step: str, input_hash: str, status: str, detail: str
    ) -> None:
        self.repo.record_step(
            self.book.id, chapter.idx, step,
            pipeline_version=self.version, input_hash=input_hash, status=status, detail=detail,
        )  # fmt: skip
        (self.report.ran if status == "done" else self.report.failed).append(
            f"{step} ch{chapter.idx}"
        )

    def _client(self) -> LLMClient:
        if self.llm is None:
            raise IngestionError("This stage needs the model, but no LLM client was given")
        return self.llm

    def _protected(self, beats: list[Beat]) -> bool:
        return any(b.source == "spine" or b.review_status == "approved" for b in beats)

    # stage 5

    def segment(self, chapter: Chapter) -> None:
        existing = self.repo.get_beats(self.book.id, chapter.idx)
        if (
            existing
            and self._protected(existing)
            and not self.options.force
            and not self.options.dry_run  # a dry run may compare with the hand-written beats
        ):
            self.log(
                f"segment  ch{chapter.idx} {chapter.title!r}: keeping {len(existing)} "
                "hand-written or approved beats (use force to replace)"
            )
            self.report.skipped.append(f"segment ch{chapter.idx}")
            return
        body = self.text[chapter.start_char : chapter.end_char]
        input_hash = _digest(self.version, body)
        if (
            not self.options.dry_run
            and existing
            and self._already_done(chapter, SEGMENT, input_hash)
        ):
            return
        beats, seg = segment_chapter(
            self._client(), self.book.title, chapter, self.text, self.settings, self.version
        )
        sizes = ", ".join(str(b.end_char - b.start_char) for b in beats)
        self.log(
            f"segment  ch{chapter.idx} {chapter.title!r}: {len(beats)} beats "
            f"({len(seg.proposed)} proposed by the model); sizes {sizes}"
        )
        for note in seg.notes:
            self.log(f"           note: {note}")
        if self.options.dry_run:
            for b in beats:
                self.log(
                    f"           B{b.idx + 1} raw lines {self._lines(b.start_char, b.end_char)}"
                )
            if existing:
                pairs = compare_boundaries(beats, existing)
                hits = sum(1 for _, near in pairs if near is not None)
                self.log(
                    f"           compared with the {len(existing)} existing beats: "
                    f"{hits} of {len(pairs)} boundaries within 1,500 characters"
                )
            return
        self.repo.replace_beats(self.book.id, chapter.idx, beats)
        self._record(chapter, SEGMENT, input_hash, "done", json.dumps(seg.notes))

    # stages 6 and 7

    def generate(self, chapter: Chapter) -> None:
        beats = self.repo.get_beats(self.book.id, chapter.idx)
        todo = [
            b for b in beats
            if b.source == "llm" and (b.review_status != "approved" or self.options.force)
        ]  # fmt: skip
        if not todo:
            self.log(f"generate ch{chapter.idx} {chapter.title!r}: no generated beats to write")
            return
        input_hash = _digest(self.version, [(b.start_char, b.end_char) for b in todo])
        if self._already_done(chapter, GENERATE, input_hash):
            return
        later_titles = [c.title for c in self.prepared.stories if c.idx > chapter.idx]
        done: dict[int, Beat] = {}
        for beat in todo:
            nxt = beats[beat.idx + 1] if beat.idx + 1 < len(beats) else None
            filled = generate_beat(
                self._client(),
                book_title=self.book.title,
                author=self.book.author,
                chapter_title=chapter.title,
                base=beat,
                scene=scene_text(self.text, chapter, beat),
                next_hint=next_hint(scene_text(self.text, chapter, nxt) if nxt else None),
                has_next=nxt is not None,
                settings=self.settings,
            )
            done[beat.idx] = filled
            status = f"{len(filled.flags)} flag(s)" if filled.flags else "ok"
            self.log(f"generate ch{chapter.idx} B{beat.idx + 1} {filled.title!r}: {status}")
        merged = [done.get(b.idx, b) for b in beats]
        for beat in with_spoilers(merged, later_titles):
            if beat.idx in done:
                self.repo.update_beat(self.book.id, beat)
        flagged = sum(1 for b in done.values() if b.flags)
        self._record(chapter, GENERATE, input_hash, "done", f"{len(done)} beats, {flagged} flagged")

    def validate(self, chapter: Chapter) -> None:
        beats = [b for b in self.repo.get_beats(self.book.id, chapter.idx) if b.source == "llm"]
        flagged = 0
        for beat in beats:
            scene = scene_text(self.text, chapter, beat)
            flags = [p.message for p in check_beat(beat, scene)]
            flagged += bool(flags)
            self.repo.update_beat(self.book.id, replace(beat, flags=flags))
        self.log(
            f"validate ch{chapter.idx} {chapter.title!r}: {len(beats)} beats checked, "
            f"{flagged} flagged"
        )

    # stage 8

    def entities(self, chapter: Chapter) -> None:
        beats = self.repo.get_beats(self.book.id, chapter.idx)
        if not beats:
            return
        input_hash = _digest(self.version, [(b.start_char, b.end_char) for b in beats])
        if self._already_done(chapter, ENTITIES, input_hash):
            return
        known: dict[str, Entity] = {
            e.key: e for e in self.repo.get_entities(self.book.id) if e.card_chapter != chapter.idx
        }
        before = len(known)
        book_start = self.prepared.chapters[0].start_char
        notes: list[str] = []
        for beat in beats:
            items = extract_from_beat(
                self._client(),
                book_title=self.book.title,
                author=self.book.author,
                scene=scene_text(self.text, chapter, beat),
            )
            notes += merge_into(
                known, items, text=self.text, book_start=book_start,
                chapter_idx=chapter.idx, beat=beat,
            )  # fmt: skip
        self.repo.replace_entities_from_chapter(self.book.id, chapter.idx, list(known.values()))
        self.log(
            f"entities ch{chapter.idx} {chapter.title!r}: {len(known) - before} new, "
            f"{len(known)} in the book, {len(notes)} dropped"
        )
        self._record(chapter, ENTITIES, input_hash, "done", json.dumps(notes))

    # the run

    def run(self) -> RunReport:
        chapters = self.prepared.stories
        if self.options.chapter is not None:
            chapters = [c for c in chapters if c.idx == self.options.chapter]
            if not chapters:
                raise IngestionError(f"Chapter {self.options.chapter} is not a story chapter")
        steps = {
            SEGMENT: self.segment, GENERATE: self.generate,
            VALIDATE: self.validate, ENTITIES: self.entities,
        }  # fmt: skip
        order = [s for s in (SEGMENT, GENERATE, VALIDATE, ENTITIES) if s in self.options.stages]
        for chapter in chapters:
            for stage in order:
                if self.options.dry_run and stage != SEGMENT:
                    continue
                try:
                    steps[stage](chapter)
                except (LLMError, ValueError) as e:
                    self._record(chapter, stage, "", "failed", str(e))
                    self.log(f"{stage:<8} ch{chapter.idx} FAILED: {e}")
        return self.report


def run_ingestion(
    conn: sqlite3.Connection,
    settings: Settings,
    llm: LLMClient | None,
    book_id: int,
    options: RunOptions,
    log: Log = lambda _: None,
) -> RunReport:
    repo = ContentRepo(conn)
    book = repo.get_book(book_id)
    if book is None:
        raise IngestionError(f"Book {book_id} is not in the catalog; run `catalog import` first")
    uses_llm = bool(options.stages)
    if uses_llm and book.status == "ready" and not options.force:
        raise IngestionError(
            f"Book {book_id} is published, and published beats are not edited in place. "
            "Use force to rebuild it."
        )
    if uses_llm and not options.dry_run:
        repo.set_book_status(book_id, "ingesting")
    prepared = prepare(conn, settings, book_id, spine_path=options.spine_path, log=log)
    report = _Run(conn, settings, llm, prepared, options, log).run()
    if not options.dry_run:
        report.beats, report.chunks = build_chunks(conn, settings, prepared, log)
        if uses_llm and report.failed:
            repo.set_book_status(book_id, "failed")
    return report
