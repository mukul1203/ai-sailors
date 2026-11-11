import pytest

from storyquest.ingestion.errors import IngestionError
from storyquest.ingestion.text import clean, normalize_title

RAW = (
    "Header\r\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\r\nline one\r\n\r\nline three\r\n"
    "*** END OF THE PROJECT GUTENBERG EBOOK X ***\r\nfooter\r\n"
)


def test_clean_keeps_only_the_text_between_markers() -> None:
    c = clean(RAW)
    assert c.text == "line one\n\nline three\n"


def test_offsets_map_back_to_raw_line_numbers() -> None:
    c = clean(RAW)
    third = c.text.index("line three")
    assert c.first_line == 3
    assert c.line_at(0) == 3
    assert c.line_at(third) == 5
    assert c.offset_of_line(5) == third
    assert c.offset_of_line(99) == len(c.text)


def test_line_before_the_text_is_rejected() -> None:
    with pytest.raises(IngestionError):
        clean(RAW).offset_of_line(1)


@pytest.mark.parametrize("raw", ["no markers here", "*** END OF THE PROJECT GUTENBERG EBOOK X ***"])
def test_missing_markers_are_an_error(raw: str) -> None:
    with pytest.raises(IngestionError, match="markers"):
        clean(raw)


def test_normalize_title_ignores_quote_style_and_case() -> None:
    assert normalize_title("Mowgli\u2019s Brothers") == normalize_title("mowgli's brothers")
