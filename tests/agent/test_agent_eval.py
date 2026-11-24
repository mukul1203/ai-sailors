"""Mode M5 in the eval runner and the command-line view of a turn."""

from collections.abc import Callable
from pathlib import Path

import pytest

from llm_helpers import AgentLLM, plan
from storyquest.agent.context import AgentContext
from storyquest.agent.modes import get_mode
from storyquest.agent.render import render_turn
from storyquest.agent.turn import run_turn
from storyquest.domain.position import Position
from storyquest.evaluation.items import load_items
from storyquest.evaluation.report import summarize
from storyquest.evaluation.runner import make_config, run_eval
from storyquest.models.llm import LLMClient

pytestmark = pytest.mark.integration

MakeCtx = Callable[[LLMClient], AgentContext]


def test_the_eval_scores_m5_on_the_passages_its_tools_found(
    make_ctx: MakeCtx, eval_dir: Path
) -> None:
    golden = eval_dir / "golden_v1.jsonl"
    items = [i for i in load_items(golden) if i.id in {"CAN-003", "MAL-001"}]

    def rows_for(*calls: tuple[str, str]) -> dict[str, dict]:  # type: ignore[type-arg]
        llm = AgentLLM(plans=[plan("Why does Shere Khan limp?", *calls)])
        return {
            r["id"]: r for r in run_eval(make_ctx(llm), items, get_mode("M5"), log=lambda _: None)
        }

    # A search for the limp finds the gold lines; looking up only his name finds his first
    # mentions instead. Retrieval is scored on what the agent's own tools returned.
    searched = rows_for(("search_book", "Shere Khan lame foot"))
    assert searched["CAN-003"]["retrieval_hit"] is True
    assert searched["CAN-003"]["tool_calls"] == 1 and searched["CAN-003"]["calls"] == 4
    assert rows_for(("lookup_character", "Shere Khan"))["CAN-003"]["retrieval_hit"] is False
    assert searched["MAL-001"]["tool_calls"] == 0  # an empty message never reaches the planner

    ctx = make_ctx(AgentLLM())
    config = make_config(ctx, get_mode("M5"), "dev", golden, list(searched.values()))
    assert "tool calls" in summarize(config, list(searched.values()))


def test_the_command_line_view_lists_the_tool_calls(make_ctx: MakeCtx) -> None:
    ctx = make_ctx(AgentLLM())
    position = Position(0, 0)
    result = run_turn(ctx, "Why does Shere Khan limp?", position, mode=get_mode("M5"))
    text = render_turn(ctx, position, "Why does Shere Khan limp?", result, verbose=False)
    assert "Tool search_book('lame') found" in text
    assert "[planner]" in text and "[critic]" in text
