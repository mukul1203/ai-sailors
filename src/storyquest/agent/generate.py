"""Building the answer prompt and calling the model."""

from typing import Any

from storyquest.agent.context import AgentContext, Where
from storyquest.agent.grounding import EXTRA_TOKENS, THINKING_TOKENS, numbered_text
from storyquest.agent.modes import Mode
from storyquest.agent.prompts import load_prompt
from storyquest.models.llm import LLMResult, Message
from storyquest.stores.search import SearchHit

_RULE_WITH_PASSAGES = (
    "Use only the passages provided. If they do not answer the question, say you do not know "
    "yet and invite the child to keep reading."
)
_RULE_WITHOUT_PASSAGES = (
    "Answer only from what you know about the original book. If you are not sure, say you are "
    "not sure."
)
_RULE_SELECT = (
    "Use only the passages provided. Every sentence has an id like [1.2]. Reply as JSON. First "
    "list in evidence the ids of up to 3 sentences that answer the question, or an empty list if "
    "none does. Then write answer using only those sentences; if the list is empty, the answer "
    "says you do not know yet."
)


_STRATEGY_PROMPTS = {
    "few-shot": "strategy_few_shot",
    "chain-of-thought": "strategy_cot",
    "decomposition": "strategy_decompose",
}


def _evidence_rule(mode: Mode) -> str:
    if mode.grounded:
        return _RULE_SELECT
    return _RULE_WITH_PASSAGES if mode.retrieval else _RULE_WITHOUT_PASSAGES


def build_messages(
    ctx: AgentContext, mode: Mode, where: Where, child_text: str, passages: list[SearchHit]
) -> list[Message]:
    system = load_prompt("generate").format(
        title=ctx.book.title,
        author=ctx.book.author,
        chapter=where.chapter_title,
        beat=where.beat_title or "the start of the chapter",
        evidence_rule=_evidence_rule(mode),
    )
    if mode.grounded and mode.prompting in _STRATEGY_PROMPTS:
        system += "\n" + load_prompt(_STRATEGY_PROMPTS[mode.prompting])
    parts: list[str] = []
    if mode.retrieval:
        numbered = (
            numbered_text(passages)
            if mode.grounded
            else "\n\n".join(f"[{i}] {p.text}" for i, p in enumerate(passages, 1))
        )
        parts.append(f"Passages from the book (what the child has already read):\n{numbered}\n")
    parts.append(
        "The child's message is between the markers.\n"
        f"<child_message>\n{child_text}\n</child_message>"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def generate(
    ctx: AgentContext,
    messages: list[Message],
    *,
    schema: dict[str, Any] | None = None,
    thinking: bool = False,
) -> LLMResult:
    """`thinking`: the schema asks for reasoning or sub-questions first, which need more room."""
    if schema is not None:
        extra = EXTRA_TOKENS + (THINKING_TOKENS if thinking else 0)
        return ctx.llm.chat(
            messages,
            max_tokens=ctx.settings.generation_max_tokens + extra,
            temperature=0.0,
            json_schema=schema,
        )
    return ctx.llm.chat(messages, max_tokens=ctx.settings.generation_max_tokens, temperature=0.0)
