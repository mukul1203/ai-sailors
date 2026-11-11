"""Throttling: one request at a time and a requests-per-minute cap, per process."""

import threading
import time
from collections.abc import Callable
from typing import Any

from storyquest.models.llm import LLMClient, LLMResult, Message


class ThrottledClient:
    def __init__(
        self,
        inner: LLMClient,
        *,
        max_concurrency: int = 1,
        requests_per_minute: int = 50,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._lock = threading.Lock()
        self._gap = 60.0 / requests_per_minute
        self._next_start = 0.0
        self._clock = clock
        self._sleep = sleep

    def chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResult:
        with self._slots:
            self._wait_for_turn()
            return self._inner.chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                json_schema=json_schema,
                extra_body=extra_body,
            )

    def _wait_for_turn(self) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start)
            self._next_start = start + self._gap
        if start > now:
            self._sleep(start - now)
