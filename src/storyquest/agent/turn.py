"""One child turn: guard, route, (retrieve), generate, check."""

from storyquest.agent.context import AgentContext
from storyquest.agent.generate import build_messages, generate
from storyquest.agent.guard import check_input
from storyquest.agent.modes import Mode
from storyquest.agent.output_check import check_reply
from storyquest.agent.replies import REPLIES
from storyquest.agent.router import classify
from storyquest.agent.trace import StepTrace, TurnResult
from storyquest.domain.position import Position
from storyquest.models.llm import LLMError, LLMResult, Message
from storyquest.stores.search import search_chunks


def _trace(name: str, messages: list[Message], r: LLMResult) -> StepTrace:
    return StepTrace(
        name, messages, r.text, r.prompt_tokens, r.completion_tokens, r.latency_s, r.cached
    )


def run_turn(ctx: AgentContext, text: str, position: Position, *, mode: Mode) -> TurnResult:
    child = " ".join(text.split())
    problem = check_input(child, ctx.settings.max_child_input_chars)
    if problem is not None:
        return TurnResult(REPLIES[problem], problem, mode.name)

    steps: list[StepTrace] = []
    flags: list[str] = []
    where = ctx.where(position)

    try:
        route, router_step, parsed = classify(ctx.llm, ctx.book.title, child)
    except LLMError as e:
        return TurnResult(REPLIES["error"], "error", mode.name, flags=[f"llm_error:router:{e}"])
    steps.append(router_step)
    if not parsed:
        flags.append("router_unparsed")
    if route != "story_question":
        return TurnResult(REPLIES[route], route, mode.name, steps, flags=flags)

    passages = []
    if mode.retrieval:
        passages = search_chunks(
            ctx.conn, ctx.book.id, child, position, limit=ctx.settings.retrieval_top_k
        )
        if not passages:
            flags.append("no_hits")
            return TurnResult(REPLIES["unknown_yet"], route, mode.name, steps, flags=flags)

    messages = build_messages(ctx, mode, where, child, passages)
    try:
        result = generate(ctx, messages)
    except LLMError as e:
        flags.append(f"llm_error:generate:{e}")
        return TurnResult(REPLIES["error"], "error", mode.name, steps, passages, flags)
    steps.append(_trace("generate", messages, result))

    reply = result.text
    problems = check_reply(reply, child, ctx.names, where.boundary)
    if problems or not reply:
        flags.extend(problems or ["empty_reply"])
        reply = REPLIES["careful"]
    return TurnResult(reply, route, mode.name, steps, passages, flags)
