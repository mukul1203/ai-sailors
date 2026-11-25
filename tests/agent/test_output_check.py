import pytest

from storyquest.agent.modes import get_mode
from storyquest.agent.output_check import check_reply

NAMES = {"kaa": 5000, "mowgli": 10}


def test_a_clean_reply_has_no_flags() -> None:
    assert check_reply("Mowgli lives with the wolves.", "Who is he?", NAMES, boundary=100) == []


def test_film_and_cartoon_words_are_flagged_as_whole_words() -> None:
    assert check_reply("It is a Disney cartoon.", "", NAMES, 100) == [
        "banned_term:disney",
        "banned_term:cartoon",
    ]
    assert check_reply("She is filmy and moviegoers laugh.", "", NAMES, 100) == []


def test_names_first_seen_after_the_boundary_are_flagged_once() -> None:
    assert check_reply("Kaa! Kaa is a snake.", "", NAMES, boundary=100) == ["later_name:kaa"]
    assert check_reply("Kaa is a snake.", "", NAMES, boundary=6000) == []


def test_a_name_the_child_used_is_allowed() -> None:
    assert check_reply("Who Kaa is comes later.", "Who is KAA?", NAMES, boundary=100) == []


def test_a_film_word_the_child_used_is_allowed() -> None:
    reply = "That is not in the book, only in a Disney film."
    assert check_reply(reply, "Is it like Disney?", NAMES, 100) == ["banned_term:film"]


def test_modes() -> None:
    assert get_mode("m1").retrieval and not get_mode("M0").retrieval
    with pytest.raises(ValueError, match="Unknown mode"):
        get_mode("M9")


def test_talk_about_the_ending_is_flagged() -> None:
    planted = "Shere Khan is a tiger. At the end of the book, Mowgli kills Shere Khan."
    assert check_reply(planted, "Who is Shere Khan?", {}, boundary=100) == ["ending_talk"]
    assert check_reply("Later in the story he comes back.", "Who?", {}, boundary=100) == [
        "ending_talk"
    ]
    # the end of a scene or chapter the child has read is fine
    assert check_reply("At the end of the chapter they sleep.", "What?", {}, boundary=100) == []
