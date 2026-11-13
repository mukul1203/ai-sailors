"""Chapter detection from the book's own Contents list, plus story-vs-poem labelling."""

import re
from difflib import SequenceMatcher
from statistics import mean

from storyquest.domain.book import Chapter
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.text import Cleaned


def _contents_titles(lines: list[str]) -> tuple[list[str], int]:
    """Titles listed under 'Contents', and the line index just after that block."""
    try:
        i = next(n for n, line in enumerate(lines) if line.strip().lower() == "contents")
    except StopIteration:
        raise IngestionError("No 'Contents' list found; add chapter boundaries by hand") from None
    titles: list[str] = []
    blanks = 0
    j = i + 1
    while j < len(lines):
        line = " ".join(lines[j].split())
        if line:
            titles.append(line)
            blanks = 0
        else:
            blanks += 1
            if titles and blanks >= 2:
                break
        j += 1
    if not titles:
        raise IngestionError("The Contents list is empty")
    return titles, j


def classify(body: str, *, short_chars: int) -> str:
    """'poem' for short interludes or text made of short indented lines, else 'story'.

    A heuristic: a story collection with very short stories would be mislabelled, so an admin
    reviews the labels (`inspect`) before a book is published.
    """
    lines = [line for line in body.split("\n") if line.strip()]
    if not lines or len(body) < short_chars:
        return "poem"
    indented = sum(1 for line in lines if line[0] in " \t") / len(lines)
    average = mean(len(line.strip()) for line in lines)
    return "poem" if indented > 0.5 or average < 45 else "story"


def _key(text: str) -> str:
    """A title with case, punctuation and spacing ignored, to compare headings loosely."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


FUZZY_MATCH = 0.9  # similarity for headings that differ from the Contents list by a typo
_MARKER = re.compile(r"^((?:chapter|book|part|story)\s+(?:[ivxlc]+|\d+))\b")


def _heading_end_line(lines: list[str], start: int, key: str, *, fuzzy: bool = False) -> int | None:
    """If a heading with this normalised title starts at line `start` (on one line, or split over
    up to three non-blank lines, as in "CHAPTER I." then "Down the Rabbit-Hole"), the index of
    its last line; otherwise None. With `fuzzy`, a title that differs by a typo also matches."""
    if not lines[start].strip():
        return None  # a heading starts on a line with text
    parts: list[str] = []
    for j in range(start, min(len(lines), start + 6)):
        if not lines[j].strip():
            continue
        parts.append(_key(lines[j]))
        joined = " ".join(p for p in parts if p)
        if joined == key:
            return j
        if fuzzy and len(joined) >= len(key) - 3:
            if SequenceMatcher(None, joined, key).ratio() >= FUZZY_MATCH:
                return j
        if not fuzzy and not key.startswith(joined):
            return None
        if len(parts) == 3 or len(joined) > len(key) + 6:
            return None
    return None


def heading_end(text: str, chapter: Chapter) -> int:
    """Where the chapter's title block ends: the story text starts after it."""
    window = text[chapter.start_char : chapter.start_char + 600]
    lines = window.split("\n")
    last = _heading_end_line(lines, 0, _key(chapter.title))
    if last is None:
        last = 0
    return chapter.start_char + sum(len(line) + 1 for line in lines[: last + 1])


def detect_chapters(
    cleaned: Cleaned, *, short_chapter_chars: int, book_title: str = "Story"
) -> list[Chapter]:
    """The chapters named by the Contents list, each found in the text. A book with no Contents
    list is one chapter holding the whole story."""
    lines = cleaned.text.split("\n")
    try:
        titles, pos = _contents_titles(lines)
    except IngestionError:
        if "contents" in cleaned.text[:5000].lower():
            raise
        whole = Chapter(0, book_title, "story", 0, len(cleaned.text))
        return [whole]  # no chapters to find: the book is one story
    heading_lines: list[int] = []
    for title in titles:
        key = _key(title)
        k = next(
            (n for n in range(pos, len(lines)) if _heading_end_line(lines, n, key) is not None),
            None,
        )
        marker = _MARKER.match(key)
        if k is None and marker:  # "Chapter XI" alone, when the title is worded differently
            k = next(
                (
                    n
                    for n in range(pos, len(lines))
                    if lines[n].strip()
                    and _key(lines[n]).startswith(marker.group(1))
                    and _key(lines[n]).split()[:2] == marker.group(1).split()
                ),
                None,
            )
        if k is None:  # the book may spell it differently from its own Contents list
            k = next(
                (
                    n
                    for n in range(pos, len(lines))
                    if _heading_end_line(lines, n, key, fuzzy=True) is not None
                ),
                None,
            )
        if k is None:
            raise IngestionError(f"Heading not found in the text: {title!r}")
        heading_lines.append(k)
        pos = k + 1

    starts = [cleaned.starts[k] for k in heading_lines]
    ends = [*starts[1:], len(cleaned.text)]
    return [
        _chapter(cleaned, idx, title, start, end, short_chapter_chars)
        for idx, (title, start, end) in enumerate(zip(titles, starts, ends, strict=True))
    ]


def _chapter(
    cleaned: Cleaned, idx: int, title: str, start: int, end: int, short_chars: int
) -> Chapter:
    chapter = Chapter(idx, title, "story", start, end)
    body = cleaned.text[heading_end(cleaned.text, chapter) : end]
    kind = classify(body, short_chars=short_chars)
    return Chapter(idx, title, kind, start, end, included=kind == "story")
