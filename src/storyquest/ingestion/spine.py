"""Load a hand-written spine (reference beats) and map its line numbers to text offsets."""

import json
import re
from pathlib import Path
from typing import Any

from storyquest.domain.book import Beat, Chapter
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.text import Cleaned, normalize_title


def _starts_paragraph(text: str, offset: int) -> bool:
    return re.search(r"\n[ \t]*\n\Z", text[max(0, offset - 200) : offset]) is not None


def load_spine(path: Path, cleaned: Cleaned, chapters: list[Chapter]) -> tuple[int, list[Beat]]:
    """Returns (chapter index, beats). Beats are made to partition the whole chapter."""
    data: dict[str, Any] = json.loads(path.read_text())
    wanted = normalize_title(data["chapter"])
    chapter = next((c for c in chapters if normalize_title(c.title) == wanted), None)
    if chapter is None:
        raise IngestionError(f"Spine chapter {data['chapter']!r} not found in the book")

    spine_beats: list[dict[str, Any]] = data["beats"]
    starts = [cleaned.offset_of_line(int(b["source_lines"].split("-")[0])) for b in spine_beats]
    starts[0] = chapter.start_char
    if any(a >= b for a, b in zip(starts, starts[1:], strict=False)):
        raise IngestionError("Spine beats are out of order or overlap")
    if starts[-1] >= chapter.end_char:
        raise IngestionError("Spine beats run past the end of the chapter")
    for beat, start in zip(spine_beats[1:], starts[1:], strict=True):
        if not _starts_paragraph(cleaned.text, start):
            line = cleaned.line_at(start)
            raise IngestionError(
                f"Beat {beat['id']} starts mid-paragraph (raw line {line}); "
                "move it to the first line of a paragraph"
            )
    ends = [*starts[1:], chapter.end_char]

    beats = [
        Beat(
            chapter_idx=chapter.idx,
            idx=i,
            title=b["title"],
            narration=b["narration_summary"],
            start_char=start,
            end_char=end,
            clues=b["clues"],
            vocabulary=b["vocabulary"],
            choice=b["choice"],
            spoiler_reveals=b["spoiler_reveals"],
            review_status="approved",
            source="spine",
        )
        for i, (b, start, end) in enumerate(zip(spine_beats, starts, ends, strict=True))
    ]
    return chapter.idx, beats
