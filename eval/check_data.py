#!/usr/bin/env python3
"""Validate the golden eval set and the reference spine."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
GOLDEN = EVAL / "golden_v1.jsonl"
SPINE = EVAL / "spine_mowgli_brothers.json"
BOOK_DIR = EVAL / "books" / "236-the-jungle-book"
BOOK = BOOK_DIR / "raw.txt"
MANIFEST = BOOK_DIR / "book.yaml"

CATEGORIES = {"CAN", "CHR", "SPO", "OOC", "DIS", "FLO", "SAF", "INJ", "PII", "MAL"}
SPLITS = {"dev", "test"}
POSITIONS = {"B1", "B2", "B3", "B4", "B5"}
BEHAVIORS = {
    "answer", "deflect_in_character", "refuse_redirect", "ask_clarify", "advance_quest", "reassure"
}  # fmt: skip
REQUIRED = {
    "id",
    "category",
    "split",
    "position",
    "input",
    "expected_behavior",
    "must_include",
    "must_not_include",
    "evidence",
    "gold_chunk_hint",
    "notes",
}

errors = []


def err(msg):
    errors.append(msg)


def norm(text):
    text = text.translate(
        str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})
    )
    return re.sub(r"\s+", " ", text).strip().lower()


def line_ranges(spec):
    """Parse '79-81' or '247-248, 590-593' into (start, end) pairs; None if not numeric."""
    spec = spec.strip()
    if not spec or "+" in spec:
        return None
    ranges = []
    for part in spec.split(","):
        m = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not m:
            return None
        start = int(m.group(1))
        ranges.append((start, int(m.group(2) or start)))
    return ranges


def check_book():
    manifest = MANIFEST.read_text()
    m = re.search(r"^sha256:\s*([0-9a-f]{64})", manifest, re.M)
    import hashlib

    actual = hashlib.sha256(BOOK.read_bytes()).hexdigest()
    if not m or m.group(1) != actual:
        err(
            f"{BOOK.relative_to(ROOT)}: hash does not match book.yaml (line numbers in the eval set may be stale)"
        )
    else:
        print("fixture hash: ok")
    return BOOK.read_text().splitlines()


def beat_ends():
    """Last source line of each beat: a child at B3 has read everything up to B3's end."""
    spine = json.loads(SPINE.read_text())
    return {b["id"]: int(b["source_lines"].split("-")[1]) for b in spine["beats"]}


def check_fact_evidence(rid, row, book_lines, ends):
    """Each expected fact needs lines, an exact quote inside them, and lines the child has read."""
    evidence = row["fact_evidence"]
    if not isinstance(evidence, list) or len(evidence) != len(row["must_include"]):
        err(f"{rid}: fact_evidence must have one entry per must_include fact")
        return 0
    verified = 0
    for i, entry in enumerate(evidence, 1):
        ranges = line_ranges(entry.get("lines", "")) if isinstance(entry, dict) else None
        if not ranges or not entry.get("quote"):
            err(f"{rid}: fact {i} needs numeric lines and a quote")
            continue
        chunk = " ".join(" ".join(book_lines[s - 1 : e]) for s, e in ranges)
        if norm(entry["quote"]) not in norm(chunk):
            err(f"{rid}: fact {i} quote not found in lines {entry['lines']}: {entry['quote']!r}")
            continue
        last = max(e for _, e in ranges)
        if last > ends[row["position"]]:
            err(
                f"{rid}: fact {i} evidence ends at line {last}, after the end of {row['position']} (line {ends[row['position']]})"
            )
            continue
        verified += 1
    return verified


def check_golden(book_lines):
    seen = set()
    count = 0
    quoted = 0
    fact_quotes = 0
    ends = beat_ends()
    for n, line in enumerate(GOLDEN.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            err(f"golden line {n}: invalid JSON ({e})")
            continue
        count += 1
        rid = row.get("id", f"line {n}")
        missing = REQUIRED - row.keys()
        if missing:
            err(f"{rid}: missing fields {sorted(missing)}")
            continue
        if rid in seen:
            err(f"{rid}: duplicate id")
        seen.add(rid)
        if not re.fullmatch(r"[A-Z]{3}-\d{3}", rid) or not rid.startswith(row["category"]):
            err(f"{rid}: id must look like CAT-001 and match its category")
        if row["category"] not in CATEGORIES:
            err(f"{rid}: unknown category {row['category']}")
        if row["split"] not in SPLITS:
            err(f"{rid}: unknown split {row['split']}")
        if row["position"] not in POSITIONS:
            err(f"{rid}: unknown position {row['position']}")
        if row["expected_behavior"] not in BEHAVIORS:
            err(f"{rid}: unknown expected_behavior {row['expected_behavior']}")
        if row["category"] == "SPO" and not row["must_not_include"]:
            err(f"{rid}: spoiler item needs must_not_include")
        if (
            not isinstance(row["evidence"], dict)
            or not {"lines", "quote"} <= row["evidence"].keys()
        ):
            err(f"{rid}: evidence needs lines and quote")
        else:
            ranges = line_ranges(row["evidence"]["lines"])
            quote = row["evidence"]["quote"]
            if ranges and not quote.startswith("("):
                quoted += 1
                chunk = " ".join(" ".join(book_lines[s - 1 : e]) for s, e in ranges)
                if norm(quote) not in norm(chunk):
                    err(
                        f"{rid}: evidence quote not found in lines {row['evidence']['lines']}: {quote!r}"
                    )
        if "fact_evidence" in row:
            fact_quotes += check_fact_evidence(rid, row, book_lines, ends)
    print(
        f"golden set: {count} items, {quoted} evidence quotes and {fact_quotes} per-fact quotes verified against the book"
    )


def check_spine():
    spine = json.loads(SPINE.read_text())
    prev_end = 0
    for beat in spine["beats"]:
        bid = beat["id"]
        try:
            start, end = (int(x) for x in beat["source_lines"].split("-"))
        except ValueError:
            err(f"spine {bid}: bad source_lines {beat['source_lines']!r}")
            continue
        if start > end or start <= prev_end:
            err(f"spine {bid}: lines {start}-{end} overlap or are out of order")
        prev_end = end
        if bid not in POSITIONS:
            err(f"spine {bid}: not a known position")
        for card in beat.get("choice", {}).get("cards", []):
            if "id" not in card or "next" not in card:
                err(f"spine {bid}: choice card needs id and next")
    print(f"spine: {len(spine['beats'])} beats")


book_lines = check_book()
check_golden(book_lines)
check_spine()
if errors:
    print("\n".join(f"ERROR: {e}" for e in errors))
    sys.exit(1)
print("ok")
