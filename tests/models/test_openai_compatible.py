import json
from collections.abc import Callable

import httpx
import pytest

from storyquest.models.llm import LLMError
from storyquest.models.openai_compatible import OpenAICompatibleClient

Handler = Callable[[httpx.Request], httpx.Response]


def body(text: str = "hi", **message: str) -> dict[str, object]:
    return {
        "model": "m",
        "choices": [{"message": {"content": text, **message}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


def make(handler: Handler) -> tuple[OpenAICompatibleClient, list[float]]:
    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(
        "https://x/v1/", "KEY", "m", None, http=http, sleep=sleeps.append
    )
    return client, sleeps


MSG = [{"role": "user", "content": "hello"}]


def test_parses_result_and_sends_expected_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body("hello back"))

    client, _ = make(handler)
    result = client.chat(MSG, max_tokens=50)
    assert result.text == "hello back"
    assert (result.prompt_tokens, result.completion_tokens) == (5, 2)
    assert seen[0].url == "https://x/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer KEY"
    sent = json.loads(seen[0].content)
    assert sent["model"] == "m" and sent["max_tokens"] == 50 and sent["temperature"] == 0.0


def test_retries_429_with_increasing_delays_then_succeeds() -> None:
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, json=body() if status == 200 else {})

    client, sleeps = make(handler)
    assert client.chat(MSG, max_tokens=5).text == "hi"
    assert sleeps == [2.0, 4.0]


def test_gives_up_after_retry_limit() -> None:
    client, sleeps = make(lambda request: httpx.Response(429, json={}))
    with pytest.raises(LLMError) as exc:
        client.chat(MSG, max_tokens=5)
    assert exc.value.status == 429
    assert sleeps == [2.0, 4.0, 8.0]


def test_bad_request_is_not_retried_and_hides_the_key() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": "bad"})

    client, sleeps = make(handler)
    with pytest.raises(LLMError) as exc:
        client.chat(MSG, max_tokens=5)
    assert len(calls) == 1 and sleeps == []
    assert "KEY" not in str(exc.value)


def test_think_block_is_split_from_the_answer() -> None:
    client, _ = make(lambda r: httpx.Response(200, json=body("<think>plan</think>\nThe answer")))
    result = client.chat(MSG, max_tokens=5)
    assert result.text == "The answer"
    assert result.reasoning == "plan"


def test_json_schema_is_sent_as_response_format() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=body("{}"))

    client, _ = make(handler)
    client.chat(MSG, max_tokens=5, json_schema={"type": "object"})
    assert seen[0]["response_format"]["json_schema"]["schema"] == {"type": "object"}  # type: ignore[index]


@pytest.mark.parametrize("bad", [0, 1025])
def test_max_tokens_outside_endpoint_limit_is_rejected(bad: int) -> None:
    client, _ = make(lambda r: httpx.Response(200, json=body()))
    with pytest.raises(ValueError):
        client.chat(MSG, max_tokens=bad)
