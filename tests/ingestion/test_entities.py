from stage_llm import StageLLM

from storyquest.domain.book import Beat, Entity
from storyquest.ingestion.entities import (
    entity_key,
    extract_from_beat,
    first_occurrence,
    merge_into,
)

TEXT = (
    "Title\n\nIt was Mowgli who laughed. Later the man-cub, whom the wolves called Frog, "
    "met Bagheera the Black Panther.\n\nShere Khan came. Mowgli ran."
)
BEAT = Beat(0, 0, "t", "n", 0, len(TEXT))


def test_the_first_appearance_comes_from_the_text() -> None:
    assert first_occurrence(TEXT, ["Mowgli"], 0) == TEXT.index("Mowgli")
    assert first_occurrence(TEXT, ["frog", "Bagheera"], 0) == TEXT.index("Frog")  # earliest wins
    assert first_occurrence(TEXT, ["Mow"], 0) is None  # whole words only
    assert first_occurrence(TEXT, ["Mowgli"], TEXT.index("Shere")) == TEXT.rindex("Mowgli")


def test_keys_ignore_case_and_leading_articles() -> None:
    assert entity_key("The Black  Panther") == "black panther" == entity_key("black panther")


def item(name: str, **kw: object) -> dict[str, object]:
    return {"name": name, "kind": "character", "aliases": [], "card": f"About {name}.", **kw}


def test_entities_not_in_the_book_are_dropped() -> None:
    known: dict[str, Entity] = {}
    notes = merge_into(
        known, [item("Mowgli"), item("Zork")], text=TEXT, book_start=0, chapter_idx=2, beat=BEAT
    )
    assert list(known) == ["mowgli"] and any("Zork" in n for n in notes)
    e = known["mowgli"]
    assert e.first_char == TEXT.index("Mowgli") and (e.card_chapter, e.card_beat) == (2, 0)


def test_malformed_entities_are_skipped() -> None:
    known: dict[str, Entity] = {}
    merge_into(
        known,
        [item("", ), item("Mowgli", kind="monster"), item("Mowgli", card="")],
        text=TEXT, book_start=0, chapter_idx=0, beat=BEAT,
    )  # fmt: skip
    assert known == {}


def test_a_repeat_adds_aliases_but_keeps_the_first_card() -> None:
    known: dict[str, Entity] = {}
    merge_into(known, [item("Mowgli")], text=TEXT, book_start=0, chapter_idx=0, beat=BEAT)
    later = Beat(0, 3, "t", "n", 0, len(TEXT))
    merge_into(
        known,
        [item("Mowgli", card="Changed.", aliases=["Frog"]), item("Frog")],
        text=TEXT, book_start=0, chapter_idx=1, beat=later,
    )  # fmt: skip
    assert list(known) == ["mowgli"]  # "Frog" is an alias of Mowgli, not a new entity
    assert known["mowgli"].card == "About Mowgli." and "Frog" in known["mowgli"].aliases
    assert known["mowgli"].card_beat == 0


def test_the_model_answer_is_read_tolerantly() -> None:
    llm = StageLLM()
    items = extract_from_beat(
        llm, book_title="The Jungle Book", author="Kipling", scene="Mowgli ran."
    )
    assert [i["name"] for i in items] == ["Mowgli", "Zork Zorkson"]
    llm.mode = "garbage"
    assert extract_from_beat(llm, book_title="b", author="a", scene="Mowgli") == []


def test_ambiguous_and_generic_aliases_are_dropped() -> None:
    from storyquest.ingestion.entities import clean_aliases

    def entity(name: str, aliases: list[str]) -> Entity:
        return Entity(entity_key(name), name, "character", "card", 0, aliases)

    known = {
        "mowgli": entity("Mowgli", ["Little Brother", "man", "Man-cub", "Frog"]),
        "bagheera": entity("Bagheera", ["Little Brother", "Black Panther", "Akela"]),
        "akela": entity("Akela", ["Lone Wolf"]),
    }
    dropped = clean_aliases(known)
    assert known["mowgli"].aliases == ["Man-cub", "Frog"]  # shared and generic ones are gone
    assert known["bagheera"].aliases == ["Black Panther"]  # "Akela" is another entity's name
    assert known["akela"].aliases == ["Lone Wolf"] and dropped == 4
