"""The model layer: the interface the rest of the app uses to talk to an LLM."""

from dataclasses import dataclass
from typing import Any, Protocol

Message = dict[str, str]


@dataclass(frozen=True)
class LLMResult:
    text: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_s: float
    cached: bool = False
    reasoning: str | None = None


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class LLMClient(Protocol):
    def chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResult: ...
