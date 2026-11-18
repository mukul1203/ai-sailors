"""Finding the passages for a question, in the way the mode asks for."""

from storyquest.agent.context import AgentContext, AgentError
from storyquest.agent.modes import Mode
from storyquest.domain.position import Position
from storyquest.ingestion.entities import first_occurrence
from storyquest.models.embedder import EmbeddingError
from storyquest.models.reranker import RerankerError
from storyquest.stores.search import SearchHit, hybrid_search, search_chunks
from storyquest.stores.vector import has_vectors

MAX_CARDS = 2


def entity_cards(ctx: AgentContext, text: str, position: Position) -> list[SearchHit]:
    """Cards for the characters, places and terms the child's message names. A card is used
    only if the child has reached both where the name first appears and the passage the card
    was written from, so a card cannot spoil anything."""
    boundary = ctx.where(position).boundary
    seen = (position.chapter_idx, position.beat_idx)
    cards = [
        e
        for e in ctx.entities
        if e.first_char < boundary
        and (e.card_chapter, e.card_beat) <= seen
        and first_occurrence(text, [e.name, *e.aliases], 0) is not None
    ]
    return [
        SearchHit(
            chunk_id=-1,
            chapter_idx=e.card_chapter,
            beat_idx=e.card_beat,
            idx=0,
            text=f"{e.name}: {e.card}",
            start_char=-1,
            end_char=-1,
            score=0.0,
            source="entity",
        )
        for e in cards[:MAX_CARDS]
    ]


def retrieve(
    ctx: AgentContext, mode: Mode, text: str, position: Position
) -> tuple[list[SearchHit], list[str]]:
    """The passages (book text first, then entity cards if the mode uses them) and any flags."""
    hits, flags = _search(ctx, mode, text, position)
    if mode.entities and hits:  # a card alone never answers: the book text must back it up
        hits = [*hits, *entity_cards(ctx, text, position)]
    return hits, flags


def _search(
    ctx: AgentContext, mode: Mode, text: str, position: Position
) -> tuple[list[SearchHit], list[str]]:
    """The passages and any flags. Hybrid search falls back to keywords if embedding fails."""
    s = ctx.settings
    candidate_limit = s.retrieval_candidates if mode.rerank else s.retrieval_top_k

    def rerank(hits: list[SearchHit], flags: list[str]) -> tuple[list[SearchHit], list[str]]:
        if not mode.rerank:
            return hits[:s.retrieval_top_k], flags
        if ctx.reranker is None:
            raise AgentError(f"Mode {mode.name} needs a configured reranker")
        try:
            reranked = ctx.reranker.rerank(text, hits)
        except RerankerError as e:
            flags.append(f"reranker_error:{e}")
            return hits[:s.retrieval_top_k], flags
        return reranked[:s.retrieval_top_k], flags

    if mode.hybrid:
        if ctx.embedder is None:
            raise AgentError(f"Mode {mode.name} needs an embedder; run with EMBEDDING_API_KEY set")
        try:
            vector = ctx.embedder.embed([text], query=True)[0]
        except EmbeddingError as e:
            hits = search_chunks(ctx.conn, ctx.book.id, text, position, limit=candidate_limit)
            return rerank(hits, [f"embedding_error:{e}"])
        if not has_vectors(ctx.conn, ctx.book.id, ctx.embedder.model_id):
            hits = search_chunks(ctx.conn, ctx.book.id, text, position, limit=candidate_limit)
            return rerank(hits, ["no_vectors:run `make embed` for this book"])
        hits = hybrid_search(
            ctx.conn,
            ctx.book.id,
            text,
            vector,
            ctx.embedder.model_id,
            position,
            limit=candidate_limit,
            candidates=s.retrieval_candidates,
            rrf_k=s.rrf_k,
        )
        return rerank(hits, [])
    hits = search_chunks(
        ctx.conn,
        ctx.book.id,
        text,
        position,
        limit=candidate_limit,
    )
    return rerank(hits, [])
