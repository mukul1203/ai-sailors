"""The tools the agent's planner can choose from.

Every tool is read-only: it finds book text, it never changes the game (moving the story on or
awarding a badge stays with ordinary code, so a model can never do either). Every tool is also
position-safe: the child's position is passed in by code, never chosen by the model, so a tool
can only return text the child has already read.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from storyquest.agent.context import AgentContext
from storyquest.agent.modes import get_mode
from storyquest.agent.retrieval import entity_cards, retrieve
from storyquest.agent.trace import ToolTrace
from storyquest.domain.position import Position
from storyquest.stores.search import SearchHit, search_chunks

MAX_ARGUMENT_CHARS = 100  # a search query or a name, never a paragraph
NAME_PASSAGES = 2  # book passages that mention a looked-up name


@dataclass(frozen=True)
class ToolCall:
    """What the planner asked for: a tool by name and its one text argument."""

    tool: str
    argument: str = ""


@dataclass(frozen=True)
class ToolOutput:
    passages: list[SearchHit]
    flags: list[str] = field(default_factory=list)  # e.g. search fell back to keywords


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # what the planner reads when choosing
    run: Callable[[AgentContext, Position, str], ToolOutput]


def search_book(ctx: AgentContext, position: Position, query: str) -> ToolOutput:
    """The best-matching passages for a query, by keywords and meaning when vectors exist."""
    mode = get_mode("M2" if ctx.embedder is not None else "M1")
    hits, flags = retrieve(ctx, mode, query, position)
    return ToolOutput(hits, flags)


def lookup_character(ctx: AgentContext, position: Position, name: str) -> ToolOutput:
    """Book passages that mention a character, place or term, then its card if there is one.

    The book text comes first because a short card alone is not enough to answer from (the
    entity-card modes showed a card can crowd out the sentences that hold the exact facts).
    """
    mentions = search_chunks(ctx.conn, ctx.book.id, name, position, limit=NAME_PASSAGES)
    cards = entity_cards(ctx, name, position) if mentions else []
    return ToolOutput([*mentions, *cards])


def current_scene(ctx: AgentContext, position: Position, _: str = "") -> ToolOutput:
    """The retelling of the part the child is reading now: who is here and what is happening."""
    beats = ctx.beats.get(position.chapter_idx, [])
    beat = next((b for b in beats if b.idx == position.beat_idx), None)
    if beat is None or not beat.narration.strip():
        return ToolOutput([])
    scene = SearchHit(
        chunk_id=-1,
        chapter_idx=beat.chapter_idx,
        beat_idx=beat.idx,
        idx=0,
        text=beat.narration,
        start_char=-1,
        end_char=-1,
        score=0.0,
        source="scene",
    )
    return ToolOutput([scene])


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "search_book",
            "Find passages in the book about a topic or event. Argument: a short search query.",
            search_book,
        ),
        Tool(
            "lookup_character",
            "Find what the book says about one character, place or term. Argument: the name.",
            lookup_character,
        ),
        Tool(
            "current_scene",
            "Read what is happening in the part the child is reading now. Argument: empty.",
            current_scene,
        ),
    )
}


def run_tool(ctx: AgentContext, position: Position, call: ToolCall) -> tuple[ToolOutput, ToolTrace]:
    """Run one tool call. An unknown tool or a failing tool returns no passages and says why,
    so one bad call never ends the child's turn."""
    argument = " ".join(call.argument.split())[:MAX_ARGUMENT_CHARS]
    start = time.monotonic()
    tool = TOOLS.get(call.tool)
    if tool is None:
        error = f"unknown tool {call.tool!r}"
        return ToolOutput([]), ToolTrace(call.tool, argument, 0, 0.0, error)
    try:
        output = tool.run(ctx, position, argument)
    except Exception as e:  # noqa: BLE001 - a broken tool must not break the child's turn
        output, error = ToolOutput([]), f"{type(e).__name__}: {e}"
    else:
        error = ""
    elapsed = time.monotonic() - start
    return output, ToolTrace(call.tool, argument, len(output.passages), elapsed, error)
