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
    assert can3.gold_lines == [(122, 124)]
    assert items["SPO-004"].position == Position(0, 2)


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
