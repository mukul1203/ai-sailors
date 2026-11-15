"""Retrieval on its own: does search put the gold passage in the top k? No chat-model calls.

The capstone asks for retrieval recall@k measured apart from answer quality, because a weak
generator can hide a good search (or a lucky answer can hide a bad one). This runs the same
position-filtered searches the agent uses, keyword, meaning and hybrid, for several k at once,
so chunking and embedding experiments take seconds instead of a full eval run.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from storyquest.agent.context import AgentContext
from storyquest.evaluation.items import GoldItem
from storyquest.ingestion.text import Cleaned
from storyquest.stores.search import hybrid_search, search_chunks
from storyquest.stores.vector import dense_search, has_vectors

METHODS = ("bm25", "dense", "hybrid")


@dataclass(frozen=True)
class RecallRow:
    method: str
    k: int
    passages_found: int  # questions whose gold passage was in the top k
    passage_questions: int  # questions that have a gold passage
    facts_found: int  # expected facts whose evidence lines were in the top k
    facts: int


def measurable(items: Sequence[GoldItem]) -> list[GoldItem]:
    """Questions retrieval can be scored on: a non-empty input with gold lines to find."""
    return [i for i in items if not i.skip and i.input.strip() and (i.gold_lines or i.fact_lines)]


def _ranked(
    ctx: AgentContext, method: str, item: GoldItem, vector: list[float] | None, depth: int
) -> list[int]:
    s, book = ctx.settings, ctx.book.id
    if method == "bm25":
        return [
            h.chunk_id
            for h in search_chunks(ctx.conn, book, item.input, item.position, limit=depth)
        ]
    assert ctx.embedder is not None and vector is not None
    if method == "dense":
        found = dense_search(
            ctx.conn, book, vector, item.position, ctx.embedder.model_id, limit=depth
        )
        return [chunk_id for chunk_id, _ in found]
    hits = hybrid_search(
        ctx.conn,
        book,
        item.input,
        vector,
        ctx.embedder.model_id,
        item.position,
        limit=depth,
        candidates=s.retrieval_candidates,
        rrf_k=s.rrf_k,
    )
    return [h.chunk_id for h in hits]


def retrieval_recall(
    ctx: AgentContext, cleaned: Cleaned, items: Sequence[GoldItem], ks: Sequence[int]
) -> list[RecallRow]:
    """Recall at each k for every search method the context can run (meaning and hybrid need
    the embedder and the book's vectors for it)."""
    items = measurable(items)
    ks = sorted(set(ks))
    depth = ks[-1]
    spans = {
        int(r[0]): (cleaned.line_at(int(r[1])), cleaned.line_at(int(r[2]) - 1))
        for r in ctx.conn.execute(
            "SELECT id, start_char, end_char FROM chunks WHERE book_id = ?", (ctx.book.id,)
        )
    }

    def holds(chunk_id: int, ranges: list[tuple[int, int]]) -> bool:
        first, last = spans[chunk_id]
        return any(first <= b and a <= last for a, b in ranges)

    methods = ["bm25"]
    vectors: list[list[float] | None] = [None] * len(items)
    if ctx.embedder is not None and has_vectors(ctx.conn, ctx.book.id, ctx.embedder.model_id):
        methods += ["dense", "hybrid"]
        vectors = list(ctx.embedder.embed([i.input for i in items], query=True))

    rows = []
    for method in methods:
        ranked = [_ranked(ctx, method, i, v, depth) for i, v in zip(items, vectors, strict=True)]
        for k in ks:
            with_gold = [(i, r) for i, r in zip(items, ranked, strict=True) if i.gold_lines]
            facts = [
                (ranges, r) for i, r in zip(items, ranked, strict=True) for ranges in i.fact_lines
            ]
            rows.append(
                RecallRow(
                    method,
                    k,
                    sum(any(holds(c, i.gold_lines) for c in r[:k]) for i, r in with_gold),
                    len(with_gold),
                    sum(any(holds(c, ranges) for c in r[:k]) for ranges, r in facts),
                    len(facts),
                )
            )
    return rows


def render_recall(rows: Sequence[RecallRow], *, top_k: int, embedding: str | None) -> str:
    """A table: one line per method, one column per k; the agent's own top-k is marked."""
    ks = sorted({r.k for r in rows})
    first = rows[0]
    lines = [
        f"Retrieval recall: {first.passage_questions} questions with a gold passage, "
        f"{first.facts} expected facts | embeddings {embedding or 'none (keyword search only)'}",
        "Each cell: questions whose gold passage was found / facts whose evidence was found.",
        "",
        "method  "
        + "".join(f"{('@' + str(k) + (' (agent)' if k == top_k else '')):>18}" for k in ks),
    ]
    for method in METHODS:
        cells = {r.k: r for r in rows if r.method == method}
        if not cells:
            continue
        line = f"{method:8}"
        for k in ks:
            r = cells[k]
            line += f"{f'{r.passages_found}/{r.passage_questions}  {r.facts_found}/{r.facts}':>18}"
        lines.append(line)
    if not any(r.method != "bm25" for r in rows):
        lines += ["", "Meaning and hybrid search need the embedding key and `make embed` first."]
    return "\n".join(lines)
