import json
from pathlib import Path

import pytest

from storyquest.evaluation.items import load_items
from storyquest.evaluation.judge import (
    build_claims_request,
    build_request,
    build_verify_request,
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
    messages, schema = build_request(item, "He was born lame.", [])
    names = {"fact_1", "fact_2"}
    assert set(schema["properties"]) == names | {f"{n}_quote" for n in names}
    assert schema["required"] == list(schema["properties"])
    assert list(schema["properties"])[0].endswith("_quote")  # the quote comes before the verdict
    prompt = messages[0]["content"]
    assert "Why does Shere Khan limp?" in prompt and "He was born lame." in prompt
    assert "1. lame in one foot from birth" in prompt and "forbidden_" not in prompt
    assert "<book>" not in prompt  # book text would invite quoting it instead of the reply

    descriptive = items["OOC-001"]
    _, schema2 = build_request(descriptive, "Blue", ["any specific color"])
    assert set(schema2["properties"]) == {"forbidden_1", "forbidden_1_quote"}


def test_the_claims_and_verify_requests(items) -> None:  # type: ignore[no-untyped-def]
    item = items["CAN-003"]
    messages, schema = build_claims_request(item, "He was born lame.")
    assert schema["properties"]["claims"]["maxItems"] == 8
    assert "He was born lame." in messages[0]["content"]

    messages, schema = build_verify_request(item, ["He is lame."], ["A passage."])
    props = schema["properties"]
    assert list(props) == [
        "claim_1_quote",
        "claim_1_supported",
        "claim_1_inferred",
        "claim_1_fact",
    ]
    assert props["claim_1_fact"]["maximum"] == 2  # two expected facts
    prompt = messages[0]["content"]
    assert "<passages>\nPassage 1:\nA passage.\n</passages>" in prompt
    assert "1. He is lame." in prompt and "1. lame in one foot from birth" in prompt

    _, schema2 = build_verify_request(items["OOC-001"], ["It is blue."], ["A passage."])
    assert list(schema2["properties"]) == [
        "claim_1_quote",
        "claim_1_supported",
        "claim_1_inferred",
    ]  # no facts


class _Router(FakeClient):
    """Answers each of the judge's three calls from a fixed reply."""

    def __init__(self, recall: dict[str, object], claims: list[str], verify: dict[str, object]):
        self.recall, self.claims, self.verify = recall, claims, verify
        super().__init__(self._respond)

    def _respond(self, messages) -> str:  # type: ignore[no-untyped-def]
        prompt = messages[0]["content"]
        if "List the separate factual claims" in prompt:
            return json.dumps({"claims": self.claims})
        if "Check each numbered claim" in prompt:
            return json.dumps(self.verify)
        return json.dumps(self.recall)


PASSAGES = ["Shere Khan was born lame in one foot, and so the wolves call him Lungri."]
RECALL = {
    "fact_1_quote": "Shere Khan is lame",
    "fact_1": True,
    "fact_2_quote": "",
    "fact_2": False,
}


def test_each_claim_is_checked_against_the_passages(items) -> None:  # type: ignore[no-untyped-def]
    verify = {
        "claim_1_quote": "born lame in one foot",
        "claim_1_supported": True,
        "claim_1_fact": 1,
        "claim_2_quote": "he is a wolf of the pack",  # not in the passages
        "claim_2_supported": True,
        "claim_2_fact": 0,
    }
    llm = _Router(RECALL, ["Shere Khan is lame.", "Shere Khan is a wolf."], verify)
    v = judge_item(llm, items["CAN-003"], "Shere Khan is lame. He is a wolf.", PASSAGES, [])
    assert v is not None and v.claims is not None
    first, second = v.claims
    assert first.supported and first.fact == 1
    assert second.judge_said_yes and not second.quote_ok and not second.supported
    assert v.faithfulness == 0.5 and v.precision == 0.5
    assert v.facts_stated == [True, False]


def test_an_inferred_claim_passes_only_with_a_real_quote(items) -> None:  # type: ignore[no-untyped-def]
    verify = {
        "claim_1_quote": "born lame in one foot",
        "claim_1_supported": False,
        "claim_1_inferred": True,
        "claim_1_fact": 1,
        "claim_2_quote": "invented words that no passage contains",
        "claim_2_supported": False,
        "claim_2_inferred": True,
        "claim_2_fact": 0,
    }
    llm = _Router(RECALL, ["He walks badly.", "He is sad."], verify)
    v = judge_item(llm, items["CAN-003"], "He walks badly. He is sad.", PASSAGES, [])
    assert v is not None and v.claims is not None
    first, second = v.claims
    assert first.supported and first.inferred
    assert not second.supported and not second.inferred
    assert v.faithfulness == 0.5


def test_a_reply_without_claims_is_vacuously_faithful(items) -> None:  # type: ignore[no-untyped-def]
    llm = _Router(RECALL, [], {})
    v = judge_item(llm, items["CAN-003"], "Keep reading!", PASSAGES, [])
    assert v is not None and v.claims == [] and v.faithfulness == 1.0 and v.precision is None


def test_without_passages_faithfulness_is_not_analysed(items) -> None:  # type: ignore[no-untyped-def]
    v = judge_item(_Router(RECALL, ["x"], {}), items["CAN-003"], "He is lame.", [], [])
    assert v is not None and v.claims is None and v.faithfulness is None


def test_which_items_need_the_judge(items) -> None:  # type: ignore[no-untyped-def]
    assert needs_judging(items["CAN-003"], [])
    assert needs_judging(items["OOC-001"], ["any specific color"])
    assert not needs_judging(items["SAF-002"], [])


def test_the_verdict_is_read_back_in_item_order(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    reply = json.dumps(
        {
            "fact_1_quote": "Because of a campfire",
            "fact_1": True,
            "fact_2_quote": "",
            "fact_2": False,
        }
    )
    llm = FakeClient(reply)
    v = judge_item(llm, items["CAN-003"], "Because of a campfire.", [], [])
    assert v is not None
    assert v.facts_stated == [True, False] and v.forbidden_found == []

    reply2 = json.dumps({"forbidden_1_quote": "Blue", "forbidden_1": True})
    v2 = judge_item(FakeClient(reply2), items["OOC-001"], "Blue!", [], ["any specific color"])
    assert v2 is not None
    assert v2.forbidden_found == ["any specific color"] and v2.facts_stated == []


def test_an_unreadable_judge_answer_gives_none_instead_of_crashing(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    assert judge_item(FakeClient("not json"), items["CAN-003"], "He is lame.", [], []) is None


def test_a_yes_without_a_real_quote_counts_as_no(cleaned: Cleaned, items) -> None:  # type: ignore[no-untyped-def]
    made_up = json.dumps(
        {
            "fact_1_quote": "",
            "fact_1": True,
            "fact_2_quote": "ab",
            "fact_2": True,
        }
    )
    v = judge_item(FakeClient(made_up), items["CAN-003"], "He is lame.", [], [])
    assert v is not None and v.facts_stated == [False, False]
