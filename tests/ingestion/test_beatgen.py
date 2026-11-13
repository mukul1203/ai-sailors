import json
from dataclasses import replace

from stage_llm import StageLLM

from storyquest.config import Settings, load_settings
from storyquest.domain.book import Beat
from storyquest.ingestion.beatgen import (
    drop_untraceable,
    generate_beat,
    peek,
    question_from_answer,
    retell_from_answer,
    with_spoilers,
)

SCENE = (
    "\u201cHe has no right!\u201d Father Wolf began angrily. \u201cBy the Law of the Jungle he "
    "has no right to change his quarters without due warning. He will frighten every head of "
    "game within ten miles.\u201d Tabaqui, the jackal, laughed and ran away into the dark."
)
NEXT = (
    "Directly in front of him, holding on by a low branch, stood a naked brown baby who could "
    "just walk. He looked up into Father Wolf's face, and laughed."
)
BASE = Beat(2, 3, "Part 4", "", 0, len(SCENE), source="llm", pipeline_version="v1")


def settings() -> Settings:
    return load_settings(environ={"INGEST_RETRIES": "2"})


def run(llm: StageLLM, *, has_next: bool = True, previous: str = "") -> Beat:
    return generate_beat(
        llm,
        book_title="The Jungle Book",
        author="Kipling",
        chapter_title="Mowgli's Brothers",
        base=BASE,
        scene=SCENE,
        next_text=NEXT,
        has_next=has_next,
        previous_narration=previous,
        settings=settings(),
    )


def test_a_good_run_makes_two_calls_and_a_clean_beat() -> None:
    llm = StageLLM()
    beat = run(llm)
    assert llm.calls_of("beat") == 1 and llm.calls_of("question") == 1
    assert beat.title.startswith("Scene ") and beat.narration
    assert len(beat.clues) == len(beat.clue_quotes) == 3 and beat.flags == []
    assert beat.review_status == "draft" and beat.source == "llm" and beat.pipeline_version == "v1"
    choice = beat.choice
    assert len(choice["cards"]) == 3 and len(choice["hints"]) == 2
    assert [c["id"] for c in choice["cards"]] == ["B4-a", "B4-b", "B4-c"]
    assert sum(c["canon"] for c in choice["cards"]) == 1  # one right answer
    right = next(c for c in choice["cards"] if c["canon"])
    assert right["text"] == "Directly front holding"  # taken from the NEXT text
    assert all(c["next"] == "B5" for c in choice["cards"])
    assert run(StageLLM(), has_next=False).choice["cards"][0]["next"] == "end"


def test_the_story_so_far_and_the_next_text_reach_the_right_prompts() -> None:
    llm = StageLLM()
    run(llm, previous="Father Wolf woke up in his cave.")
    retell, question = llm.calls[0][0]["content"], llm.calls[1][0]["content"]
    assert "Father Wolf woke up in his cave." in retell and "do not repeat that" in retell
    first = StageLLM()
    run(first)
    assert "first scene" in first.calls[0][0]["content"]
    assert NEXT.split(".")[0] in question and "<next>" in question
    assert NEXT.split(".")[0] not in retell  # the retelling never sees what the child must guess


def test_the_last_beat_is_told_to_stop_before_its_closing_words() -> None:
    llm = StageLLM()
    run(llm, has_next=False)
    assert "never tell them" in llm.calls[0][0]["content"]


def test_untraceable_quotes_are_retried_then_dropped_and_flagged() -> None:
    llm = StageLLM()
    llm.mode = "bad_quotes"
    beat = run(llm)
    assert llm.calls_of("beat") == 3  # one try and two retries
    retry = llm.calls[1][0]["content"]
    assert "Fix them" in retry and "not in the scene text" in retry
    assert beat.clues == [] and any("dropped" in f for f in beat.flags)


def test_a_right_answer_that_is_not_in_the_next_text_is_retried_and_flagged() -> None:
    llm = StageLLM()
    llm.mode = "bad_answer"
    beat = run(llm)
    assert llm.calls_of("question") == 3
    assert any("NEXT text" in f for f in beat.flags)
    assert beat.narration and beat.clues  # the retelling is kept: only the question failed


def test_an_unreadable_answer_leaves_a_flagged_empty_beat() -> None:
    llm = StageLLM()
    llm.mode = "garbage"
    beat = run(llm)
    assert llm.calls_of("beat") == 3 and llm.calls_of("question") == 0
    assert beat.narration == "" and beat.flags == ["generation failed: no usable answer"]


def test_wrong_shapes_are_rejected() -> None:
    assert retell_from_answer({"title": "x"}, BASE) is None
    assert question_from_answer({"question": "x"}, BASE, has_next=True) is None


def test_the_right_answer_is_not_always_first() -> None:
    positions = set()
    for idx in range(12):
        data = {
            "question": "Q?",
            "answer": f"right {idx}",
            "wrong_answers": ["wrong one", "wrong two"],
            "hint_1": "a",
            "hint_2": "b",
        }
        beat = question_from_answer(data, replace(BASE, idx=idx), has_next=True)
        assert beat is not None
        positions.add([c["canon"] for c in beat.choice["cards"]].index(True))
    assert len(positions) > 1


def test_untraceable_clues_and_words_are_dropped() -> None:
    beat = replace(
        BASE,
        clues=["kept", "lost"],
        clue_quotes=["he has no right to change his quarters", "a sentence from elsewhere"],
        vocabulary=["jackal", "dragon"],
    )
    fixed, notes = drop_untraceable(beat, SCENE)
    assert fixed.clues == ["kept"] and fixed.vocabulary == ["jackal"] and len(notes) == 2


def test_the_scene_is_cut_to_fit_the_model_limit() -> None:
    llm = StageLLM()
    beat = generate_beat(
        llm,
        book_title="b",
        author="a",
        chapter_title="c",
        base=BASE,
        scene=SCENE + " " + "word " * 4000,
        next_text=NEXT,
        has_next=True,
        settings=settings(),
    )
    assert len(llm.calls[0][0]["content"]) < 14000 and any("cut to fit" in f for f in beat.flags)


def test_the_question_looks_at_the_next_scene_or_the_closing_words() -> None:
    assert peek("  next   scene text ", SCENE) == "next scene text"
    assert peek(None, SCENE) == " ".join(SCENE.split())[:700]
    assert len(peek("x " * 2000, SCENE)) == 700


def test_spoilers_are_what_comes_later() -> None:
    beats = [
        replace(BASE, idx=i, title=t, clues=[f"clue {i}"])
        for i, t in enumerate(["One", "Two", "Three"])
    ]
    out = with_spoilers(beats, ["Later Chapter"])
    assert out[0].spoiler_reveals == ["Two", "Three", "clue 1", "clue 2", "Later Chapter"]
    assert out[2].spoiler_reveals == ["Later Chapter"]
    assert json.dumps(out[1].spoiler_reveals)
