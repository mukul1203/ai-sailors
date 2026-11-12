"""Stage 6: generate the content of each beat (title, narration, clues, vocabulary, choice).

One small JSON call per beat. Each clue comes with a quote copied from the scene, and stage 7
checks the quote against the text; a beat that fails is asked again with the problems listed,
then kept with its flags if it still fails, so the human reviewer sees it first.
"""

import dataclasses
import json
from typing import Any

from storyquest.config import Settings
from storyquest.domain.book import Beat
from storyquest.ingestion.prompts import load_prompt
from storyquest.ingestion.validate import (
    Problem,
    check_beat,
    normalise,
    quote_in_text,
    vocabulary_in_text,
)
from storyquest.models.llm import LLMClient

MAX_TOKENS = 900  # the endpoint allows at most 1024 output tokens
MAX_SCENE_CHARS = 12000  # about 3,000 tokens: with the prompt and answer, inside the 8,192 limit
NEXT_PEEK_CHARS = 500

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "narration_summary": {"type": "string"},
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
        "vocabulary": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "choice_prompt": {"type": "string"},
        "choice_options": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {"type": "string"},
        },
        "canon_option": {"type": "integer", "minimum": 1, "maximum": 3},
    },
    "required": [
        "title",
        "narration_summary",
        "clues",
        "vocabulary",
        "choice_prompt",
        "choice_options",
        "canon_option",
    ],
    "additionalProperties": False,
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def beat_from_answer(data: dict[str, Any], base: Beat, *, has_next: bool) -> Beat | None:
    """Build a beat from the model's JSON, or None if the shape is wrong."""
    try:
        clue_items = [c for c in data["clues"] if isinstance(c, dict)]
        options = [_text(o) for o in data["choice_options"] if _text(o)]
        vocabulary = [_text(v) for v in data["vocabulary"] if _text(v)]
        canon = data["canon_option"]
        canon = canon if isinstance(canon, int) and 1 <= canon <= len(options) else 1
        number = base.idx + 1
        cards = [
            {
                "id": f"B{number}-{chr(ord('a') + i)}",
                "text": option,
                "next": f"B{number + 1}" if has_next else "end",
                "canon": i + 1 == canon,
            }
            for i, option in enumerate(options)
        ]
        return dataclasses.replace(
            base,
            title=_text(data["title"]),
            narration=_text(data["narration_summary"]),
            clues=[_text(c.get("clue")) for c in clue_items],
            clue_quotes=[_text(c.get("quote")) for c in clue_items],
            vocabulary=vocabulary,
            choice={"prompt": _text(data["choice_prompt"]), "cards": cards},
        )
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


def _feedback(problems: list[Problem]) -> str:
    lines = "\n".join(f"- {p.message}" for p in problems if p.retry)
    return f"\nYour last answer had these problems. Fix them:\n{lines}\n" if lines else ""


def generate_beat(
    llm: LLMClient,
    *,
    book_title: str,
    author: str,
    chapter_title: str,
    base: Beat,
    scene: str,
    next_hint: str,
    has_next: bool,
    settings: Settings,
) -> Beat:
    """Returns the beat with its content filled in and `flags` listing what is still wrong."""
    notes: list[str] = []
    if len(scene) > MAX_SCENE_CHARS:
        scene = scene[:MAX_SCENE_CHARS]
        notes.append("the scene was cut to fit the model's limit")
    best: tuple[int, Beat, list[Problem]] | None = None
    problems: list[Problem] = []
    for _ in range(settings.ingest_retries + 1):
        prompt = load_prompt("beat").format(
            title=book_title,
            author=author,
            chapter=chapter_title,
            next=next_hint or "the chapter ends",
            feedback=_feedback(problems),
            scene=scene,
        )
        result = llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
            json_schema=SCHEMA,
        )
        beat = _read(result.text, base, has_next)
        problems = (
            [Problem("the answer was not valid JSON of the expected shape", retry=True)]
            if beat is None
            else check_beat(beat, scene)
        )
        if beat is not None and (best is None or len(problems) < best[0]):
            best = (len(problems), beat, problems)
        if not any(p.retry for p in problems):
            break
    if best is None:
        return dataclasses.replace(base, flags=[*notes, "generation failed: no usable answer"])
    _, beat, _ = best
    beat, dropped = drop_untraceable(beat, scene)
    flags = [p.message for p in check_beat(beat, scene)]
    return dataclasses.replace(beat, flags=[*notes, *dropped, *flags])


def _read(text: str, base: Beat, has_next: bool) -> Beat | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return beat_from_answer(data, base, has_next=has_next) if isinstance(data, dict) else None


def next_hint(next_scene: str | None) -> str:
    if not next_scene:
        return ""
    flat = " ".join(next_scene.split())
    return flat[:NEXT_PEEK_CHARS]


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
