import json
from dataclasses import replace

from stage_llm import StageLLM

from storyquest.config import Settings, load_settings
from storyquest.domain.book import Beat
from storyquest.ingestion.beatgen import (
    beat_from_answer,
    drop_untraceable,
    generate_beat,
    with_spoilers,
)

SCENE = (
    "\u201cHe has no right!\u201d Father Wolf began angrily. \u201cBy the Law of the Jungle he "
    "has no right to change his quarters without due warning. He will frighten every head of "
    "game within ten miles.\u201d Tabaqui, the jackal, laughed and ran away into the dark."
)
BASE = Beat(0, 0, "Part 1", "", 0, len(SCENE), source="llm", pipeline_version="v1")


def settings(tmp_path: object = None) -> Settings:
    return load_settings(environ={"INGEST_RETRIES": "2"})


def run(llm: StageLLM, scene: str = SCENE, has_next: bool = True) -> Beat:
    return generate_beat(
        llm,
        book_title="The Jungle Book",
        author="Kipling",
        chapter_title="Mowgli's Brothers",
        base=BASE,
        scene=scene,
        next_hint="Mowgli arrives.",
        has_next=has_next,
        settings=settings(),
    )


def test_a_good_answer_fills_the_beat_without_flags() -> None:
    llm = StageLLM()
    beat = run(llm)
    assert beat.title.startswith("Scene ") and beat.narration
    assert len(beat.clues) == len(beat.clue_quotes) == 3
    assert beat.flags == [] and len(llm.calls) == 1
    assert beat.review_status == "draft" and beat.source == "llm" and beat.pipeline_version == "v1"
    cards = beat.choice["cards"]
    assert [c["id"] for c in cards] == ["B1-a", "B1-b"] and cards[1]["canon"] is True
    assert cards[0]["next"] == "B2"
    assert run(StageLLM(), has_next=False).choice["cards"][0]["next"] == "end"


def test_untraceable_quotes_are_retried_then_dropped_and_flagged() -> None:
    llm = StageLLM()
    llm.mode = "bad_quotes"
    beat = run(llm)
    assert len(llm.calls) == 3  # one try and two retries
    assert (
        "Fix them" in llm.calls[1][0]["content"]
        and "not in the scene text" in (llm.calls[1][0]["content"])
    )
    assert beat.clues == [] and beat.flags  # dropped, never kept untraceable
    assert any("dropped" in f for f in beat.flags) and any("clue" in f for f in beat.flags)


def test_an_unreadable_answer_leaves_a_flagged_empty_beat() -> None:
    llm = StageLLM()
    llm.mode = "garbage"
    beat = run(llm)
    assert len(llm.calls) == 3
    assert beat.narration == "" and beat.flags == ["generation failed: no usable answer"]


def test_a_wrong_shape_is_rejected() -> None:
    assert beat_from_answer({"title": "x"}, BASE, has_next=True) is None
    assert (
        beat_from_answer(
            {"clues": [], "vocabulary": [], "choice_options": "x"}, BASE, has_next=True
        )
        is None
    )


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
    beat = run(llm, scene=SCENE + " " + "word " * 4000)
    sent = llm.calls[0][0]["content"]
    assert len(sent) < 14000 and any("cut to fit" in f for f in beat.flags)


def test_spoilers_are_what_comes_later() -> None:
    beats = [
        replace(BASE, idx=i, title=t, clues=[f"clue {i}"])
        for i, t in enumerate(["One", "Two", "Three"])
    ]
    out = with_spoilers(beats, ["Later Chapter"])
    assert out[0].spoiler_reveals == ["Two", "Three", "clue 1", "clue 2", "Later Chapter"]
    assert out[2].spoiler_reveals == ["Later Chapter"]
    assert json.dumps(out[1].spoiler_reveals)
