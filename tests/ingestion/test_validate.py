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
        "prompt": "Father Wolf springs at the bushes. What does he find there?",
        "cards": [
            {"id": "B1-a", "text": "A tiny human baby", "next": "B2", "canon": True},
            {"id": "B1-b", "text": "A hungry jackal", "next": "B2", "canon": False},
            {"id": "B1-c", "text": "Shere Khan the tiger", "next": "B2", "canon": False},
        ],
        "hints": ["It is not an enemy.", "It is small, brown and has no fur."],
    },
    source="llm",
)
NEXT = (
    "Directly in front of him, holding on by a low branch, stood a naked brown baby who could "
    "just walk. He looked up into Father Wolf's face, and laughed."
)


def test_a_good_beat_has_no_problems() -> None:
    assert check_beat(GOOD, SCENE, NEXT) == []
    assert check_beat(GOOD, SCENE) == []  # without the next text, only its shape is checked


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
    assert any("question" in m for m in with_(choice={"prompt": "", "cards": []}))
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


def with_choice(**changes: object) -> list[str]:
    from storyquest.ingestion.validate import check_question

    choice = {**GOOD.choice, **changes}
    return [p.message for p in check_question(replace(GOOD, choice=choice), NEXT)]


def test_the_right_answer_must_come_from_the_next_text() -> None:
    cards = [
        {"id": "a", "text": "A hungry jackal", "canon": True},
        {"id": "b", "text": "A tiny human baby", "canon": False},
    ]
    assert any("NEXT text" in m for m in with_choice(cards=cards))  # the baby is in the text
    swapped = [{**cards[0], "canon": False}, {**cards[1], "canon": True}]
    assert not any("NEXT text" in m for m in with_choice(cards=swapped))


def test_matching_ignores_word_endings() -> None:
    from storyquest.ingestion.validate import content_words

    assert content_words("jumps") == content_words("jumped")
    assert content_words("drums") == content_words("drumming")


def test_a_question_needs_one_right_answer_two_hints_and_no_giveaways() -> None:
    cards = GOOD.choice["cards"]
    assert any("exactly one" in m for m in with_choice(cards=[{**c, "canon": True} for c in cards]))
    assert any("two hints" in m for m in with_choice(hints=["only one"]))
    assert any(
        "gives the right answer away" in m
        for m in with_choice(hints=["Look for a tiny human baby.", "x"])
    )
    assert any(
        "different and short" in m
        for m in with_choice(cards=[cards[0], {**cards[1], "text": "A tiny human baby"}, cards[2]])
    )
    assert any(
        "not about 'the text'" in m or "about the story" in m
        for m in with_choice(prompt="What happens at the very start of the next text?")
    )


def test_an_answer_copied_from_the_text_or_told_in_the_narration_is_refused() -> None:
    from storyquest.ingestion.validate import check_question

    copied = [
        {"id": "a", "text": "stood a naked brown baby who could just walk", "canon": True},
        {"id": "b", "text": "A hungry jackal", "canon": False},
    ]
    assert any(
        "own words" in p.message
        for p in check_question(replace(GOOD, choice={**GOOD.choice, "cards": copied}), NEXT)
    )
    told = replace(GOOD, narration="Father Wolf finds a tiny human baby in the bushes tonight.")
    assert any("tells the answer" in p.message for p in check_question(told, NEXT))


def test_the_retelling_must_be_a_story_with_complete_sentences() -> None:
    from storyquest.ingestion.validate import check_retell

    meta = replace(GOOD, narration="The scene begins with Father Wolf. He is angry at Shere Khan.")
    assert any("never say 'the scene'" in p.message for p in check_retell(meta, SCENE))
    cut = replace(
        GOOD, narration="Father Wolf is angry because Shere Khan came without warning and the"
    )
    assert any("cut off" in p.message for p in check_retell(cut, SCENE))
