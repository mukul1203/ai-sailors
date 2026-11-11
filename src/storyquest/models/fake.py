"""A canned LLM for tests and offline work."""

from collections.abc import Callable
from typing import Any

from storyquest.models.llm import LLMResult, Message


class FakeClient:
    def __init__(self, reply: str | Callable[[list[Message]], str] = "ok") -> None:
        self._reply = reply
        self.calls: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResult:
        self.calls.append(messages)
        text = self._reply(messages) if callable(self._reply) else self._reply
        prompt_chars = sum(len(m["content"]) for m in messages)
        return LLMResult(
            text=text,
            finish_reason="stop",
            prompt_tokens=prompt_chars // 4,
            completion_tokens=len(text) // 4,
            model="fake",
            latency_s=0.0,
        )
