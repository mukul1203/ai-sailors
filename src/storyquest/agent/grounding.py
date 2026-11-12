"""Grounded answers (M1S): sentences are numbered, the model returns ids, code looks them up."""

import json
import re
from typing import Any

from storyquest.stores.search import SearchHit

EXTRA_TOKENS = 100  # room for the evidence on top of the normal answer budget
MAX_SELECTED = 3
_SENTENCE = re.compile(r".+?(?:[.!?][\"\u201d\u2019']*(?=\s+[\"\u201c\u2018']?[A-Z])|$)", re.S)


def split_sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s.strip() for s in _SENTENCE.findall(flat) if s.strip()]


def numbered_sentences(passages: list[SearchHit]) -> dict[str, str]:
    """Maps ids like "2.3" (passage 2, sentence 3) to the sentence text."""
    return {
        f"{i}.{j}": s
        for i, p in enumerate(passages, 1)
        for j, s in enumerate(split_sentences(p.text), 1)
    }


def numbered_text(passages: list[SearchHit]) -> str:
    """The passages as the model sees them in M1S: one numbered sentence per line."""
    blocks = []
    for i, p in enumerate(passages, 1):
        lines = [f"[{i}.{j}] {s}" for j, s in enumerate(split_sentences(p.text), 1)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def schema_for(passages: list[SearchHit]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "evidence": {
                "type": "array",
                "items": {"type": "string", "enum": list(numbered_sentences(passages))},
                "maxItems": MAX_SELECTED,
            },
            "answer": {"type": "string"},
        },
        "required": ["evidence", "answer"],
        "additionalProperties": False,
    }


def verify(raw: str, passages: list[SearchHit]) -> tuple[str | None, str | None, str]:
    """Returns (answer, problem, evidence). problem is None when the answer is grounded."""
    try:
        data = json.loads(raw)
        answer = str(data["answer"]).strip()
    except (ValueError, KeyError, TypeError):
        return None, "unparsed", ""
    by_id = numbered_sentences(passages)
    ids = [i for i in data.get("evidence") or [] if i in by_id]
    if not ids:
        return None, "no_evidence", ""
    return answer, None, " ".join(by_id[i] for i in ids)
