"""Client for an OpenAI-compatible chat endpoint (the hosted Qwen3-8B on vLLM)."""

import re
import ssl
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from storyquest.models.llm import LLMError, LLMResult, Message

MAX_OUTPUT_TOKENS = 1024  # endpoint limit
RETRY_DELAYS = (2.0, 4.0, 8.0)
_RETRYABLE = (429, 503)
_THINK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        ca_cert_path: Path | None,
        *,
        timeout: float = 120.0,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._sleep = sleep
        self._delays = retry_delays
        if http is None:
            ctx = ssl.create_default_context(cafile=str(ca_cert_path) if ca_cert_path else None)
            http = httpx.Client(verify=ctx, timeout=timeout)
        self._http = http

    def chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        json_schema: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResult:
        if not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError(f"max_tokens must be between 1 and {MAX_OUTPUT_TOKENS}")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": True},
            }
        if extra_body:
            payload.update(extra_body)
        start = time.monotonic()
        data = self._post(payload)
        return self._parse(data, time.monotonic() - start)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        for delay in (*self._delays, None):
            try:
                resp = self._http.post(self._url, json=payload, headers=self._headers)
            except httpx.HTTPError as e:
                raise LLMError(f"request failed: {type(e).__name__}: {e}") from e
            if resp.status_code == 200:
                body: dict[str, Any] = resp.json()
                return body
            if resp.status_code in _RETRYABLE and delay is not None:
                self._sleep(delay)
                continue
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
        raise LLMError("unreachable")

    def _parse(self, data: dict[str, Any], latency: float) -> LLMResult:
        choice = data["choices"][0]
        message = choice.get("message", {})
        text = message.get("content") or ""
        reasoning = message.get("reasoning") or message.get("reasoning_content")
        found = _THINK.findall(text)
        if found:
            reasoning = "\n".join(s.strip() for s in found)
            text = _THINK.sub("", text)
        usage = data.get("usage") or {}
        return LLMResult(
            text=text.strip(),
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model=str(data.get("model", self._model)),
            latency_s=latency,
            reasoning=reasoning,
        )
