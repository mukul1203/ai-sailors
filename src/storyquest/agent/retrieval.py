"""Finding the passages for a question, in the way the mode asks for."""

from storyquest.agent.context import AgentContext, AgentError
from storyquest.agent.modes import Mode
from storyquest.domain.position import Position
from storyquest.models.embedder import EmbeddingError
from storyquest.stores.search import SearchHit, hybrid_search, search_chunks


def retrieve(
    ctx: AgentContext, mode: Mode, text: str, position: Position
) -> tuple[list[SearchHit], list[str]]:
    """The passages and any flags. Hybrid search falls back to keywords if embedding fails."""
    s = ctx.settings
    if mode.hybrid:
        if ctx.embedder is None:
            raise AgentError(f"Mode {mode.name} needs an embedder; run with EMBEDDING_API_KEY set")
        try:
            vector = ctx.embedder.embed([text], query=True)[0]
        except EmbeddingError as e:
            hits = search_chunks(ctx.conn, ctx.book.id, text, position, limit=s.retrieval_top_k)
            return hits, [f"embedding_error:{e}"]
        hits = hybrid_search(
            ctx.conn,
            ctx.book.id,
            text,
            vector,
            ctx.embedder.model_id,
            position,
            limit=s.retrieval_top_k,
            candidates=s.retrieval_candidates,
            rrf_k=s.rrf_k,
        )
        return hits, []
    return search_chunks(ctx.conn, ctx.book.id, text, position, limit=s.retrieval_top_k), []
