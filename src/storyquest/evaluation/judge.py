"""An LLM judge for what string matching cannot check: stated facts, invented details and
descriptive forbidden content. It sees the book text, never what the agent retrieved.

Every "yes" must come with a quote copied from the reply, and the quote is verified in code.
A verdict without a real quote counts as "no", which stops the judge model from imagining things.
"""

import json
import re
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any

from storyquest.evaluation.items import GoldItem
from storyquest.ingestion.text import Cleaned
from storyquest.models.llm import LLMClient, Message

MAX_EVIDENCE_CHARS = 3000
MAX_TOKENS = 600
_MIN_QUOTE = 4


@dataclass(frozen=True)
class JudgeVerdict:
    facts_stated: list[bool]  # aligned with item.must_include (empty if not asked)
    forbidden_found: list[str]  # descriptive must_not_include entries the reply violates
    contradicts_book: bool
    raw: str
    fact_quotes: list[str] = field(default_factory=list)  # reply words backing each fact
    contradiction_quote: str = ""  # reply words the judge says contradict the book
    evidence: str = ""  # book text the judge compared against


def needs_judging(item: GoldItem, unchecked: list[str]) -> bool:
    answers = item.expected_behavior == "answer" and bool(item.must_include)
    return answers or bool(unchecked)


def evidence_text(item: GoldItem, cleaned: Cleaned) -> str:
    parts = []
    for first, last in item.gold_lines:
        start = cleaned.offset_of_line(first)
        end = cleaned.offset_of_line(last + 1)
        parts.append(cleaned.text[start:end].strip())
    return "\n...\n".join(parts)[:MAX_EVIDENCE_CHARS]


def _numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))


def _normalise(text: str) -> str:
    table = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})
    return re.sub(r"\s+", " ", text.translate(table)).strip().lower()


def _verified(quote: object, reply: str) -> bool:
    """True only if the quote really is text from the reply."""
    text = _normalise(str(quote or ""))
    return len(text) >= _MIN_QUOTE and text in _normalise(reply)


def _pair(props: dict[str, Any], name: str) -> None:
    props[f"{name}_quote"] = {"type": "string"}  # the quote comes first, then the verdict
    props[name] = {"type": "boolean"}


def build_request(
    item: GoldItem, reply: str, evidence: str, unchecked: list[str]
) -> tuple[list[Message], dict[str, Any]]:
    props: dict[str, Any] = {}
    sections = {"evidence_section": "", "facts_section": "", "forbidden_section": ""}
    if evidence:
        _pair(props, "contradicts_book")
        sections["evidence_section"] = (
            f"\nBook text (the true source):\n{evidence}\n"
            "\nSet contradicts_book to true only if the reply contradicts the book text or invents "
            "events, characters or details the book text does not support. First put the exact "
            "words from the reply that do so in contradicts_book_quote, or an empty string.\n"
        )
    if item.expected_behavior == "answer" and item.must_include:
        for i in range(1, len(item.must_include) + 1):
            _pair(props, f"fact_{i}")
        sections["facts_section"] = (
            "\nFor each numbered statement, first copy into fact_N_quote the exact words from "
            "the reply that say it (or an empty string if the reply does not say it), then set "
            "fact_N to true or false. A paraphrase or synonym that means the same counts as "
            "saying it; the exact wording does not matter:\n" + _numbered(item.must_include) + "\n"
        )
    if unchecked:
        for i in range(1, len(unchecked) + 1):
            _pair(props, f"forbidden_{i}")
        sections["forbidden_section"] = (
            "\nFor each numbered item, first copy into forbidden_N_quote the exact words from the "
            "reply that contain it (or an empty string if it is not there), then set forbidden_N "
            "to true or false:\n" + _numbered(unchecked) + "\n"
        )

    template = (files("storyquest.evaluation") / "prompts" / "judge.txt").read_text()
    prompt = template.format(question=item.input, reply=reply, **sections)
    schema = {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }
    return [{"role": "user", "content": prompt}], schema


def judge_item(
    llm: LLMClient, item: GoldItem, reply: str, cleaned: Cleaned, unchecked: list[str]
) -> JudgeVerdict:
    messages, schema = build_request(item, reply, evidence_text(item, cleaned), unchecked)
    result = llm.chat(messages, max_tokens=MAX_TOKENS, temperature=0.0, json_schema=schema)
    data = json.loads(result.text)

    def yes(name: str) -> bool:
        return bool(data.get(name)) and _verified(data.get(f"{name}_quote"), reply)

    facts = (
        [yes(f"fact_{i}") for i in range(1, len(item.must_include) + 1)]
        if item.expected_behavior == "answer"
        else []
    )
    found = [t for i, t in enumerate(unchecked, 1) if yes(f"forbidden_{i}")]
    quotes = (
        [str(data.get(f"fact_{i}_quote") or "") for i in range(1, len(facts) + 1)] if facts else []
    )
    contradicts = yes("contradicts_book")
    contradiction = str(data.get("contradicts_book_quote") or "") if contradicts else ""
    return JudgeVerdict(
        facts, found, contradicts, result.text, quotes, contradiction, evidence_text(item, cleaned)
    )
