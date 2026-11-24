"""The planner: one model call that rewrites the question and chooses the tools to answer it.

The output is held to a JSON schema (tool names are an enum), so the 8B model can only pick
real tools. If its answer still cannot be used, the caller asks once more and then falls back
to a plain book search for the child's own words.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from storyquest.agent.memory import PastTurn, describe
from storyquest.agent.prompts import load_prompt
from storyquest.agent.tools import MAX_ARGUMENT_CHARS, TOOLS, ToolCall
from storyquest.agent.trace import StepTrace
from storyquest.models.llm import LLMClient, Message

MAX_CALLS = 3
MAX_QUESTION_CHARS = 200
MAX_TOKENS = 200

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "maxLength": MAX_QUESTION_CHARS},
        "calls": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_CALLS,
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": list(TOOLS)},
                    "argument": {"type": "string", "maxLength": MAX_ARGUMENT_CHARS},
                },
                "required": ["tool", "argument"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["question", "calls"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Plan:
    question: str  # the child's question, rewritten to make sense on its own
    calls: list[ToolCall]


def fallback_plan(child_text: str) -> Plan:
    """What the agent does when the planner gives nothing usable: search for the child's words."""
    return Plan(child_text, [ToolCall("search_book", child_text)])


def parse_plan(raw: str, child_text: str) -> Plan | None:
    """The plan in the model's JSON, or None if there is no usable tool call in it."""
    try:
        data = json.loads(raw)
        calls = [ToolCall(str(c["tool"]), str(c.get("argument", ""))) for c in data["calls"]]
    except (ValueError, KeyError, TypeError):
        return None
    calls = [c for c in calls if c.tool in TOOLS][:MAX_CALLS]
    if not calls:
        return None
    question = str(data.get("question") or "").strip() or child_text
    return Plan(question[:MAX_QUESTION_CHARS], calls)


def make_plan(
    llm: LLMClient, book_title: str, child_text: str, history: Sequence[PastTurn]
) -> tuple[Plan | None, StepTrace]:
    """One planner call. Returns the plan (None if unusable) and the trace of the call."""
    tools = "\n".join(f"- {t.name}: {t.description}" for t in TOOLS.values())
    system = load_prompt("planner").format(
        title=book_title, tools=tools, history=describe(history) or "(none)"
    )
    messages: list[Message] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"<child_message>\n{child_text}\n</child_message>",
        },
    ]
    result = llm.chat(messages, max_tokens=MAX_TOKENS, temperature=0.0, json_schema=SCHEMA)
    return parse_plan(result.text, child_text), StepTrace.of("planner", messages, result)
