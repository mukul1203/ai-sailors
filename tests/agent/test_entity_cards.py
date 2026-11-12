from collections.abc import Callable
from dataclasses import replace

import pytest

from llm_helpers import ScriptedLLM
from storyquest.agent.context import AgentContext
from storyquest.agent.modes import Mode, get_mode
from storyquest.agent.retrieval import MAX_CARDS, entity_cards, retrieve
from storyquest.agent.turn import run_turn
from storyquest.domain.book import Entity
from storyquest.domain.position import Position
from storyquest.ingestion.entities import first_occurrence
from storyquest.ingestion.pipeline import load_cleaned
from storyquest.models.llm import LLMClient

pytestmark = pytest.mark.integration

CARDS = Mode("T", "keywords + entity cards", retrieval=True, entities=True)


@pytest.fixture
def ctx(make_ctx: Callable[[LLMClient], AgentContext]) -> AgentContext:
    base = make_ctx(ScriptedLLM(answer="Tabaqui is a jackal."))
    text = load_cleaned(base.settings.data_dir, base.book).text

    def card(name: str, chapter: int, beat: int, aliases: list[str] | None = None) -> Entity:
        found = first_occurrence(text, [name], 0)
        assert found is not None
        return Entity(
            key=name.lower(), name=name, kind="character", card=f"{name} is a character.",
            first_char=found, aliases=aliases or [], card_chapter=chapter, card_beat=beat,
        )  # fmt: skip

    entities = [
        card("Tabaqui", 0, 0),
        card("Akela", 0, 2, ["Lone Wolf"]),
        card("Mowgli", 0, 1),
        card("Bagheera", 0, 2),
    ]
    return replace(base, entities=entities)


def names(hits: list) -> list[str]:  # type: ignore[type-arg]
    return [h.text.split(":")[0] for h in hits if h.source == "entity"]


def test_a_named_character_gets_its_card(ctx: AgentContext) -> None:
    cards = entity_cards(ctx, "Who is Tabaqui?", Position(0, 0))
    assert names(cards) == ["Tabaqui"]
    assert cards[0].source == "entity" and cards[0].start_char == -1
    assert cards[0].text == "Tabaqui: Tabaqui is a character."


def test_aliases_and_case_match_whole_words_only(ctx: AgentContext) -> None:
    assert names(entity_cards(ctx, "tell me about the lone wolf", Position(0, 3))) == ["Akela"]
    assert entity_cards(ctx, "What is a Tabaquis?", Position(0, 0)) == []


def test_a_card_is_hidden_until_the_child_has_reached_it(ctx: AgentContext) -> None:
    assert entity_cards(ctx, "Who is Akela?", Position(0, 1)) == []  # card from beat 3
    assert names(entity_cards(ctx, "Who is Akela?", Position(0, 2))) == ["Akela"]
    # Bagheera's name appears early in the text but its card comes from beat 3
    assert entity_cards(ctx, "Who is Bagheera?", Position(0, 0)) == []


def test_at_most_two_cards_are_added(ctx: AgentContext) -> None:
    cards = entity_cards(ctx, "Do Mowgli, Akela and Bagheera meet?", Position(0, 4))
    assert len(cards) == MAX_CARDS == 2


def test_cards_follow_the_book_text_and_need_it(ctx: AgentContext) -> None:
    hits, _ = retrieve(ctx, CARDS, "Who is Tabaqui?", Position(0, 0))
    assert hits[-1].source == "entity" and all(h.source == "chunk" for h in hits[:-1])
    assert hits[0].source == "chunk"
    plain, _ = retrieve(ctx, get_mode("M1"), "Who is Tabaqui?", Position(0, 0))
    assert all(h.source == "chunk" for h in plain)  # the other modes never get cards


def test_a_turn_in_a_card_mode_shows_the_card_as_a_passage(ctx: AgentContext) -> None:
    result = run_turn(ctx, "Who is Tabaqui?", Position(0, 0), mode=CARDS)
    assert result.reply == "Tabaqui is a jackal."
    assert names(result.passages) == ["Tabaqui"]
    prompt = ctx.llm.calls[-1][1]["content"]  # type: ignore[attr-defined]
    assert "Tabaqui: Tabaqui is a character." in prompt


def test_the_entity_modes_are_registered() -> None:
    assert get_mode("M3").entities and get_mode("M3").hybrid and not get_mode("M3").grounded
    assert get_mode("M3S").entities and get_mode("M3S").grounded
