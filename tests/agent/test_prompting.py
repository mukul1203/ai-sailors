"""Prompting comparison: M2S-FS, M2S-COT and M2S-DEC keep M2S's search and grounding and change
only the answer prompt, so differences in the results come from the prompting alone."""

import json
import re
from collections.abc import Callable
from dataclasses import replace

import pytest

from llm_helpers import AgentLLM, ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.grounding import schema_for
from storyquest.agent.modes import describe_steps, get_mode
from storyquest.agent.turn import run_turn
from storyquest.domain.position import Position
from storyquest.models.embedder import FakeEmbedder
from storyquest.models.llm import Message
from storyquest.stores.vector import chunks_without_vectors, store_vectors

START = Position(0, 0)
QUESTION = "Why are the wolves scared of Tabaqui?"
MakeCtx = Callable[[object], AgentContext]
VARIANTS = ("M2S-FS", "M2S-COT", "M2S-DEC")


def test_the_variants_differ_from_m2s_only_in_the_prompt() -> None:
    base = get_mode("M2S")
    assert base.prompting == "zero-shot"
    for name in VARIANTS:
        mode = get_mode(name.lower())
        same = (mode.retrieval, mode.grounded, mode.hybrid, mode.entities, mode.rerank)
        assert same == (base.retrieval, base.grounded, base.hybrid, base.entities, base.rerank)
        assert not mode.agentic and mode.prompting != "zero-shot"
        assert describe_steps(mode, 6) != describe_steps(base, 6)


def test_the_schema_asks_for_reasoning_or_sub_questions_before_the_evidence() -> None:
    assert list(schema_for([])["properties"]) == ["evidence", "answer"]
    cot = schema_for([], "chain-of-thought")
    assert list(cot["properties"]) == ["reasoning", "evidence", "answer"]
    assert cot["required"] == ["reasoning", "evidence", "answer"]
    dec = schema_for([], "decomposition")
    assert list(dec["properties"]) == ["sub_questions", "evidence", "answer"]
    assert dec["properties"]["sub_questions"]["maxItems"] == 3


pytestmark_integration = pytest.mark.integration


class CitingLLM(ScriptedLLM):
    """Cites the first sentence it is shown, with any extra fields the strategy asks for."""

    def __init__(self, extra: dict[str, object]) -> None:
        self.extra = extra
        super().__init__()

    def _respond(self, messages: list[Message]) -> str:
        if "sort short messages" in messages[0]["content"]:
            return json.dumps({"label": "story_question"})
        first = re.search(r"\[(\d+\.\d+)\]", messages[1]["content"])
        ids = [first.group(1)] if first else []
        return json.dumps({**self.extra, "evidence": ids, "answer": "He can go mad."})


def _ask(make_ctx: MakeCtx, llm: ScriptedLLM, name: str):  # type: ignore[no-untyped-def]
    ctx = make_ctx(llm)
    fake = FakeEmbedder()
    todo = chunks_without_vectors(ctx.conn, ctx.book.id, fake.model_id)
    vectors = fake.embed([text for _, text in todo], query=False)
    rows = [(c, v) for (c, _), v in zip(todo, vectors, strict=True)]
    store_vectors(ctx.conn, fake.model_id, fake.dim, rows)
    return run_turn(replace(ctx, embedder=fake), QUESTION, START, mode=get_mode(name))


@pytestmark_integration
@pytest.mark.parametrize(
    ("name", "marker", "extra"),
    [
        ("M2S-FS", "The Lighthouse Cat", {}),
        ("M2S-COT", "In reasoning", {"reasoning": "Sentence says he goes mad."}),
        ("M2S-DEC", "sub_questions", {"sub_questions": [{"question": "q", "finding": "f"}]}),
    ],
)
def test_each_variant_adds_its_instruction_and_hides_its_working(
    make_ctx: MakeCtx, name: str, marker: str, extra: dict[str, object]
) -> None:
    llm = CitingLLM(extra)
    result = _ask(make_ctx, llm, name)
    assert result.reply == "He can go mad." and result.flags == []
    system = llm.generation_calls[0][0]["content"]
    assert marker in system


@pytestmark_integration
def test_m2s_keeps_its_prompt_unchanged(make_ctx: MakeCtx) -> None:
    llm = CitingLLM({})
    _ask(make_ctx, llm, "M2S")
    system = llm.generation_calls[0][0]["content"]
    assert "Lighthouse" not in system and "reasoning" not in system


@pytestmark_integration
@pytest.mark.parametrize(
    ("name", "marker"), [("M5-FS", "Example 1, the passages answer"), ("M5-COT", "In reasoning")]
)
def test_the_agent_variants_change_only_the_answer_prompt(
    make_ctx: MakeCtx, name: str, marker: str
) -> None:
    mode = get_mode(name)
    assert mode.agentic and mode.grounded and mode.hybrid
    llm = AgentLLM()
    result = run_turn(make_ctx(llm), "Why does Shere Khan limp?", Position(0, 1), mode=mode)
    assert result.reply == "Shere Khan was born lame in one foot."
    assert llm.roles.count("generate") == 1 and "critic" in llm.roles
    systems = {llm.role(m): m[0]["content"] for m in llm.calls}
    assert marker in systems["generate"]
    assert marker not in systems["planner"] and marker not in systems["critic"]


@pytestmark_integration
def test_m5_keeps_its_answer_prompt_unchanged(make_ctx: MakeCtx) -> None:
    llm = AgentLLM()
    run_turn(make_ctx(llm), "Why does Shere Khan limp?", Position(0, 1), mode=get_mode("M5"))
    systems = {llm.role(m): m[0]["content"] for m in llm.calls}
    assert "Example 1, the passages" not in systems["generate"]
    assert "In reasoning" not in systems["generate"]
    assert not get_mode("M5").thinks and get_mode("M5-COT").thinks
