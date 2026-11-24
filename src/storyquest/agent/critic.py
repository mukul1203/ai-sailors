"""The critic: one model call that checks a draft answer before the child sees it.

It is given the question, the book sentences the answer cites and the answer itself, and says
"approve" or "revise" with the problem in one sentence. The code checks (spoiler names, film
words) still run as well; the critic adds the judgements code cannot make, such as "this fact
is not in the sentences" or "this does not answer the question".
"""

import json
from dataclasses import dataclass
from typing import Any

from storyquest.agent.context import Where
from storyquest.agent.prompts import load_prompt
from storyquest.agent.trace import StepTrace
from storyquest.models.llm import LLMClient, Message

MAX_PROBLEM_CHARS = 200
MAX_TOKENS = 120

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "revise"]},
        "problem": {"type": "string", "maxLength": MAX_PROBLEM_CHARS},
    },
    "required": ["verdict", "problem"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Critique:
    approved: bool
    problem: str = ""  # what to fix, when not approved


def parse_critique(raw: str) -> Critique | None:
    """The critic's verdict, or None if its answer cannot be read."""
    try:
        data = json.loads(raw)
        verdict = data["verdict"]
    except (ValueError, KeyError, TypeError):
        return None
    if verdict not in ("approve", "revise"):
        return None
    problem = str(data.get("problem") or "").strip()[:MAX_PROBLEM_CHARS]
    return Critique(verdict == "approve", "" if verdict == "approve" else problem)


def review(
    llm: LLMClient,
    book_title: str,
    where: Where,
    question: str,
    passages: str,
    evidence: str,
    answer: str,
) -> tuple[Critique | None, StepTrace]:
    """One critic call. Returns the critique (None if unreadable) and the trace of the call.

    `evidence` is the sentences the answer cites and `passages` the passages it was written from:
    a cited "He has been lame in one foot" says nothing about who "he" is until it is read in
    its passage, and without that the critic once approved "Mowgli limps" for Shere Khan's limp.
    """
    system = load_prompt("critic").format(
        title=book_title,
        chapter=where.chapter_title,
        beat=where.beat_title or "the start of the chapter",
    )
    content = (
        f"<question>\n{question}\n</question>\n"
        f"<passages>\n{passages}\n</passages>\n"
        f"<book_sentences>\n{evidence}\n</book_sentences>\n"
        f"<answer>\n{answer}\n</answer>"
    )
    messages: list[Message] = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
    result = llm.chat(messages, max_tokens=MAX_TOKENS, temperature=0.0, json_schema=SCHEMA)
    return parse_critique(result.text), StepTrace.of("critic", messages, result)
