"""Cleaning: drop the Gutenberg header and footer and keep a map back to raw line numbers."""

import bisect
import re
from dataclasses import dataclass

from storyquest.ingestion.errors import IngestionError

_START = re.compile(
    r"^\*\*\* START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .*\*\*\*[ \t]*$", re.MULTILINE
)
_END = re.compile(
    r"^\*\*\* END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK .*\*\*\*[ \t]*$", re.MULTILINE
)


@dataclass(frozen=True)
class Cleaned:
    """The book text between Gutenberg's markers, unmodified apart from line endings.

    All offsets in the database are character offsets into `text`.
    """

    text: str
    first_line: int  # line number in the raw file where `text` begins (1-based)
    starts: tuple[int, ...]  # offset where each line of `text` begins

    def line_at(self, offset: int) -> int:
        """The raw-file line number containing this offset."""
        return bisect.bisect_right(self.starts, offset) - 1 + self.first_line

    def offset_of_line(self, raw_line: int) -> int:
        """The offset where a raw-file line begins."""
        i = raw_line - self.first_line
        if i < 0:
            raise IngestionError(f"line {raw_line} is before the start of the book text")
        return self.starts[i] if i < len(self.starts) else len(self.text)


def clean(raw: str) -> Cleaned:
    raw = raw.replace("\r\n", "\n")
    start = _START.search(raw)
    end = _END.search(raw)
    if start is None or end is None or end.start() < start.end():
        raise IngestionError("Gutenberg START/END markers not found; is this a Gutenberg text?")
    body_start = start.end() + 1  # skip the newline after the marker line
    text = raw[body_start : end.start()]
    first_line = raw.count("\n", 0, body_start) + 1
    starts = (0, *(i + 1 for i, ch in enumerate(text) if ch == "\n"))
    return Cleaned(text=text, first_line=first_line, starts=starts)


def normalize_title(title: str) -> str:
    """Compare titles ignoring curly-vs-straight quotes and case."""
    table = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})
    return title.translate(table).strip().lower()
