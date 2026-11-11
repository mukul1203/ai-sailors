from dataclasses import dataclass, field

from storyquest.models.llm import Message
from storyquest.stores.search import SearchHit


@dataclass(frozen=True)
class StepTrace:
    """One model call made during a turn, kept so a developer can see exactly what happened."""

    name: str
    messages: list[Message]
    output: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    cached: bool


@dataclass(frozen=True)
class TurnResult:
    reply: str
    route: str  # what the router decided, or the reason the turn ended early
    mode: str
    steps: list[StepTrace] = field(default_factory=list)
    passages: list[SearchHit] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
