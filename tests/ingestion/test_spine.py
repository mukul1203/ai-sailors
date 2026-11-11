import json
from pathlib import Path

import pytest

from storyquest.domain.book import Chapter
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.spine import load_spine
from storyquest.ingestion.text import Cleaned

pytestmark = pytest.mark.integration


def test_spine_beats_partition_the_whole_chapter(
    jungle: tuple[Cleaned, list[Chapter]], eval_dir: Path
) -> None:
    cleaned, chapters = jungle
    chapter_idx, beats = load_spine(eval_dir / "spine_mowgli_brothers.json", cleaned, chapters)
    chapter = chapters[chapter_idx]
    assert chapter.title == "Mowgli\u2019s Brothers"
    assert len(beats) == 5
    assert beats[0].start_char == chapter.start_char
    assert beats[-1].end_char == chapter.end_char
    assert all(a.end_char == b.start_char for a, b in zip(beats, beats[1:], strict=False))
    assert [cleaned.line_at(b.start_char) for b in beats] == [56, 194, 292, 408, 645]
    assert beats[0].review_status == "approved"
    assert beats[0].choice["cards"]


def write_spine(tmp_path: Path, eval_dir: Path, **changes: object) -> Path:
    data = json.loads((eval_dir / "spine_mowgli_brothers.json").read_text())
    data.update({k: v for k, v in changes.items() if k != "b3_lines"})
    if "b3_lines" in changes:
        data["beats"][2]["source_lines"] = changes["b3_lines"]
    path = tmp_path / "spine.json"
    path.write_text(json.dumps(data))
    return path


def test_a_beat_starting_mid_paragraph_is_rejected(
    jungle: tuple[Cleaned, list[Chapter]], eval_dir: Path, tmp_path: Path
) -> None:
    cleaned, chapters = jungle
    spine = write_spine(tmp_path, eval_dir, b3_lines="290-406")
    with pytest.raises(IngestionError, match="mid-paragraph"):
        load_spine(spine, cleaned, chapters)


def test_unknown_chapter_is_rejected(
    jungle: tuple[Cleaned, list[Chapter]], eval_dir: Path, tmp_path: Path
) -> None:
    cleaned, chapters = jungle
    spine = write_spine(tmp_path, eval_dir, chapter="No Such Chapter")
    with pytest.raises(IngestionError, match="not found"):
        load_spine(spine, cleaned, chapters)
