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
