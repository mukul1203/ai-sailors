from pathlib import Path

from storyquest.ingestion.names import find_names
from storyquest.ingestion.text import clean


def test_names_are_capitalised_words_that_never_appear_in_lowercase() -> None:
    text = "Then Kaa came. They saw the python, and they ran. Kaa left, then Mowgli waved."
    names = find_names(text)
    assert set(names) == {"kaa", "mowgli"}
    assert names["kaa"] == text.index("Kaa")


def test_short_words_and_all_capitals_are_ignored() -> None:
    text = "Oh no. THE BOOK. See Ahai! Al Bo."
    assert find_names(text) == {"ahai": text.index("Ahai")}


def test_a_word_only_ever_capitalised_at_the_start_of_a_sentence_is_not_a_name() -> None:
    text = "Rules are fun. Kaa said hello."
    assert set(find_names(text)) == set()
    assert set(find_names("The boy saw Kaa. Rules are fun.")) == {"kaa"}


def test_names_before_start_do_not_count() -> None:
    text = "Contents: Kaa\n\nChapter text. Mowgli met Kaa."
    names = find_names(text, start=text.index("Chapter"))
    assert names["kaa"] == text.rindex("Kaa")
    assert "contents" not in names


def test_jungle_book_names(eval_dir: Path) -> None:
    cleaned = clean((eval_dir / "books" / "236-the-jungle-book" / "raw.txt").read_text())
    first_chapter = cleaned.text.index("\nMowgli\u2019s Brothers\n\n") + 1
    names = find_names(cleaned.text, start=first_chapter)
    assert {"mowgli", "bagheera", "kaa", "tabaqui"} <= set(names)
    assert not {"then", "they", "the"} & set(names)
    assert names["mowgli"] < names["bagheera"] < names["kaa"]
