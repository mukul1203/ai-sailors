from pathlib import Path

import pytest

from storyquest.domain.book import Chapter
from storyquest.ingestion.chapters import detect_chapters
from storyquest.ingestion.text import Cleaned, clean


@pytest.fixture(scope="session")
def jungle(eval_dir: Path) -> tuple[Cleaned, list[Chapter]]:
    raw = (eval_dir / "books" / "236-the-jungle-book" / "raw.txt").read_text()
    cleaned = clean(raw)
    return cleaned, detect_chapters(cleaned, short_chapter_chars=3500)
