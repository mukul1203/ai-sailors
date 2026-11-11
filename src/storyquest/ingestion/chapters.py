"""Chapter detection from the book's own Contents list, plus story-vs-poem labelling."""

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
        line = lines[j].strip()
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


def detect_chapters(cleaned: Cleaned, *, short_chapter_chars: int) -> list[Chapter]:
    lines = cleaned.text.split("\n")
    titles, pos = _contents_titles(lines)
    heading_lines: list[int] = []
    for title in titles:
        try:
            k = next(n for n in range(pos, len(lines)) if lines[n].strip() == title)
        except StopIteration:
            raise IngestionError(f"Heading not found in the text: {title!r}") from None
        heading_lines.append(k)
        pos = k + 1

    starts = [cleaned.starts[k] for k in heading_lines]
    ends = [*starts[1:], len(cleaned.text)]
    chapters = []
    for idx, (title, start, end) in enumerate(zip(titles, starts, ends, strict=True)):
        body = cleaned.text[start:end].split("\n", 1)[1] if "\n" in cleaned.text[start:end] else ""
        kind = classify(body, short_chars=short_chapter_chars)
        chapters.append(Chapter(idx, title, kind, start, end, included=kind == "story"))
    return chapters
