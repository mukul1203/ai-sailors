"""One child turn: guard, route, then (retrieve), generate, check, or the agent loop (M5)."""

import time
from collections.abc import Sequence
from dataclasses import replace

from storyquest.agent.context import AgentContext
from storyquest.agent.generate import build_messages, generate
from storyquest.agent.grounding import schema_for, verify
from storyquest.agent.guard import check_input
from storyquest.agent.loop import run_agent
from storyquest.agent.memory import PastTurn
from storyquest.agent.modes import Mode
from storyquest.agent.output_check import check_reply
from storyquest.agent.replies import REPLIES
from storyquest.agent.retrieval import retrieve
from storyquest.agent.router import classify
from storyquest.agent.trace import StepTrace, TurnResult, timed
from storyquest.domain.position import Position
from storyquest.models.llm import LLMError, LLMResult, Message
from storyquest.stores.search import SearchHit


def _trace(name: str, messages: list[Message], r: LLMResult) -> StepTrace:
    return StepTrace(
        name,
        messages,
        r.text,
        r.prompt_tokens,
        r.completion_tokens,
        r.latency_s,
        r.cached,
        r.model,
        r.finish_reason,
    )


def run_turn(
    ctx: AgentContext,
    text: str,
    position: Position,
    *,
    mode: Mode,
    history: Sequence[PastTurn] = (),
) -> TurnResult:
    """Answer one message. `history` (the session's last story questions) is used by the agent
    mode only, to understand follow-up questions."""
    started_at, start = time.time(), time.monotonic()
    timings: dict[str, float] = {}
    result = _run(ctx, text, position, mode, timings, history)
    return replace(
        result,
        started_at=started_at,
        total_latency_s=round(time.monotonic() - start, 4),
        timings=timings,
    )


def _run(
    ctx: AgentContext,
    text: str,
    position: Position,
    mode: Mode,
    timings: dict[str, float],
    history: Sequence[PastTurn],
) -> TurnResult:
    child = " ".join(text.split())
    with timed(timings, "guard"):
        problem = check_input(child, ctx.settings.max_child_input_chars)
    if problem is not None:
        return TurnResult(REPLIES[problem], problem, mode.name)

    steps: list[StepTrace] = []
    flags: list[str] = []
    where = ctx.where(position)

    try:
        with timed(timings, "router"):
            route, router_step, parsed = classify(ctx.llm, ctx.book.title, child)
    except LLMError as e:
        return TurnResult(REPLIES["error"], "error", mode.name, flags=[f"llm_error:router:{e}"])
    steps.append(router_step)
    if not parsed:
        flags.append("router_unparsed")
    if route != "story_question":
        return TurnResult(REPLIES[route], route, mode.name, steps, flags=flags)
    if mode.agentic:
        return run_agent(
            ctx, child, position, mode, history=history, steps=steps, flags=flags, timings=timings
        )

    passages: list[SearchHit] = []
    if mode.retrieval:
        with timed(timings, "retrieval"):
            passages, retrieval_flags = retrieve(ctx, mode, child, position)
        flags.extend(retrieval_flags)
        if not passages:
            flags.append("no_hits")
            return TurnResult(REPLIES["unknown_yet"], route, mode.name, steps, flags=flags)

    messages = build_messages(ctx, mode, where, child, passages)
    try:
        with timed(timings, "generate"):
            result = generate(
                ctx,
                messages,
                schema=schema_for(passages, mode.prompting) if mode.grounded else None,
                thinking=mode.prompting in ("chain-of-thought", "decomposition"),
            )
    except LLMError as e:
        flags.append(f"llm_error:generate:{e}")
        return TurnResult(REPLIES["error"], "error", mode.name, steps, passages, flags)
    steps.append(_trace("generate", messages, result))

    reply = result.text
    evidence = ""
    if mode.grounded:
        with timed(timings, "verify"):
            answer, problem, evidence = verify(reply, passages)
        if answer is None:
            flags.append(f"ungrounded:{problem}")
            return TurnResult(
                REPLIES["unknown_yet"], route, mode.name, steps, passages, flags, evidence
            )
        reply = answer
    with timed(timings, "output_check"):
        problems = check_reply(reply, child, ctx.names, where.boundary)
    if problems or not reply:
        flags.extend(problems or ["empty_reply"])
        reply = REPLIES["careful"]
    return TurnResult(reply, route, mode.name, steps, passages, flags, evidence)
