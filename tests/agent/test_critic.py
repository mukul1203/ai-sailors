import json

from storyquest.agent.context import Where
from storyquest.agent.critic import MAX_PROBLEM_CHARS, Critique, parse_critique, review
from storyquest.models.fake import FakeClient

WHERE = Where("Mowgli's Brothers", "A Warning at the Cave", 1000)


def verdict(v: str, problem: str = "") -> str:
    return json.dumps({"verdict": v, "problem": problem})


def test_approve_and_revise_are_read() -> None:
    assert parse_critique(verdict("approve", "ignored")) == Critique(True, "")
    assert parse_critique(verdict("revise", "The book does not say he is old.")) == Critique(
        False, "The book does not say he is old."
    )


def test_a_long_problem_is_cut_and_a_bad_answer_is_unreadable() -> None:
    long = parse_critique(verdict("revise", "x" * 500))
    assert long is not None and len(long.problem) == MAX_PROBLEM_CHARS
    for raw in ("not json", "{}", verdict("maybe")):
        assert parse_critique(raw) is None


def test_a_verdict_cut_off_by_the_token_limit_is_still_read() -> None:
    # what the course endpoint returned on 25 Nov: the limit hit before the JSON closed
    assert parse_critique('{\n  "verdict": "approve"') == Critique(True, "")
    cut = parse_critique('{"verdict": "revise", "problem": "The book does not say he dies')
    assert cut == Critique(False, "The book does not say he dies")
    assert parse_critique('{\n  "verd') is None


def test_the_critic_sees_the_question_the_passages_the_sentences_and_the_answer() -> None:
    llm = FakeClient(verdict("approve"))
    passages = "Father Wolf looked up. It was the jackal, Tabaqui."
    critique, trace = review(
        llm,
        "The Jungle Book",
        WHERE,
        "Who is Tabaqui?",
        passages,
        "It was the jackal.",
        "A jackal.",
    )
    assert critique == Critique(True) and trace.name == "critic"
    system, user = llm.calls[0][0]["content"], llm.calls[0][1]["content"]
    assert "The Jungle Book" in system and "A Warning at the Cave" in system
    assert "<question>\nWho is Tabaqui?\n</question>" in user
    assert f"<passages>\n{passages}\n</passages>" in user  # so "he" or "it" can be resolved
    assert "<book_sentences>\nIt was the jackal.\n</book_sentences>" in user
    assert user.endswith("<answer>\nA jackal.\n</answer>")


def test_the_critic_prompt_says_what_is_not_a_problem() -> None:
    from storyquest.agent.prompts import load_prompt

    prompt = load_prompt("critic").format(title="T", chapter="C", beat="B")
    assert "NOT problems" in prompt and "different or simpler words" in prompt
    assert "quote the exact words" in prompt
    assert '"verdict": "approve"' in prompt and '"verdict": "revise"' in prompt  # examples
