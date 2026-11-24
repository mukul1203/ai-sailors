from collections.abc import Callable

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.tools import (
    MAX_ARGUMENT_CHARS,
    TOOLS,
    Tool,
    ToolCall,
    current_scene,
    lookup_character,
    run_tool,
    search_book,
)
from storyquest.domain.position import Position
from storyquest.models.llm import LLMClient

pytestmark = pytest.mark.integration

MakeCtx = Callable[[LLMClient], AgentContext]
START = Position(0, 0)


def test_there_are_three_tools_and_each_says_what_it_needs() -> None:
    assert set(TOOLS) == {"search_book", "lookup_character", "current_scene"}
    assert all("Argument:" in t.description for t in TOOLS.values())


def test_search_book_only_finds_what_the_child_has_read(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    found = search_book(ctx, START, "Shere Khan lame foot").passages
    assert found and all((p.chapter_idx, p.beat_idx) == (0, 0) for p in found)
    # Baloo first appears in the third beat: at the start, the book has nothing about him.
    assert search_book(ctx, START, "Baloo the bear").passages == []


def test_lookup_character_gives_book_text_and_nothing_for_names_not_reached(
    make_ctx: MakeCtx,
) -> None:
    ctx = make_ctx(ScriptedLLM())
    tabaqui = lookup_character(ctx, START, "Tabaqui").passages
    assert tabaqui and tabaqui[0].source == "chunk" and "Tabaqui" in tabaqui[0].text
    assert lookup_character(ctx, START, "Baloo").passages == []


def test_current_scene_is_the_retelling_of_the_childs_beat(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    [scene] = current_scene(ctx, START).passages
    assert scene.source == "scene" and (scene.chapter_idx, scene.beat_idx) == (0, 0)
    assert scene.text == ctx.beats[0][0].narration
    assert current_scene(ctx, Position(99, 0)).passages == []  # no such chapter


def test_a_bad_or_broken_tool_call_returns_nothing_and_says_why(
    make_ctx: MakeCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = make_ctx(ScriptedLLM())
    output, trace = run_tool(ctx, START, ToolCall("delete_everything", "now"))
    assert output.passages == [] and "unknown tool" in trace.error

    def broken(*_: object) -> None:
        raise RuntimeError("index missing")

    monkeypatch.setitem(TOOLS, "search_book", Tool("search_book", "Argument: x", broken))  # type: ignore[arg-type]
    output, trace = run_tool(ctx, START, ToolCall("search_book", "Shere Khan"))
    assert output.passages == [] and trace.error == "RuntimeError: index missing"


def test_arguments_are_tidied_and_capped(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(ScriptedLLM())
    _, trace = run_tool(ctx, START, ToolCall("search_book", "  Shere \n Khan  " + "x" * 300))
    assert trace.argument.startswith("Shere Khan x") and len(trace.argument) == MAX_ARGUMENT_CHARS
    assert trace.error == ""
