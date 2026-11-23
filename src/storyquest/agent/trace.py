from dataclasses import dataclass, field
from typing import Any

from storyquest.models.llm import Message
from storyquest.stores.search import SearchHit


def hit_to_dict(p: SearchHit, *, full: bool) -> dict[str, Any]:
    """A passage as JSON. The summary form keeps ids and ranks but not the book text."""
    out: dict[str, Any] = {
        "chunk_id": p.chunk_id,
        "chapter": p.chapter_idx,
        "beat": p.beat_idx,
        "idx": p.idx,
        "score": round(p.score, 4),
        "bm25_rank": p.bm25_rank,
        "dense_rank": p.dense_rank,
        "rerank_rank": p.rerank_rank,
        "rerank_score": None if p.rerank_score is None else round(p.rerank_score, 4),
        "source": p.source,
    }
    if full:
        out["text"] = p.text
    return out


@dataclass(frozen=True)
class StepTrace:
    """One model call made during a turn, kept so a developer can see exactly what happened."""

    name: str
    messages: list[Message]
    output: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float  # for a cached step, the latency of the original call, not this one
    cached: bool
    model: str = ""
    finish_reason: str | None = None

    def to_dict(self, *, full: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_s": round(self.latency_s, 3),
            "cached": self.cached,
            "model": self.model,
            "finish_reason": self.finish_reason,
        }
        if full:
            out["messages"] = [dict(m) for m in self.messages]
            out["output"] = self.output
        return out


@dataclass(frozen=True)
class TurnResult:
    reply: str
    route: str  # what the router decided, or the reason the turn ended early
    mode: str
    steps: list[StepTrace] = field(default_factory=list)
    passages: list[SearchHit] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    evidence: str = ""  # the text the model pointed at, in the modes that ask for it
    started_at: float = 0.0  # wall-clock time (epoch seconds) the turn began
    total_latency_s: float = 0.0  # real time the whole turn took
    timings: dict[str, float] = field(default_factory=dict)  # seconds per stage that ran

    @property
    def prompt_tokens(self) -> int:
        return sum(s.prompt_tokens for s in self.steps)

    @property
    def completion_tokens(self) -> int:
        return sum(s.completion_tokens for s in self.steps)

    def to_dict(self, *, full: bool) -> dict[str, Any]:
        """The turn as JSON. `full` also keeps prompts, model output and passage text."""
        return {
            "route": self.route,
            "mode": self.mode,
            "started_at": self.started_at,
            "total_latency_s": self.total_latency_s,
            "timings": self.timings,
            "steps": [s.to_dict(full=full) for s in self.steps],
            "passages": [hit_to_dict(p, full=full) for p in self.passages],
            "flags": self.flags,
            "evidence": self.evidence,
        }
