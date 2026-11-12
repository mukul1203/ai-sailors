"""Stage 5: cut a story chapter into beats.

The model proposes which paragraphs begin a new scene, a window of paragraph openings at a time
(a chapter does not fit in one call). Code then decides: it keeps only valid paragraph numbers,
merges beats that are too short, splits beats that are too long, and builds beats that start at
paragraph starts and together cover the whole chapter. A bad model answer therefore costs
quality, never correctness; with no usable answer the chapter is cut by size alone.
"""

import json
from dataclasses import dataclass
from typing import Any

from storyquest.config import Settings
from storyquest.domain.book import Beat, Chapter
from storyquest.ingestion.chunking import Span, paragraph_spans
from storyquest.ingestion.prompts import load_prompt
from storyquest.models.llm import LLMClient

MAX_TOKENS = 200
PREVIEW_CHARS = 160
CHARS_PER_WORD = 5.5


@dataclass(frozen=True)
class Segmentation:
    starts: list[int]  # paragraph indexes where beats begin; the first is always 0
    proposed: list[int]  # the model's valid proposals, before merging and splitting
    notes: list[str]  # what code had to fix, for the log and the step record


def chapter_paragraphs(text: str, chapter: Chapter) -> list[Span]:
    """The chapter's paragraphs, without its title line."""
    return paragraph_spans(
        text, chapter.start_char + _title_length(text, chapter), chapter.end_char
    )


def _title_length(text: str, chapter: Chapter) -> int:
    newline = text.find("\n", chapter.start_char)
    return 0 if newline < 0 else newline + 1 - chapter.start_char


def _preview(text: str, span: Span) -> str:
    flat = " ".join(text[span[0] : span[1]].split())
    words = len(flat.split())
    head = flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 1] + "…"
    return f"{head} ({words} words)"


def _read_starts(text: str, low: int, high: int) -> list[int] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    listed = data.get("starts") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        return None
    return sorted(
        {n for n in listed if isinstance(n, int) and not isinstance(n, bool) and low <= n <= high}
    )


def propose_starts(
    llm: LLMClient,
    book_title: str,
    chapter: Chapter,
    text: str,
    paragraphs: list[Span],
    settings: Settings,
) -> tuple[list[int], list[str]]:
    """Ask the model, window by window, where scenes begin. Returns (paragraph numbers, notes)."""
    proposed: set[int] = set()
    notes: list[str] = []
    size = settings.segment_window_paragraphs
    for low in range(0, len(paragraphs), size):
        high = min(low + size, len(paragraphs)) - 1
        chars = paragraphs[high][1] - paragraphs[low][0]
        if chars < settings.beat_min_chars:
            continue  # too little text for a boundary to be useful
        shown = "\n".join(f"[{i}] {_preview(text, paragraphs[i])}" for i in range(low, high + 1))
        prompt = load_prompt("segment").format(
            title=book_title,
            chapter=chapter.title,
            first=low,
            last=high,
            target_words=round(settings.beat_target_chars / CHARS_PER_WORD),
            expected=max(1, round(chars / settings.beat_target_chars)),
            paragraphs=shown,
        )
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "starts": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": low, "maximum": high},
                    "maxItems": 12,
                }
            },
            "required": ["starts"],
            "additionalProperties": False,
        }
        result = llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            json_schema=schema,
        )
        starts = _read_starts(result.text, low, high)
        if starts is None:
            notes.append(f"paragraphs {low}-{high}: the answer could not be read, ignored")
            continue
        proposed.update(starts)
    return sorted(proposed), notes


def _edges(chapter: Chapter, paragraphs: list[Span], starts: list[int]) -> list[int]:
    """Character offsets of every beat boundary, including the chapter's start and end."""
    inner = [paragraphs[i][0] for i in starts[1:]]
    return [chapter.start_char, *inner, chapter.end_char]


def _best_subset(
    chapter: Chapter, paragraphs: list[Span], candidates: list[int], settings: Settings
) -> list[int] | None:
    """The subset of candidate starts whose beats are closest to the target size, with every
    beat between the minimum and maximum. None if no subset satisfies the limits."""
    points = [0, *candidates]  # paragraph indexes; 0 is the chapter start
    edge = [chapter.start_char, *(paragraphs[i][0] for i in candidates), chapter.end_char]
    last = len(points)  # index of the chapter end in `edge`
    best: dict[int, tuple[float, int]] = {0: (0.0, -1)}  # edge index -> (cost, previous)
    for j in range(1, last + 1):
        for i in range(j):
            if i not in best:
                continue
            size = edge[j] - edge[i]
            if not settings.beat_min_chars <= size <= settings.beat_max_chars:
                continue
            cost = best[i][0] + (size - settings.beat_target_chars) ** 2
            if j not in best or cost < best[j][0]:
                best[j] = (cost, i)
    if last not in best:
        return None
    chosen: list[int] = []
    at = best[last][1]
    while at > 0:
        chosen.append(points[at])
        at = best[at][1]
    return [0, *reversed(chosen)]


def plan_starts(
    chapter: Chapter, paragraphs: list[Span], proposed: list[int], settings: Settings
) -> tuple[list[int], list[str]]:
    """Turn the model's proposals into a valid list of beat starts."""
    notes: list[str] = []
    candidates = sorted({p for p in proposed if 0 < p < len(paragraphs)})
    if candidates and (picked := _best_subset(chapter, paragraphs, candidates, settings)):
        dropped = len(candidates) - (len(picked) - 1)
        if dropped:
            notes.append(f"kept {len(picked) - 1} of {len(candidates)} proposed boundaries")
        return picked, notes
    starts = sorted({0, *candidates})

    def sizes() -> list[int]:
        edges = _edges(chapter, paragraphs, starts)
        return [b - a for a, b in zip(edges, edges[1:], strict=False)]

    while len(starts) > 1:
        current = sizes()
        smallest = min(range(len(current)), key=current.__getitem__)
        if current[smallest] >= settings.beat_min_chars:
            break
        notes.append(f"merged a beat of only {current[smallest]} characters")
        del starts[smallest if smallest > 0 else 1]

    while True:
        current = sizes()
        too_big = [
            k
            for k, size in enumerate(current)
            if size > settings.beat_max_chars and _paragraph_count(starts, k, len(paragraphs)) > 1
        ]
        if not too_big:
            break
        k = too_big[0]
        edges = _edges(chapter, paragraphs, starts)
        middle = edges[k] + current[k] // 2
        first = starts[k] + 1
        last = starts[k + 1] if k + 1 < len(starts) else len(paragraphs)
        cut = min(range(first, last), key=lambda i: abs(paragraphs[i][0] - middle))
        starts.insert(k + 1, cut)
        notes.append(f"split a beat of {current[k]} characters at paragraph {cut}")
    return starts, notes


def _paragraph_count(starts: list[int], k: int, total: int) -> int:
    end = starts[k + 1] if k + 1 < len(starts) else total
    return end - starts[k]


def make_beats(
    chapter: Chapter, paragraphs: list[Span], starts: list[int], pipeline_version: str
) -> list[Beat]:
    edges = _edges(chapter, paragraphs, starts)
    return [
        Beat(
            chapter_idx=chapter.idx,
            idx=i,
            title=f"Part {i + 1}",
            narration="",
            start_char=a,
            end_char=b,
            review_status="draft",
            source="llm",
            pipeline_version=pipeline_version,
        )
        for i, (a, b) in enumerate(zip(edges, edges[1:], strict=False))
    ]


def segment_chapter(
    llm: LLMClient,
    book_title: str,
    chapter: Chapter,
    text: str,
    settings: Settings,
    pipeline_version: str,
) -> tuple[list[Beat], Segmentation]:
    paragraphs = chapter_paragraphs(text, chapter)
    if not paragraphs:
        raise ValueError(f"chapter {chapter.title!r} has no text")
    notes: list[str] = []
    proposed: list[int] = []
    if chapter.end_char - chapter.start_char > settings.beat_max_chars:
        proposed, notes = propose_starts(llm, book_title, chapter, text, paragraphs, settings)
        if not proposed:
            notes.append("no usable proposals: the chapter is cut by size alone")
    starts, fixes = plan_starts(chapter, paragraphs, proposed, settings)
    beats = make_beats(chapter, paragraphs, starts, pipeline_version)
    return beats, Segmentation(starts, proposed, [*notes, *fixes])


def compare_boundaries(
    proposed: list[Beat], existing: list[Beat], tolerance: int = 1500
) -> list[tuple[int, int | None]]:
    """For each existing beat start after the first, the nearest proposed start within
    `tolerance` characters (or None). Used to compare a dry run with hand-written beats."""
    ours = [b.start_char for b in proposed[1:]]
    pairs: list[tuple[int, int | None]] = []
    for beat in existing[1:]:
        near = min(ours, key=lambda s: abs(s - beat.start_char), default=None)
        ok = near is not None and abs(near - beat.start_char) <= tolerance
        pairs.append((beat.start_char, near if ok else None))
    return pairs
