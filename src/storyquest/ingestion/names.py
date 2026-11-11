"""Proper names in a book and where each first appears, used to catch name spoilers."""

import re

_CAPITALISED = re.compile(r"\b[A-Z][a-z]{2,}\b")
_LOWERCASE = re.compile(r"\b[a-z]{3,}\b")
_ENDS_A_SENTENCE = '.!?"\u201c\u201d\u2018\u2019'


def find_names(text: str, *, start: int = 0) -> dict[str, int]:
    """Lowercased names mapped to the offset of their first appearance at or after `start`.

    A word counts as a name if it is never written in lowercase and is capitalised somewhere
    other than the start of a sentence, so ordinary sentence-starting words ("Then", "Rules")
    are excluded. Pass the offset where the first chapter begins as `start`, so titles in the
    Contents list do not count as appearances.
    """
    lowercase_words = set(_LOWERCASE.findall(text, start))
    first: dict[str, int] = {}
    mid_sentence: set[str] = set()
    for m in _CAPITALISED.finditer(text, start):
        word = m.group().lower()
        if word in lowercase_words:
            continue
        first.setdefault(word, m.start())
        before = text[max(start, m.start() - 8) : m.start()].rstrip()
        if before and before[-1] not in _ENDS_A_SENTENCE:
            mid_sentence.add(word)
    return {word: offset for word, offset in first.items() if word in mid_sentence}
