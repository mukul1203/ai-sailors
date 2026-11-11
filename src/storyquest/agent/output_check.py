"""Checks on a finished reply that need no model: film and cartoon talk, and name spoilers."""

import re

_BANNED = re.compile(r"\b(disney|cartoon|movie|film|king louie|bare necessities)\b", re.IGNORECASE)
_WORDS = re.compile(r"[A-Za-z]{3,}")


def check_reply(reply: str, child_text: str, names: dict[str, int], boundary: int) -> list[str]:
    """Returns a flag for each problem found; an empty list means the reply passes.

    `names` maps each proper name to where it first appears in the book. A name that first
    appears after `boundary` (the end of the part the child has reached) would be a spoiler.
    Names and film words the child used themselves are allowed, so the agent can say "that is
    not in the book".
    """
    flags = []
    asked_about = {w.lower() for w in _WORDS.findall(child_text)}
    child_lower = child_text.lower()
    for m in _BANNED.finditer(reply):
        term = m.group().lower()
        if term not in child_lower:
            flags.append(f"banned_term:{term}")
    for word in dict.fromkeys(w.lower() for w in _WORDS.findall(reply)):
        first = names.get(word)
        if first is not None and first >= boundary and word not in asked_about:
            flags.append(f"later_name:{word}")
    return flags
