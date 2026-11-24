import json

from storyquest.agent.memory import PastTurn
from storyquest.agent.planner import (
    MAX_CALLS,
    SCHEMA,
    Plan,
    fallback_plan,
    make_plan,
    parse_plan,
)
from storyquest.agent.tools import TOOLS, ToolCall
from storyquest.models.fake import FakeClient


def plan_json(question: str, *calls: tuple[str, str]) -> str:
    return json.dumps(
        {"question": question, "calls": [{"tool": t, "argument": a} for t, a in calls]}
    )


def test_a_good_plan_is_read_as_written() -> None:
    raw = plan_json("Why does Shere Khan limp?", ("lookup_character", "Shere Khan"))
    assert parse_plan(raw, "why does he limp") == Plan(
        "Why does Shere Khan limp?", [ToolCall("lookup_character", "Shere Khan")]
    )


def test_unknown_tools_are_dropped_and_extra_calls_cut() -> None:
    raw = plan_json("q", ("delete_book", "x"), *[("search_book", f"q{n}") for n in range(5)])
    plan = parse_plan(raw, "q")
    assert plan is not None and [c.tool for c in plan.calls] == ["search_book"] * MAX_CALLS


def test_an_unusable_answer_gives_no_plan() -> None:
    for raw in ("not json", "{}", plan_json("q"), plan_json("q", ("delete_book", "x"))):
        assert parse_plan(raw, "q") is None


def test_an_empty_rewrite_keeps_the_childs_question() -> None:
    plan = parse_plan(plan_json("", ("search_book", "fire")), "What is the Red Flower?")
    assert plan is not None and plan.question == "What is the Red Flower?"


def test_the_fallback_searches_for_the_childs_own_words() -> None:
    assert fallback_plan("Who is Akela?") == Plan(
        "Who is Akela?", [ToolCall("search_book", "Who is Akela?")]
    )


def test_the_planner_sees_the_tools_the_history_and_the_marked_question() -> None:
    llm = FakeClient(plan_json("Why did Shere Khan come?", ("search_book", "Shere Khan cave")))
    history = [PastTurn("Who is Shere Khan?", "A tiger who limps.")]
    plan, trace = make_plan(llm, "The Jungle Book", "why did he come?", history)
    assert plan is not None and plan.question == "Why did Shere Khan come?"
    system, user = llm.calls[0][0]["content"], llm.calls[0][1]["content"]
    assert all(name in system for name in TOOLS)
    assert "Child: Who is Shere Khan?\nGuide: A tiger who limps." in system
    assert user == "<child_message>\nwhy did he come?\n</child_message>"
    assert trace.name == "planner"
    tool_enum = SCHEMA["properties"]["calls"]["items"]["properties"]["tool"]["enum"]
    assert tool_enum == list(TOOLS)


def test_without_history_the_prompt_says_so() -> None:
    llm = FakeClient(plan_json("q", ("search_book", "q")))
    make_plan(llm, "The Jungle Book", "q", [])
    assert "(none)" in llm.calls[0][0]["content"]
