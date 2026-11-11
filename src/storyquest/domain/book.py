from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Book:
    id: int  # Project Gutenberg ebook number
    title: str
    author: str
    raw_path: str
    content_sha256: str
    language: str = "en"
    age_band: str = ""
    summary: str = ""
    content_notes: str = ""
    visibility: str = "listed"
    status: str = "allowlisted"


@dataclass(frozen=True)
class Chapter:
    idx: int
    title: str
    kind: str  # story, poem, front or back
    start_char: int
    end_char: int
    included: bool = True


@dataclass(frozen=True)
class Beat:
    chapter_idx: int
    idx: int
    title: str
    narration: str
    start_char: int
    end_char: int
    clues: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)
    choice: dict[str, Any] = field(default_factory=dict)
    spoiler_reveals: list[str] = field(default_factory=list)
    review_status: str = "draft"


@dataclass(frozen=True)
class Chunk:
    chapter_idx: int
    beat_idx: int
    idx: int  # order within the beat
    text: str
    start_char: int
    end_char: int
