from dataclasses import replace

from storyquest.domain.book import Beat
from storyquest.ingestion.validate import (
    check_beat,
    normalise,
    quote_in_text,
    reading_grade,
    safety_hits,
    vocabulary_in_text,
)

SCENE = (
    "\u201cHe has no right!\u201d Father Wolf began angrily. \u201cBy the Law of the Jungle he "
    "has no right to change his quarters without due warning.\u201d\n\nTabaqui, the jackal, "
    "laughed and ran away into the dark."
)
GOOD = Beat(
    chapter_idx=0,
    idx=0,
    title="A Warning At The Cave",
    narration="Father Wolf is angry. A tiger has come to his hills without warning. "
    "Tabaqui the jackal laughs and runs away.",
    start_char=0,
    end_char=len(SCENE),
    clues=["The tiger came without warning", "Tabaqui is a jackal"],
    clue_quotes=[
        "he has no right to change his quarters without due warning",
        "Tabaqui, the jackal, laughed",
    ],
    vocabulary=["quarters", "jackal"],
    choice={
        "prompt": "What should Father Wolf do?",
        "cards": [
            {"id": "B1-a", "text": "Go and see", "next": "B2", "canon": True},
            {"id": "B1-b", "text": "Stay home", "next": "B2", "canon": False},
        ],
    },
    source="llm",
)


def test_a_good_beat_has_no_problems() -> None:
    assert check_beat(GOOD, SCENE) == []


def test_quotes_ignore_case_spacing_and_curly_quotes() -> None:
    scene = normalise(SCENE)
    assert quote_in_text("\u201cHe has no right!\u201d Father Wolf began", scene)
    assert quote_in_text("BY THE LAW  OF THE JUNGLE", scene)
    assert not quote_in_text("By the Law of the Sea", scene)
    assert not quote_in_text("too short", scene)  # under 12 characters


def test_vocabulary_must_occur_in_the_scene() -> None:
    scene = normalise(SCENE)
    assert vocabulary_in_text("Jackal", scene) and not vocabulary_in_text("dragon", scene)


def test_a_clue_quote_that_is_not_in_the_text_is_a_retryable_problem() -> None:
    bad = replace(GOOD, clue_quotes=["Shere Khan roared loudly", "x"])
    problems = check_beat(bad, SCENE)
    assert any("not in the scene text" in p.message and p.retry for p in problems)


def test_other_problems() -> None:
    def with_(**changes: object) -> list[str]:
        return [p.message for p in check_beat(replace(GOOD, **changes), SCENE)]  # type: ignore[arg-type]

    assert any("no title" in m for m in with_(title="Part 1"))
    assert any("narration" in m for m in with_(narration="Too short."))
    assert any("vocabulary not in the scene" in m for m in with_(vocabulary=["quarters", "dragon"]))
    assert any("choice" in m for m in with_(choice={"prompt": "", "cards": []}))
    assert any(
        "no choice option" in m
        for m in with_(choice={"prompt": "What now?", "cards": [{"text": "a"}, {"text": "b"}]})
    )
    assert any("safety" in m for m in with_(clues=["There was blood", "Tabaqui is a jackal"]))


def test_reading_grade_rises_with_harder_text() -> None:
    easy = "The cat sat. The dog ran. We like it."
    hard = (
        "The extraordinarily consequential deliberations concerning jurisdictional "
        "responsibilities continued throughout the afternoon."
    )
    assert reading_grade(easy) < 3 < 10 < reading_grade(hard)


def test_safety_screen_finds_listed_words_only() -> None:
    assert safety_hits(["A bloody fight", "all fine"]) == ["bloody"]
    assert (
        safety_hits(["The tiger will kill the deer"]) == []
    )  # the book's own violence is not screened


def test_beats_that_share_a_title_are_flagged() -> None:
    from storyquest.ingestion.validate import duplicate_title_flags

    beats = [
        replace(GOOD, idx=0, title="Kotick's Big Adventure"),
        replace(GOOD, idx=1, title="Another Scene"),
        replace(GOOD, idx=2, title="kotick's big  adventure"),
        replace(GOOD, idx=3, title="Part 4"),
        replace(GOOD, idx=4, title="Part 4"),
    ]
    assert duplicate_title_flags(beats) == {2: "the title repeats the title of B1"}
