import pytest

from storyquest.domain.book import Chapter
from storyquest.ingestion.chapters import classify, detect_chapters
from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.text import Cleaned, clean

PROSE = "\n".join(["This is a long ordinary prose line that wraps at about seventy chars."] * 130)
POEM = "\n".join(["     Short indented song line"] * 6)


def synthetic(contents: str = "First Story\nA Song\nSecond Story") -> Cleaned:
    listed = "\n".join(f"     {t}" for t in contents.split("\n"))
    return clean(
        "*** START OF THE PROJECT GUTENBERG EBOOK T ***\nTITLE\n\n\nContents\n\n"
        f"{listed}\n\n\n\nFirst Story\n\n{PROSE}\n\n\nA Song\n\n{POEM}\n\n"
        f"Second Story\n\n{PROSE}\n*** END OF THE PROJECT GUTENBERG EBOOK T ***\n"
    )


def test_chapters_follow_the_contents_list() -> None:
    cleaned = synthetic()
    chapters = detect_chapters(cleaned, short_chapter_chars=8000)
    assert [(c.title, c.kind, c.included) for c in chapters] == [
        ("First Story", "story", True),
        ("A Song", "poem", False),
        ("Second Story", "story", True),
    ]
    assert chapters[0].end_char == chapters[1].start_char
    assert chapters[1].end_char == chapters[2].start_char
    assert chapters[2].end_char == len(cleaned.text)
    assert cleaned.text[chapters[1].start_char :].startswith("A Song")


def test_a_title_missing_from_the_text_is_an_error() -> None:
    with pytest.raises(IngestionError, match="Heading not found"):
        detect_chapters(synthetic("First Story\nNo Such Chapter"), short_chapter_chars=8000)


def test_no_contents_list_is_an_error() -> None:
    cleaned = clean(
        "*** START OF THE PROJECT GUTENBERG EBOOK T ***\njust text\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK T ***\n"
    )
    with pytest.raises(IngestionError, match="Contents"):
        detect_chapters(cleaned, short_chapter_chars=8000)


def test_classify() -> None:
    assert classify(PROSE, short_chars=8000) == "story"
    assert classify(POEM, short_chars=8000) == "poem"
    assert classify("", short_chars=8000) == "poem"
    long_poem = "\n".join(["   a short line of verse"] * 600)
    assert classify(long_poem, short_chars=8000) == "poem"


def test_the_short_chapter_threshold_comes_from_the_caller() -> None:
    assert classify(PROSE, short_chars=8000) == "story"
    assert classify(PROSE, short_chars=20000) == "poem"


@pytest.mark.integration
def test_jungle_book_has_seven_stories_and_seven_poems(
    jungle: tuple[Cleaned, list[Chapter]],
) -> None:
    cleaned, chapters = jungle
    assert len(chapters) == 14
    assert [c.idx for c in chapters if not c.included] == [1, 3, 5, 7, 9, 11, 13]
    assert chapters[0].title == "Mowgli\u2019s Brothers"
    assert cleaned.line_at(chapters[0].start_char) == 56
    assert cleaned.line_at(chapters[1].start_char) == 830
    assert chapters[-1].title == "Parade Song of the Camp Animals"
    assert chapters[-1].end_char == len(cleaned.text)
