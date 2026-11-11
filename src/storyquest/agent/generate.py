"""Building the answer prompt and calling the model."""

from storyquest.agent.context import AgentContext, Where
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


def build_messages(
    ctx: AgentContext, mode: Mode, where: Where, child_text: str, passages: list[SearchHit]
) -> list[Message]:
    system = load_prompt("generate").format(
        title=ctx.book.title,
        author=ctx.book.author,
        chapter=where.chapter_title,
        beat=where.beat_title or "the start of the chapter",
        evidence_rule=_RULE_WITH_PASSAGES if mode.retrieval else _RULE_WITHOUT_PASSAGES,
    )
    parts: list[str] = []
    if mode.retrieval:
        numbered = "\n\n".join(f"[{i}] {p.text}" for i, p in enumerate(passages, 1))
        parts.append(f"Passages from the book (what the child has already read):\n{numbered}\n")
    parts.append(
        "The child's message is between the markers.\n"
        f"<child_message>\n{child_text}\n</child_message>"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def generate(ctx: AgentContext, messages: list[Message]) -> LLMResult:
    return ctx.llm.chat(messages, max_tokens=ctx.settings.generation_max_tokens, temperature=0.0)
