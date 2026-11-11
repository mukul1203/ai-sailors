from storyquest.ingestion.chunking import chunk_span

PARAGRAPH = "A short paragraph of text that is about eighty characters long, give or take. "


def paragraphs(n: int) -> str:
    return "\n\n".join(PARAGRAPH.strip() for _ in range(n))


def words(text: str) -> str:
    return "".join(text.split())


def test_paragraphs_are_packed_up_to_the_target_without_losing_text() -> None:
    text = paragraphs(40)
    spans = chunk_span(text, 0, len(text), target=500, max_len=1800)
    assert len(spans) > 3
    assert all(0 <= a < b <= len(text) for a, b in spans)
    assert all(b - a <= 500 + len(PARAGRAPH) for a, b in spans)
    assert words("".join(text[a:b] for a, b in spans)) == words(text)


def test_chunks_are_trimmed_exact_slices_in_order() -> None:
    text = "\n\n" + paragraphs(10) + "\n\n\n"
    spans = chunk_span(text, 0, len(text), target=300, max_len=1800)
    assert spans == sorted(spans)
    for a, b in spans:
        assert text[a:b] == text[a:b].strip()


def test_chunks_never_leave_the_span_they_are_made_from() -> None:
    text = paragraphs(30)
    start, end = text.index("\n\n", 400) + 2, text.index("\n\n", 1200) + 2
    spans = chunk_span(text, start, end, target=300, max_len=1800)
    assert spans
    assert all(start <= a and b <= end for a, b in spans)


def test_an_oversized_paragraph_is_split_on_sentences() -> None:
    sentence = "This sentence is exactly the kind of thing a book might say. "
    text = sentence * 50
    spans = chunk_span(text, 0, len(text), target=500, max_len=800)
    assert len(spans) > 4
    assert all(text[a:b].endswith(".") for a, b in spans)
    assert words("".join(text[a:b] for a, b in spans)) == words(text)


def test_empty_and_whitespace_spans_give_no_chunks() -> None:
    assert chunk_span("", 0, 0, target=1200, max_len=1800) == []
    assert chunk_span("   \n\n  ", 0, 7, target=1200, max_len=1800) == []


def test_a_smaller_target_gives_more_chunks() -> None:
    text = paragraphs(40)
    small = chunk_span(text, 0, len(text), target=300, max_len=1800)
    large = chunk_span(text, 0, len(text), target=1200, max_len=1800)
    assert len(small) > len(large)


def test_chunking_is_deterministic() -> None:
    text = paragraphs(25)
    first = chunk_span(text, 0, len(text), target=1200, max_len=1800)
    assert first == chunk_span(text, 0, len(text), target=1200, max_len=1800)
