"""One child turn: guard, route, (retrieve), generate, check."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from storyquest.agent.context import AgentContext
from storyquest.agent.generate import build_messages, generate
from storyquest.agent.grounding import schema_for, verify
from storyquest.agent.guard import check_input
from storyquest.agent.modes import Mode
from storyquest.agent.output_check import check_reply
from storyquest.agent.replies import REPLIES
from storyquest.agent.retrieval import retrieve
from storyquest.agent.router import classify
from storyquest.agent.trace import StepTrace, TurnResult
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


@contextmanager
def _stage(timings: dict[str, float], name: str) -> Iterator[None]:
    """Record how long a stage of the turn took, even if it ends the turn early."""
    start = time.monotonic()
    try:
        yield
    finally:
        timings[name] = round(time.monotonic() - start, 4)


def run_turn(ctx: AgentContext, text: str, position: Position, *, mode: Mode) -> TurnResult:
    started_at, start = time.time(), time.monotonic()
    timings: dict[str, float] = {}
    result = _run(ctx, text, position, mode, timings)
    return replace(
        result,
        started_at=started_at,
        total_latency_s=round(time.monotonic() - start, 4),
        timings=timings,
    )


def _run(
    ctx: AgentContext, text: str, position: Position, mode: Mode, timings: dict[str, float]
) -> TurnResult:
    child = " ".join(text.split())
    with _stage(timings, "guard"):
        problem = check_input(child, ctx.settings.max_child_input_chars)
    if problem is not None:
        return TurnResult(REPLIES[problem], problem, mode.name)

    steps: list[StepTrace] = []
    flags: list[str] = []
    where = ctx.where(position)

    try:
        with _stage(timings, "router"):
            route, router_step, parsed = classify(ctx.llm, ctx.book.title, child)
    except LLMError as e:
        return TurnResult(REPLIES["error"], "error", mode.name, flags=[f"llm_error:router:{e}"])
    steps.append(router_step)
    if not parsed:
        flags.append("router_unparsed")
    if route != "story_question":
        return TurnResult(REPLIES[route], route, mode.name, steps, flags=flags)

    passages: list[SearchHit] = []
    if mode.retrieval:
        with _stage(timings, "retrieval"):
            passages, retrieval_flags = retrieve(ctx, mode, child, position)
        flags.extend(retrieval_flags)
        if not passages:
            flags.append("no_hits")
            return TurnResult(REPLIES["unknown_yet"], route, mode.name, steps, flags=flags)

    messages = build_messages(ctx, mode, where, child, passages)
    try:
        with _stage(timings, "generate"):
            result = generate(
                ctx,
                messages,
                schema=schema_for(passages) if mode.grounded else None,
            )
    except LLMError as e:
        flags.append(f"llm_error:generate:{e}")
        return TurnResult(REPLIES["error"], "error", mode.name, steps, passages, flags)
    steps.append(_trace("generate", messages, result))

    reply = result.text
    evidence = ""
    if mode.grounded:
        with _stage(timings, "verify"):
            answer, problem, evidence = verify(reply, passages)
        if answer is None:
            flags.append(f"ungrounded:{problem}")
            return TurnResult(
                REPLIES["unknown_yet"], route, mode.name, steps, passages, flags, evidence
            )
        reply = answer
    with _stage(timings, "output_check"):
        problems = check_reply(reply, child, ctx.names, where.boundary)
    if problems or not reply:
        flags.extend(problems or ["empty_reply"])
        reply = REPLIES["careful"]
    return TurnResult(reply, route, mode.name, steps, passages, flags, evidence)
