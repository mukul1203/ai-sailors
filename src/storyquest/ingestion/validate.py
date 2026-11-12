"""Stage 7: validate a generated beat against its source text. Code only, no model.

A problem is `retry` when asking the model again could fix it (a clue quote that is not in the
text, an unreadable answer); the rest are flagged for the human reviewer. Flags are plain
sentences because the reviewer reads them as they are.
"""

import re
from dataclasses import dataclass
from importlib.resources import files

from storyquest.domain.book import Beat

MIN_QUOTE_CHARS = 12
MAX_CLUE_CHARS = 140
MIN_CLUES = 2
MIN_VOCABULARY = 2
NARRATION_RANGE = (60, 700)
TITLE_MAX = 60
MAX_READING_GRADE = 8.0  # provisional: the reading-level target is still an open question

_WORDS = re.compile(r"[A-Za-z']+")
_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})
_EDGES = " \t\n\"'.,;:!?-\u2014\u2026"


@dataclass(frozen=True)
class Problem:
    message: str
    retry: bool = False


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().lower()


def quote_in_text(quote: str, scene_norm: str) -> bool:
    """True if the quote is a stretch of the scene, ignoring case, spacing and curly quotes."""
    core = normalise(quote).strip(_EDGES)
    return len(core) >= MIN_QUOTE_CHARS and core in scene_norm


def vocabulary_in_text(word: str, scene_norm: str) -> bool:
    core = normalise(word).strip(_EDGES)
    return len(core) >= 3 and core in scene_norm


def _syllables(word: str) -> int:
    word = word.lower().strip("'")
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade level: roughly the school year needed to read the text."""
    words = _WORDS.findall(text)
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    if not words:
        return 0.0
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * len(words) / sentences + 11.8 * syllables / len(words) - 15.59


def _safety_terms() -> set[str]:
    raw = (files("storyquest.ingestion") / "prompts" / "safety_terms.txt").read_text()
    return {line.strip().lower() for line in raw.splitlines() if line.strip()}


def safety_hits(texts: list[str]) -> list[str]:
    """Words from the screening list in the generated text. A minimal screen: the reviewer is
    the real check, and the book's own text is not screened here."""
    terms = _safety_terms()
    found = {w.lower() for t in texts for w in _WORDS.findall(t)} & terms
    return sorted(found)


def duplicate_title_flags(beats: list[Beat]) -> dict[int, str]:
    """For each beat whose title another beat of the chapter also has, a flag naming that beat."""
    first: dict[str, int] = {}
    flags: dict[int, str] = {}
    for beat in beats:
        key = normalise(beat.title)
        if not key or beat.title.startswith("Part "):
            continue
        if key in first:
            flags[beat.idx] = f"the title repeats the title of B{first[key] + 1}"
        else:
            first[key] = beat.idx
    return flags


def check_beat(beat: Beat, scene: str) -> list[Problem]:
    """Everything wrong with a beat's generated content, given the text of its scene."""
    scene_norm = normalise(scene)
    problems: list[Problem] = []
    if not beat.title or beat.title.startswith("Part "):
        problems.append(Problem("the beat has no title of its own", retry=True))
    elif len(beat.title) > TITLE_MAX:
        problems.append(Problem(f"the title is longer than {TITLE_MAX} characters", retry=True))

    low, high = NARRATION_RANGE
    if not low <= len(beat.narration) <= high:
        problems.append(
            Problem(
                f"the narration is {len(beat.narration)} characters; it should be {low} to {high}",
                retry=True,
            )
        )
    else:
        grade = reading_grade(beat.narration)
        if grade > MAX_READING_GRADE:
            problems.append(Problem(f"reading level is high (grade {grade:.1f})"))

    if len(beat.clues) != len(beat.clue_quotes):
        problems.append(Problem("clues and their source quotes do not line up", retry=True))
    else:
        missing = [q for q in beat.clue_quotes if not quote_in_text(q, scene_norm)]
        if missing:
            problems.append(
                Problem(
                    f"{len(missing)} clue quote(s) are not in the scene text: "
                    + "; ".join(f'"{q[:60]}"' for q in missing),
                    retry=True,
                )
            )
    if len(beat.clues) < MIN_CLUES:
        problems.append(
            Problem(f"only {len(beat.clues)} clue(s) could be traced to the text", True)
        )
    if any(len(c) > MAX_CLUE_CHARS for c in beat.clues):
        problems.append(Problem(f"a clue is longer than {MAX_CLUE_CHARS} characters", retry=True))

    absent = [w for w in beat.vocabulary if not vocabulary_in_text(w, scene_norm)]
    if absent:
        problems.append(Problem("vocabulary not in the scene: " + ", ".join(absent), retry=True))
    if len(beat.vocabulary) < MIN_VOCABULARY:
        problems.append(Problem(f"only {len(beat.vocabulary)} vocabulary word(s)"))

    cards = beat.choice.get("cards", []) if beat.choice else []
    if not beat.choice.get("prompt") or not 2 <= len(cards) <= 3:
        problems.append(Problem("the choice needs a question and 2 or 3 options", retry=True))
    elif not any(c.get("canon") for c in cards):
        problems.append(Problem("no choice option is marked as what the book does"))

    texts = [
        beat.title,
        beat.narration,
        *beat.clues,
        str(beat.choice.get("prompt", "")),
        *(str(c.get("text", "")) for c in cards),
    ]
    if hits := safety_hits(texts):
        problems.append(Problem("safety screen words: " + ", ".join(hits), retry=True))
    return problems
