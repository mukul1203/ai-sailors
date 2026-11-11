import threading
import time
from typing import Any

from storyquest.models.fake import FakeClient
from storyquest.models.llm import LLMResult, Message
from storyquest.models.throttle import ThrottledClient

MSG: list[Message] = [{"role": "user", "content": "x"}]


class Probe(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResult:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        try:
            return super().chat(messages, **kwargs)
        finally:
            with self._lock:
                self.active -= 1


def test_only_one_request_runs_at_a_time() -> None:
    probe = Probe()
    client = ThrottledClient(probe, max_concurrency=1, requests_per_minute=6000)
    threads = [threading.Thread(target=lambda: client.chat(MSG, max_tokens=5)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(probe.calls) == 6
    assert probe.max_active == 1


def test_requests_per_minute_spaces_out_calls() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = ThrottledClient(
        FakeClient(), requests_per_minute=60, clock=lambda: now[0], sleep=sleep
    )
    for _ in range(3):
        client.chat(MSG, max_tokens=5)
    assert sleeps == [1.0, 1.0]
