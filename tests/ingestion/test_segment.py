import re
from dataclasses import replace

import pytest
from stage_llm import StageLLM

from storyquest.config import Settings
from storyquest.domain.book import Chapter
from storyquest.ingestion.segment import (
    chapter_paragraphs,
    compare_boundaries,
    make_beats,
    plan_starts,
    propose_starts,
    segment_chapter,
)
from storyquest.ingestion.text import Cleaned

pytestmark = pytest.mark.integration


@pytest.fixture
def first_story(jungle: tuple[Cleaned, list[Chapter]]) -> tuple[str, Chapter]:
    cleaned, chapters = jungle
    return cleaned.text, next(c for c in chapters if c.included)


def _check_partition(text: str, chapter: Chapter, beats: list) -> None:  # type: ignore[type-arg]
    assert beats[0].start_char == chapter.start_char and beats[-1].end_char == chapter.end_char
    for a, b in zip(beats, beats[1:], strict=False):
        assert a.end_char == b.start_char
        before = text[max(0, b.start_char - 200) : b.start_char]
        assert re.search(r"\n[ \t]*\n\Z", before)  # each beat starts at a paragraph start


def test_the_beats_partition_the_chapter(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    beats, seg = segment_chapter(StageLLM(), "The Jungle Book", chapter, text, settings, "v1")
    assert len(beats) > 2 and seg.proposed
    _check_partition(text, chapter, beats)
    sizes = [b.end_char - b.start_char for b in beats]
    assert min(sizes) >= settings.beat_min_chars and max(sizes) <= settings.beat_max_chars
    assert all(b.source == "llm" and b.review_status == "draft" for b in beats)
    assert [b.title for b in beats][:2] == ["Part 1", "Part 2"]  # stage 6 names them


def test_proposals_are_chosen_for_beats_close_to_the_target_size(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    paragraphs = chapter_paragraphs(text, chapter)
    everything = list(range(1, len(paragraphs)))  # a boundary after every paragraph
    starts, notes = plan_starts(chapter, paragraphs, everything, settings)
    beats = make_beats(chapter, paragraphs, starts, "v1")
    sizes = [b.end_char - b.start_char for b in beats]
    assert all(settings.beat_min_chars <= s <= settings.beat_max_chars for s in sizes)
    assert abs(sum(sizes) / len(sizes) - settings.beat_target_chars) < 1500
    assert notes and "kept" in notes[0]


def test_without_usable_proposals_the_chapter_is_cut_by_size(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    llm = StageLLM()
    llm.mode = "garbage"
    beats, seg = segment_chapter(llm, "The Jungle Book", chapter, text, settings, "v1")
    _check_partition(text, chapter, beats)
    assert seg.proposed == [] and any("cut by size" in n for n in seg.notes)
    assert all(b.end_char - b.start_char <= settings.beat_max_chars for b in beats)


def test_out_of_range_proposals_are_ignored(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    paragraphs = chapter_paragraphs(text, chapter)
    starts, _ = plan_starts(chapter, paragraphs, [0, -4, 9999, 5], settings)
    assert starts[0] == 0 and all(0 <= s < len(paragraphs) for s in starts)


def test_small_proposals_are_merged_and_huge_beats_split(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    paragraphs = chapter_paragraphs(text, chapter)
    tight = replace(settings, beat_min_chars=10**9, beat_max_chars=10**10)  # no subset fits
    starts, notes = plan_starts(chapter, paragraphs, [1, 2, 3], tight)
    assert starts == [0] and any("merged" in n for n in notes)
    narrow = replace(settings, beat_max_chars=5000, beat_min_chars=1000)
    starts, _ = plan_starts(chapter, paragraphs, [], narrow)
    beats = make_beats(chapter, paragraphs, starts, "v1")
    assert len(beats) > 3 and all(b.end_char - b.start_char <= 5000 for b in beats)


def test_a_short_chapter_is_one_beat_without_asking_the_model(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    short = replace(chapter, end_char=chapter.start_char + 3000)
    llm = StageLLM()
    beats, _ = segment_chapter(llm, "The Jungle Book", short, text, settings, "v1")
    assert len(beats) == 1 and not llm.calls


def test_the_model_sees_windows_not_the_whole_chapter(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    paragraphs = chapter_paragraphs(text, chapter)
    llm = StageLLM()
    propose_starts(llm, "The Jungle Book", chapter, text, paragraphs, settings)
    assert len(llm.calls) >= 2
    longest = max(len(c[0]["content"]) for c in llm.calls)
    assert longest < 16000  # roughly 4,000 tokens: the 8,192 limit is respected with room to spare


def test_comparison_with_existing_beats(
    first_story: tuple[str, Chapter], settings: Settings
) -> None:
    text, chapter = first_story
    paragraphs = chapter_paragraphs(text, chapter)
    ours = make_beats(chapter, paragraphs, [0, 10, 20], "v1")
    theirs = make_beats(chapter, paragraphs, [0, 10, 40], "v1")
    pairs = compare_boundaries(ours, theirs, tolerance=1)
    assert pairs[0][1] == pairs[0][0]  # the shared boundary matches
    assert pairs[1][1] is None  # too far from any of ours
