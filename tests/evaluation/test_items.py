from pathlib import Path

from storyquest.domain.position import Position
from storyquest.evaluation.items import load_items, parse_hint


def test_parse_hint() -> None:
    assert parse_hint("lines 176-180, 228-229") == [(176, 180), (228, 229)]
    assert parse_hint("lines 122-124") == [(122, 124)]
    assert parse_hint("lines 246") == [(246, 246)]
    assert parse_hint("") == []


def test_golden_items_load(eval_dir: Path) -> None:
    items = {i.id: i for i in load_items(eval_dir / "golden_v1.jsonl")}
    assert len(items) == 80
    can3 = items["CAN-003"]
    assert can3.position == Position(0, 0)
    assert can3.fact_lines == [[(123, 123)], [(122, 122)]]  # one entry per expected fact
    assert can3.gold_lines == [(123, 123), (122, 122)]  # the union, when facts have evidence
    assert items["SPO-004"].position == Position(0, 2)


def test_every_fact_with_evidence_lines_up_with_its_fact(eval_dir: Path) -> None:
    with_evidence = [i for i in load_items(eval_dir / "golden_v1.jsonl") if i.fact_evidence]
    assert len(with_evidence) == 30
    for item in with_evidence:
        assert len(item.fact_evidence) == len(item.must_include) == len(item.fact_lines), item.id
    saf1 = {i.id: i for i in load_items(eval_dir / "golden_v1.jsonl")}["SAF-001"]
    assert saf1.fact_lines == [] and saf1.gold_lines  # falls back to gold_chunk_hint


def test_items_that_need_a_session_are_marked_skipped(eval_dir: Path) -> None:
    skipped = {i.id for i in load_items(eval_dir / "golden_v1.jsonl") if i.skip}
    assert skipped == {
        "FLO-001", "FLO-004", "FLO-005", "FLO-006", "FLO-007", "FLO-008", "INJ-004", "INJ-005"
    }  # fmt: skip


def test_placeholder_inputs_are_expanded(eval_dir: Path) -> None:
    items = {i.id: i for i in load_items(eval_dir / "golden_v1.jsonl")}
    assert len(items["MAL-002"].input) > 300
    assert items["MAL-001"].input == ""
    assert "[" not in items["SAF-007"].input
