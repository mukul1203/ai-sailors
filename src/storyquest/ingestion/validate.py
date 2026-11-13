"""Stage 7: validate a generated beat against its source text. Code only, no model.

A problem is `retry` when asking the model again could fix it (a clue quote that is not in the
text, an unreadable answer); the rest are flagged for the human reviewer. Flags are plain
sentences because the reviewer reads them as they are.
"""

import re
from dataclasses import dataclass
from importlib.resources import files

from storyquest.domain.book import Beat
from storyquest.stores.search import STOPWORDS

MIN_QUOTE_CHARS = 12
MAX_CLUE_CHARS = 140
MIN_CLUES = 2
MIN_VOCABULARY = 2
NARRATION_RANGE = (60, 700)
TITLE_MAX = 60
MAX_ANSWER_CHARS = 80
GIVEAWAY_SHARE = 0.6  # share of the answer's words the narration may repeat
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


_MIN_WORD = 4
_NARRATION_META = ("the scene", "this scene", "in this part", "the passage")
_META = ("next text", "next part", "start of the", "very start")


def _stem(word: str) -> str:
    """A crude stem so that jump, jumps, jumped and drumming, drums match."""
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if len(word) >= _MIN_WORD and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]
    return word


def content_words(text: str) -> set[str]:
    """The meaningful words of a text, stemmed, for comparing meaning loosely (a baby "wanders
    in" and a "baby" that "could just walk" share the word baby)."""
    words = {w.lower().split("'")[0] for w in _WORDS.findall(text)}
    return {_stem(w) for w in words if len(w) >= _MIN_WORD and w not in STOPWORDS}


def _overlap(option: str, reference: set[str]) -> float:
    words = content_words(option)
    return len(words & reference) / len(words) if words else 0.0


def check_question(beat: Beat, next_scene: str | None) -> list[Problem]:
    """The question must have one right answer that the next scene backs, wrong answers it does
    not back, two hints that do not give the answer away, and a narration that does not tell it."""
    choice = beat.choice or {}
    cards = choice.get("cards", [])
    hints = [str(h) for h in choice.get("hints", []) if str(h).strip()]
    if len(str(choice.get("prompt", ""))) < 10 or not 2 <= len(cards) <= 3:
        return [Problem("the question needs a question and 2 or 3 answers", retry=True)]
    problems: list[Problem] = []
    right = [c for c in cards if c.get("canon")]
    if len(right) != 1:
        return [Problem("exactly one answer must be marked right", retry=True)]
    texts = [normalise(str(c.get("text", ""))) for c in cards]
    if len(set(texts)) < len(texts) or any(not t or len(t) > MAX_ANSWER_CHARS for t in texts):
        problems.append(Problem("the answers must be different and short", retry=True))
    if len(hints) < 2:
        problems.append(Problem("the question needs two hints", retry=True))
    answer = normalise(str(right[0].get("text", "")))
    prompt_norm = normalise(str(choice.get("prompt", "")))
    if any(m in prompt_norm for m in _META):
        problems.append(
            Problem("the question must ask about the story, not about 'the text'", True)
        )
    if next_scene and len(answer.split()) >= 5 and answer in normalise(next_scene):
        problems.append(Problem("the answer must be in your own words, not copied", retry=True))
    if hits := safety_hits(
        [str(choice.get("prompt", "")), *(str(c.get("text", "")) for c in cards), *hints]
    ):
        problems.append(Problem("safety screen words: " + ", ".join(hits), retry=True))
    if any(answer and answer in normalise(h) for h in hints):
        problems.append(Problem("a hint gives the right answer away", retry=True))
    if next_scene:
        reference = content_words(next_scene)
        score = _overlap(answer, reference)
        wrong = [_overlap(str(c.get("text", "")), reference) for c in cards if not c.get("canon")]
        if score == 0 or score <= max(wrong, default=0.0):
            problems.append(
                Problem(
                    "the right answer must come from the NEXT text, and the wrong answers must not",
                    retry=True,
                )
            )
        answer_words = content_words(answer)
        if (
            len(answer_words) >= 2
            and len(answer_words & content_words(beat.narration)) / len(answer_words)
            >= GIVEAWAY_SHARE
        ):
            problems.append(Problem("the narration tells the answer to the question", retry=True))
    return problems


def check_retell(beat: Beat, scene: str) -> list[Problem]:
    """What is wrong with the retelling of a scene: title, narration, clues and vocabulary."""
    scene_norm = normalise(scene)
    problems: list[Problem] = []
    if not beat.title or beat.title.startswith("Part "):
        problems.append(Problem("the beat has no title of its own", retry=True))
    elif len(beat.title) > TITLE_MAX:
        problems.append(Problem(f"the title is longer than {TITLE_MAX} characters", retry=True))

    low, high = NARRATION_RANGE
    narration_norm = normalise(beat.narration)
    if any(m in narration_norm for m in _NARRATION_META):
        problems.append(Problem("tell the scene as a story; never say 'the scene'", retry=True))
    elif beat.narration and beat.narration.rstrip()[-1] not in '.!?"\u201d':
        problems.append(Problem("the narration is cut off: end it with a full sentence", True))
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

    if hits := safety_hits([beat.title, beat.narration, *beat.clues]):
        problems.append(Problem("safety screen words: " + ", ".join(hits), retry=True))
    return problems


def check_beat(beat: Beat, scene: str, next_scene: str | None = None) -> list[Problem]:
    """Everything wrong with a beat's generated content, given the text of its scene and, if
    known, the text its question is about."""
    return [*check_retell(beat, scene), *check_question(beat, next_scene)]
