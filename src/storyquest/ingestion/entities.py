"""Stage 8: entity cards (characters, places and terms) with the point where each first appears.

One call per beat lists what appears in it. Code keeps an entity only if its name really occurs
in the book text, takes `first_char` from the text itself (never from the model), and merges
repeats across beats. A card is written from the first beat that mentions the entity, so it
cannot spoil later events.
"""

import json
import re
from dataclasses import replace
from typing import Any

from storyquest.domain.book import Beat, Entity
from storyquest.ingestion.prompts import load_prompt
from storyquest.models.llm import LLMClient

MAX_TOKENS = 900
MAX_PER_SCENE = 8
MAX_ALIASES = 3
MIN_ALIAS_CHARS = 4
MAX_NAME_CHARS = 40
KINDS = ("character", "place", "term")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "maxItems": MAX_PER_SCENE,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "aliases": {
                        "type": "array",
                        "maxItems": MAX_ALIASES,
                        "items": {"type": "string"},
                    },
                    "card": {"type": "string"},
                },
                "required": ["name", "kind", "aliases", "card"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entities"],
    "additionalProperties": False,
}


def entity_key(name: str) -> str:
    return re.sub(r"^(the|a|an)\s+", "", " ".join(name.lower().split()))


def first_occurrence(text: str, names: list[str], start: int) -> int | None:
    """The earliest offset at or after `start` where any of the names appears as whole words."""
    best: int | None = None
    for name in names:
        if not name.strip():
            continue
        m = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE).search(text, start)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def _read(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    items = data.get("entities") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def extract_from_beat(
    llm: LLMClient,
    *,
    book_title: str,
    author: str,
    scene: str,
) -> list[dict[str, Any]]:
    prompt = load_prompt("entities").format(title=book_title, author=author, scene=scene)
    result = llm.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
        temperature=0.0,
        json_schema=SCHEMA,
    )
    return _read(result.text)


def clean_aliases(known: dict[str, Entity]) -> int:
    """Drop aliases that would send a child to the wrong card: ones shared with another entity
    or equal to its name, generic lowercase words ("man", "dog"), and very short ones. Returns
    how many were dropped."""
    owners: dict[str, int] = {}
    for key, entity in known.items():
        for alias_key in {key, *(entity_key(a) for a in entity.aliases)}:
            owners[alias_key] = owners.get(alias_key, 0) + 1
    dropped = 0
    for key, entity in known.items():
        kept = [
            a
            for a in entity.aliases
            if len(a) >= MIN_ALIAS_CHARS
            and any(ch.isupper() for ch in a)
            and owners[entity_key(a)] == 1
        ]
        dropped += len(entity.aliases) - len(kept)
        known[key] = replace(entity, aliases=kept)
    return dropped


def merge_into(
    known: dict[str, Entity],
    items: list[dict[str, Any]],
    *,
    text: str,
    book_start: int,
    chapter_idx: int,
    beat: Beat,
) -> list[str]:
    """Add the entities of one beat to `known` (keyed by entity_key). Returns notes about
    anything dropped. An entity already known gains the new aliases but keeps its card."""
    notes: list[str] = []
    alias_to_key = {entity_key(a): k for k, e in known.items() for a in e.aliases}
    for item in items:
        name = " ".join(str(item.get("name") or "").split())
        kind = str(item.get("kind") or "")
        card = " ".join(str(item.get("card") or "").split())
        aliases = [
            " ".join(str(a).split())
            for a in (item.get("aliases") or [])
            if isinstance(a, str) and a.strip()
        ][:MAX_ALIASES]
        if not name or len(name) > MAX_NAME_CHARS or kind not in KINDS or not card:
            notes.append(f"skipped a malformed entity {name!r}")
            continue
        found = first_occurrence(text, [name, *aliases], book_start)
        if found is None:
            notes.append(f"dropped {name!r}: not found in the book text")
            continue
        key = entity_key(name)
        key = alias_to_key.get(key, key)
        if key in known:
            old = known[key]
            extra = [a for a in [name, *aliases] if entity_key(a) != key and a not in old.aliases]
            known[key] = Entity(
                key=old.key, name=old.name, kind=old.kind, card=old.card,
                first_char=min(old.first_char, found), aliases=[*old.aliases, *extra],
                card_chapter=old.card_chapter, card_beat=old.card_beat,
            )  # fmt: skip
            alias_to_key.update({entity_key(a): key for a in extra})
            continue
        known[key] = Entity(
            key=key, name=name, kind=kind, card=card, first_char=found,
            aliases=[a for a in aliases if entity_key(a) != key],
            card_chapter=chapter_idx, card_beat=beat.idx,
        )  # fmt: skip
        alias_to_key.update({entity_key(a): key for a in known[key].aliases})
    return notes
