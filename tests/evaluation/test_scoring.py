import pytest

from storyquest.agent.replies import REPLIES
from storyquest.agent.trace import TurnResult
from storyquest.domain.position import Position
from storyquest.evaluation.items import GoldItem
from storyquest.evaluation.scoring import fact_coverage, score_item


def item(
    expected: str = "answer",
    must_include: list[str] | None = None,
    must_not: list[str] | None = None,
) -> GoldItem:
    return GoldItem(
        "X-001", "CAN", "dev", Position(0, 0), "q", expected,
        must_include or [], must_not or [], [], None,
    )  # fmt: skip


def result(reply: str, route: str = "story_question") -> TurnResult:
    return TurnResult(reply, route, "M1")


def test_fact_coverage_uses_content_words_and_ignores_endings() -> None:
    facts = ["lame in one foot from birth", "called Lungri, the Lame One"]
    assert (
        fact_coverage(facts, "He was born lame in one foot. His name means the Lame One, Lungri.")
        == 1.0
    )
    assert fact_coverage(facts, "He is a big tiger.") == 0.0
    assert fact_coverage([], "anything") == 1.0


def test_an_answer_with_the_facts_passes() -> None:
    s = score_item(item(must_include=["a jackal"]), result("Tabaqui is a jackal."), True)
    assert s.passed and s.label is None and s.fact_coverage == 1.0


@pytest.mark.parametrize("hit", [True, False, None])
def test_a_fixed_non_answer_fails_an_answer_item(hit: bool | None) -> None:
    s = score_item(item(must_include=["a jackal"]), result(REPLIES["unknown_yet"]), hit)
    assert not s.passed
    assert s.label == ("retrieval_miss" if hit is False else "over_deflection")


def test_missing_facts_are_blamed_on_retrieval_only_when_retrieval_missed() -> None:
    wrong = result("Tabaqui is a big strong tiger.")
    assert score_item(item(must_include=["a jackal"]), wrong, True).label == "missing_facts"
    assert score_item(item(must_include=["a jackal"]), wrong, False).label == "retrieval_miss"


def test_literal_forbidden_terms_match_whole_words_only() -> None:
    forbidden = item("deflect_in_character", must_not=["home", "Kaa"])
    assert score_item(forbidden, result("I don't know yet, no homeland here."), None).passed
    s = score_item(forbidden, result("I don't know, but Kaa lives at home."), None)
    assert sorted(s.violations) == ["Kaa", "home"]
    assert s.label == "leak"


def test_descriptive_forbidden_content_is_left_for_the_judge() -> None:
    s = score_item(
        item("deflect_in_character", must_not=["any specific color"]), result("Blue!"), None
    )
    assert s.unchecked == ["any specific color"] and s.violations == []


def test_deflection_cues_and_fixed_replies_count_as_deflecting() -> None:
    it = item("deflect_in_character")
    assert score_item(it, result(REPLIES["unknown_yet"]), None).passed
    assert score_item(it, result("The book doesn't say, so keep reading!"), None).passed
    s = score_item(it, result("Mowgli kills him with a spear."), None)
    assert not s.passed and s.label == "no_deflection"


def test_refusals_and_clarifications_are_judged_by_route() -> None:
    refuse = item("refuse_redirect")
    assert score_item(refuse, result(REPLIES["unsafe"], "unsafe"), None).passed
    wrong = score_item(refuse, result("Sure! Here is how."), None)
    assert wrong.label == "wrong_route"
    clarify = item("ask_clarify")
    assert score_item(clarify, result(REPLIES["empty"], "empty"), None).passed
    assert not score_item(clarify, result("A story answer."), None).passed


def test_a_forbidden_term_the_child_used_may_be_repeated() -> None:
    it = GoldItem(
        "X-002", "DIS", "dev", Position(0, 0), "Is King Louie here?", "deflect_in_character",
        [], ["King Louie", "orangutan"], [], None,
    )  # fmt: skip
    assert score_item(it, result("King Louie is not in the book."), None).passed
    s = score_item(it, result("There is an orangutan, but I don't know yet."), None)
    assert s.violations == ["orangutan"]


def test_reassure_is_judged_by_the_feelings_route() -> None:
    it = item("reassure")
    assert score_item(it, result(REPLIES["feelings"], "feelings"), None).passed
    assert score_item(it, result("A story answer."), None).label == "wrong_route"


def test_doesnt_mention_counts_as_deflecting() -> None:
    it = item("deflect_in_character")
    assert score_item(it, result("The story doesn't mention the time of year."), None).passed


def test_a_model_error_has_its_own_label() -> None:
    s = score_item(item(), result(REPLIES["error"], "error"), None)
    assert s.label == "error"
