import json
from pathlib import Path

import pytest

from storyquest.evaluation.items import load_items
from storyquest.evaluation.judge import (
    build_request,
    evidence_text,
    judge_item,
    needs_judging,
)
from storyquest.ingestion.text import Cleaned, clean
from storyquest.models.fake import FakeClient


@pytest.fixture(scope="module")
def cleaned(eval_dir: Path) -> Cleaned:
    return clean((eval_dir / "books" / "236-the-jungle-book" / "raw.txt").read_text())


@pytest.fixture(scope="module")
def items(eval_dir: Path):  # type: ignore[no-untyped-def]
    return {i.id: i for i in load_items(eval_dir / "golden_v1.jsonl")}


def test_evidence_is_the_gold_lines_from_the_book(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    text = evidence_text(items["CAN-003"], cleaned)
    assert "Lungri" in text and "lame in one foot" in text
    assert len(text) < 400
    assert evidence_text(items["OOC-001"], cleaned) == ""


def test_the_request_asks_only_about_what_the_item_needs(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    item = items["CAN-003"]
    messages, schema = build_request(item, "He was born lame.", evidence_text(item, cleaned), [])
    names = {"contradicts_book", "fact_1", "fact_2"}
    assert set(schema["properties"]) == names | {f"{n}_quote" for n in names}
    assert schema["required"] == list(schema["properties"])
    assert list(schema["properties"])[0].endswith("_quote")  # the quote comes before the verdict
    prompt = messages[0]["content"]
    assert "Why does Shere Khan limp?" in prompt and "He was born lame." in prompt
    assert "1. lame in one foot from birth" in prompt and "forbidden_" not in prompt

    descriptive = items["OOC-001"]
    _, schema2 = build_request(descriptive, "Blue", "", ["any specific color"])
    assert set(schema2["properties"]) == {"forbidden_1", "forbidden_1_quote"}


def test_which_items_need_the_judge(items) -> None:  # type: ignore[no-untyped-def]
    assert needs_judging(items["CAN-003"], [])
    assert needs_judging(items["OOC-001"], ["any specific color"])
    assert not needs_judging(items["SAF-002"], [])


def test_the_verdict_is_read_back_in_item_order(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    reply = json.dumps(
        {
            "contradicts_book_quote": "a campfire",
            "contradicts_book": True,
            "fact_1_quote": "Because of a campfire",
            "fact_1": True,
            "fact_2_quote": "",
            "fact_2": False,
        }
    )
    llm = FakeClient(reply)
    v = judge_item(llm, items["CAN-003"], "Because of a campfire.", cleaned, [])
    assert v.facts_stated == [True, False] and v.contradicts_book and v.forbidden_found == []

    reply2 = json.dumps({"forbidden_1_quote": "Blue", "forbidden_1": True})
    v2 = judge_item(FakeClient(reply2), items["OOC-001"], "Blue!", cleaned, ["any specific color"])
    assert v2.forbidden_found == ["any specific color"] and v2.facts_stated == []


def test_a_yes_without_a_real_quote_counts_as_no(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    made_up = json.dumps(
        {
            "contradicts_book_quote": "words that are not in the reply",
            "contradicts_book": True,
            "fact_1_quote": "",
            "fact_1": True,
            "fact_2_quote": "ab",
            "fact_2": True,
        }
    )
    v = judge_item(FakeClient(made_up), items["CAN-003"], "He is lame.", cleaned, [])
    assert v.facts_stated == [False, False] and not v.contradicts_book
