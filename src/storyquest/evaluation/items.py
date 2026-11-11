"""Golden-set items: loading, position mapping and which items the text runner can run."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from storyquest.domain.position import Position

# Items whose input stands for something too long to store in the file.
_PLACEHOLDERS = {"[2000-character paste]": "blah " * 400}


@dataclass(frozen=True)
class GoldItem:
    id: str
    category: str
    split: str
    position: Position
    input: str
    expected_behavior: str
    must_include: list[str]
    must_not_include: list[str]
    gold_lines: list[tuple[int, int]]  # raw-file line ranges holding the answer
    skip: str | None


def parse_hint(hint: str) -> list[tuple[int, int]]:
    """'lines 176-180, 228' -> [(176, 180), (228, 228)]."""
    return [(int(a), int(b or a)) for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", hint)]


def _position(label: str) -> Position:
    """'B3' is the third beat of chapter 0; the golden set covers the first chapter only."""
    return Position(0, int(label.removeprefix("B")) - 1)


def load_items(path: Path) -> list[GoldItem]:
    items = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        text = row["input"]
        items.append(
            GoldItem(
                id=row["id"],
                category=row["category"],
                split=row["split"],
                position=_position(row["position"]),
                input=_PLACEHOLDERS.get(text, text),
                expected_behavior=row["expected_behavior"],
                must_include=row["must_include"],
                must_not_include=row["must_not_include"],
                gold_lines=parse_hint(row["gold_chunk_hint"]),
                skip=row.get("skip"),
            )
        )
    return items
