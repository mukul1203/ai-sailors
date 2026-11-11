"""Chunking: pack paragraphs into chunks of roughly `target` characters inside one span.

Chunks are exact slices of the text, so they can be quoted and traced back to offsets.
A chunk never extends outside the span it was made from (the span is a beat).
"""

import re

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n\s*")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"\u201d\u2019]?\s+")

Span = tuple[int, int]


def _trimmed(text: str, a: int, b: int) -> Span | None:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return (a, b) if a < b else None


def _paragraphs(text: str, start: int, end: int) -> list[Span]:
    spans: list[Span] = []
    pos = start
    for m in _PARAGRAPH_BREAK.finditer(text, start, end):
        if (s := _trimmed(text, pos, m.start())) is not None:
            spans.append(s)
        pos = m.end()
    if (s := _trimmed(text, pos, end)) is not None:
        spans.append(s)
    return spans


def _sentences(text: str, a: int, b: int) -> list[Span]:
    spans: list[Span] = []
    pos = a
    for m in _SENTENCE_END.finditer(text, a, b):
        if (s := _trimmed(text, pos, m.start() + len(m.group().rstrip()))) is not None:
            spans.append(s)
        pos = m.end()
    if (s := _trimmed(text, pos, b)) is not None:
        spans.append(s)
    return spans


def _pack(spans: list[Span], target: int) -> list[Span]:
    chunks: list[Span] = []
    current: Span | None = None
    for a, b in spans:
        if current is None:
            current = (a, b)
        elif b - current[0] > target:
            chunks.append(current)
            current = (a, b)
        else:
            current = (current[0], b)
    if current is not None:
        chunks.append(current)
    return chunks


def chunk_span(text: str, start: int, end: int, *, target: int, max_len: int) -> list[Span]:
    """Split text[start:end] into chunk spans, in order."""
    chunks: list[Span] = []
    pending: list[Span] = []
    for a, b in _paragraphs(text, start, end):
        if b - a > max_len:
            chunks.extend(_pack(pending, target))
            pending = []
            chunks.extend(_pack(_sentences(text, a, b), target))
        else:
            pending.append((a, b))
    chunks.extend(_pack(pending, target))
    return chunks
