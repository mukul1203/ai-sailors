"""Stage 6: generate the content of each beat, in two small calls the 8B model can do well.

1. Retell: title, a storyteller's narration of the scene, clues (each with a quote copied from the
   scene) and vocabulary. It sees the previous beat's narration, so names and the thread carry
   over, and for the last beat of a chapter it is told not to reveal the closing words.
2. Question: sees only the narration just written and the start of the NEXT scene, and writes a
   guessing question about what happens next, with the right answer in simple words, two wrong
   answers and two hints. The next beat then really does open with that event, so the quest
   connects: the child guesses, is told yes, and the story goes on from there.

Stage 7 checks each call's output against the text; a call that fails is asked again with the
problems listed, then kept with its flags if it still fails, so the human reviewer sees it first.
"""

import dataclasses
import json
import random
from typing import Any

from storyquest.config import Settings
from storyquest.domain.book import Beat
from storyquest.ingestion.prompts import load_prompt
from storyquest.ingestion.validate import (
    Problem,
    check_question,
    check_retell,
    normalise,
    quote_in_text,
    vocabulary_in_text,
)
from storyquest.models.llm import LLMClient

MAX_TOKENS = 900  # the endpoint allows at most 1024 output tokens
MAX_SCENE_CHARS = 12000  # about 3,000 tokens: with the prompt and answer, inside the 8,192 limit
NEXT_PEEK_CHARS = 700

_STRING_ARRAY: dict[str, Any] = {"type": "array", "items": {"type": "string"}}

RETELL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "narration": {"type": "string"},
        "clues": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {"quote": {"type": "string"}, "clue": {"type": "string"}},
                "required": ["quote", "clue"],
                "additionalProperties": False,
            },
        },
        "vocabulary": {**_STRING_ARRAY, "maxItems": 5},
    },
    "required": ["title", "narration", "clues", "vocabulary"],
    "additionalProperties": False,
}

QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "wrong_answers": {**_STRING_ARRAY, "minItems": 2, "maxItems": 2},
        "hint_1": {"type": "string"},
        "hint_2": {"type": "string"},
    },
    "required": ["question", "answer", "wrong_answers", "hint_1", "hint_2"],
    "additionalProperties": False,
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _feedback(problems: list[Problem]) -> str:
    lines = "\n".join(f"- {p.message}" for p in problems if p.retry)
    return f"\nYour last answer had these problems. Fix them:\n{lines}\n" if lines else ""


def retell_from_answer(data: dict[str, Any], base: Beat) -> Beat | None:
    try:
        clue_items = [c for c in data["clues"] if isinstance(c, dict)]
        return dataclasses.replace(
            base,
            title=_text(data["title"]),
            narration=_text(data["narration"]),
            clues=[_text(c.get("clue")) for c in clue_items],
            clue_quotes=[_text(c.get("quote")) for c in clue_items],
            vocabulary=[_text(v) for v in data["vocabulary"] if _text(v)],
        )
    except (KeyError, TypeError):
        return None


def question_from_answer(data: dict[str, Any], base: Beat, *, has_next: bool) -> Beat | None:
    """Add the question to a beat. The right answer and the wrong ones are put in a fixed but
    shuffled order (models like to put the right one first), with ids like B3-a."""
    try:
        answer = _text(data["answer"])
        wrong = [_text(w) for w in data["wrong_answers"] if _text(w)]
        options = [(answer, True), *((w, False) for w in wrong)]
        random.Random(f"{base.chapter_idx}:{base.idx}:{answer}").shuffle(options)
        number = base.idx + 1
        cards = [
            {
                "id": f"B{number}-{chr(ord('a') + i)}",
                "text": text,
                "next": f"B{number + 1}" if has_next else "end",
                "canon": is_answer,
            }
            for i, (text, is_answer) in enumerate(options)
            if text
        ]
        choice = {
            "prompt": _text(data["question"]),
            "cards": cards,
            "hints": [_text(data["hint_1"]), _text(data["hint_2"])],
        }
        return dataclasses.replace(base, choice=choice)
    except (KeyError, TypeError):
        return None


def drop_untraceable(beat: Beat, scene: str) -> tuple[Beat, list[str]]:
    """Remove clues whose quote is not in the scene and vocabulary that does not occur in it."""
    scene_norm = normalise(scene)
    notes: list[str] = []
    kept = [
        (c, q)
        for c, q in zip(beat.clues, beat.clue_quotes, strict=False)
        if quote_in_text(q, scene_norm)
    ]
    if len(kept) < len(beat.clues):
        notes.append(f"{len(beat.clues) - len(kept)} clue(s) dropped: quote not in the text")
    words = [w for w in beat.vocabulary if vocabulary_in_text(w, scene_norm)]
    if len(words) < len(beat.vocabulary):
        notes.append(f"{len(beat.vocabulary) - len(words)} vocabulary word(s) dropped")
    fixed = dataclasses.replace(
        beat, clues=[c for c, _ in kept], clue_quotes=[q for _, q in kept], vocabulary=words
    )
    return fixed, notes


def peek(next_scene: str | None, scene: str) -> str:
    """What the question is about: the start of the next scene, or for the last beat of a
    chapter, the closing words of this scene."""
    source = next_scene if next_scene else scene[-NEXT_PEEK_CHARS:]
    return " ".join(source.split())[:NEXT_PEEK_CHARS]


def _retell(
    llm: LLMClient,
    *,
    book_title: str,
    author: str,
    chapter_title: str,
    base: Beat,
    scene: str,
    previous_narration: str,
    ending: str,
    settings: Settings,
) -> tuple[Beat | None, list[Problem]]:
    before = (
        f'Just before this scene the story told: "{previous_narration}"\n'
        "Use the same names, and do not repeat that.\n"
        if previous_narration
        else "This is the first scene of the chapter: begin by setting the scene (where, when).\n"
    )
    avoid = f'Stop before the closing words "{ending}" and never tell them.' if ending else ""
    best: tuple[int, Beat, list[Problem]] | None = None
    problems: list[Problem] = []
    for _ in range(settings.ingest_retries + 1):
        prompt = load_prompt("beat").format(
            title=book_title, author=author, chapter=chapter_title, before=before, avoid=avoid,
            feedback=_feedback(problems), scene=scene,
        )  # fmt: skip
        result = llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            json_schema=RETELL_SCHEMA,
        )
        data = _json(result.text)
        beat = retell_from_answer(data, base) if data is not None else None
        problems = (
            [Problem("the answer was not valid JSON of the expected shape", retry=True)]
            if beat is None
            else check_retell(beat, scene)
        )
        if beat is not None and (best is None or len(problems) < best[0]):
            best = (len(problems), beat, problems)
        if not any(p.retry for p in problems):
            break
    return (best[1], best[2]) if best else (None, problems)


def _ask(
    llm: LLMClient,
    *,
    book_title: str,
    beat: Beat,
    next_text: str,
    has_next: bool,
    settings: Settings,
) -> tuple[Beat, list[Problem]]:
    best: tuple[int, Beat, list[Problem]] | None = None
    problems: list[Problem] = []
    for _ in range(settings.ingest_retries + 1):
        prompt = load_prompt("question").format(
            title=book_title, narration=beat.narration, next=next_text, feedback=_feedback(problems)
        )
        result = llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            json_schema=QUESTION_SCHEMA,
        )
        data = _json(result.text)
        with_question = question_from_answer(data, beat, has_next=has_next) if data else None
        problems = (
            [Problem("the answer was not valid JSON of the expected shape", retry=True)]
            if with_question is None
            else check_question(with_question, next_text)
        )
        if with_question is not None and (best is None or len(problems) < best[0]):
            best = (len(problems), with_question, problems)
        if not any(p.retry for p in problems):
            break
    return (best[1], best[2]) if best else (beat, problems)


def generate_beat(
    llm: LLMClient,
    *,
    book_title: str,
    author: str,
    chapter_title: str,
    base: Beat,
    scene: str,
    next_text: str,
    has_next: bool,
    previous_narration: str = "",
    settings: Settings,
) -> Beat:
    """Returns the beat with its content filled in and `flags` listing what is still wrong."""
    notes: list[str] = []
    if len(scene) > MAX_SCENE_CHARS:
        scene = scene[:MAX_SCENE_CHARS]
        notes.append("the scene was cut to fit the model's limit")
    beat, retell_problems = _retell(
        llm, book_title=book_title, author=author, chapter_title=chapter_title, base=base,
        scene=scene, previous_narration=previous_narration,
        ending="" if has_next else next_text, settings=settings,
    )  # fmt: skip
    if beat is None:
        return dataclasses.replace(base, flags=[*notes, "generation failed: no usable answer"])
    beat, dropped = drop_untraceable(beat, scene)
    with_question, question_problems = _ask(
        llm, book_title=book_title, beat=beat, next_text=next_text, has_next=has_next,
        settings=settings,
    )  # fmt: skip
    flags = [p.message for p in check_retell(with_question, scene)]
    flags += [p.message for p in question_problems]
    return dataclasses.replace(with_question, flags=[*notes, *dropped, *flags])


def with_spoilers(beats: list[Beat], later_chapter_titles: list[str]) -> list[Beat]:
    """What a child must not be told yet: later beats' titles and clues, later chapters' titles."""
    out: list[Beat] = []
    for i, beat in enumerate(beats):
        later = beats[i + 1 :]
        reveals = [b.title for b in later if b.title and not b.title.startswith("Part ")]
        reveals += [clue for b in later for clue in b.clues]
        reveals += later_chapter_titles
        out.append(dataclasses.replace(beat, spoiler_reveals=reveals))
    return out
