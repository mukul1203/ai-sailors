import json
from collections.abc import Callable

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.grounding import numbered_sentences, split_sentences
from storyquest.agent.modes import get_mode
from storyquest.agent.replies import REPLIES
from storyquest.agent.turn import run_turn
from storyquest.domain.position import Position
from storyquest.stores.search import search_chunks

pytestmark = pytest.mark.integration

START = Position(0, 0)
QUESTION = "Why are the wolves scared of Tabaqui?"
MakeCtx = Callable[[object], AgentContext]


def test_m1s_is_retrieval_plus_grounding() -> None:
    assert get_mode("m1s").retrieval and get_mode("M1S").grounded
    assert not get_mode("M1").grounded
    with pytest.raises(ValueError, match="Unknown mode"):
        get_mode("M1G")


def _ids_containing(make_ctx: MakeCtx, text: str) -> list[str]:
    ctx = make_ctx(ScriptedLLM())
    hits = search_chunks(ctx.conn, ctx.book.id, QUESTION, START, limit=3)
    return [i for i, s in numbered_sentences(hits).items() if text in s]


def ask_select(make_ctx: MakeCtx, ids: list[str]):  # type: ignore[no-untyped-def]
    answer = json.dumps({"evidence": ids, "answer": "Because he can go mad."})
    llm = ScriptedLLM(answer=answer)
    return run_turn(make_ctx(llm), QUESTION, START, mode=get_mode("M1S")), llm


def test_m1s_numbers_the_sentences_and_accepts_a_chosen_one(make_ctx: MakeCtx) -> None:
    ids = _ids_containing(make_ctx, "apt to go mad")
    assert ids
    result, llm = ask_select(make_ctx, ids[:1])
    assert result.reply == "Because he can go mad." and result.flags == []
    prompt = llm.generation_calls[0][1]["content"]
    assert f"[{ids[0]}] " in prompt and "evidence" in llm.generation_calls[0][0]["content"]


def test_m1s_rejects_an_empty_choice(make_ctx: MakeCtx) -> None:
    result, _ = ask_select(make_ctx, [])
    assert result.reply == REPLIES["unknown_yet"] and result.flags == ["ungrounded:no_evidence"]


def test_m1s_rejects_ids_that_are_not_shown_to_the_model(make_ctx: MakeCtx) -> None:
    result, _ = ask_select(make_ctx, ["9.9"])
    assert result.flags == ["ungrounded:no_evidence"]


def test_unreadable_output_is_not_grounded(make_ctx: MakeCtx) -> None:
    llm = ScriptedLLM(answer="not json")
    result = run_turn(make_ctx(llm), QUESTION, START, mode=get_mode("M1S"))
    assert result.flags == ["ungrounded:unparsed"]
    assert result.reply == REPLIES["unknown_yet"]


def test_sentences_split_after_closing_quotes() -> None:
    text = 'He said, "Go home." Then he left! Was it late? Yes.'
    assert split_sentences(text) == ['He said, "Go home."', "Then he left!", "Was it late?", "Yes."]
