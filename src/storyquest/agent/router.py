"""The router: one small model call that sorts a child's message into a label."""

import json
from typing import Any

from storyquest.agent.prompts import load_prompt
from storyquest.agent.trace import StepTrace
from storyquest.models.llm import LLMClient, Message

LABELS = ("story_question", "feelings", "off_topic", "unsafe", "injection", "personal")
DEFAULT_LABEL = "story_question"
MAX_TOKENS = 30

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": list(LABELS)}},
    "required": ["label"],
    "additionalProperties": False,
}


def classify(llm: LLMClient, book_title: str, child_text: str) -> tuple[str, StepTrace, bool]:
    """Returns (label, trace, parsed_ok). Falls back to the default label if the output is bad."""
    messages: list[Message] = [
        {"role": "system", "content": load_prompt("router").format(title=book_title)},
        {"role": "user", "content": child_text},
    ]
    result = llm.chat(messages, max_tokens=MAX_TOKENS, temperature=0.0, json_schema=_SCHEMA)
    trace = StepTrace(
        "router",
        messages,
        result.text,
        result.prompt_tokens,
        result.completion_tokens,
        result.latency_s,
        result.cached,
        result.model,
        result.finish_reason,
    )
    try:
        label = json.loads(result.text)["label"]
    except (ValueError, KeyError, TypeError):
        return DEFAULT_LABEL, trace, False
    if label not in LABELS:
        return DEFAULT_LABEL, trace, False
    return str(label), trace, True
