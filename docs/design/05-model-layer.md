# 05 — Model Layer

Scope: the boundary between the application and any model provider. Nothing outside this layer knows which model is in use.

## Interfaces

| Interface | Methods | Current implementation |
|---|---|---|
| `LLMClient` | `chat(messages, schema=None, temperature, max_tokens, stream=False)` → text or validated JSON, with token usage | Hosted `Qwen/Qwen3-8B` (vLLM, OpenAI-compatible chat endpoint); also a `fake` provider for tests and offline work |
| `Embedder` | `embed(texts)` → vectors, `model_id`, `dim` | None (the team endpoint provides no embeddings; BM25 only) |
| `Reranker` | `rerank(query, passages)` → ordered ids with scores | LLM-based listwise rerank using `LLMClient` |

Implementations are chosen in config. Adding a provider means adding one class.

## Endpoint limits (from the Track B API guide)

| Limit | Value | What the layer does |
|---|---|---|
| Active requests per key | 1, across everyone using the group key | A single global queue with concurrency 1 inside each process |
| Requests per minute | 60 | Rate limiter below the cap |
| Input plus output tokens | 8,192 per call | Budget prompts before sending; fail early if too large |
| Output tokens | 512 default, 1,024 max | Always set `max_tokens` explicitly |
| Errors | 429 and 503 are transient; 400 means a bad request | Retry 429 and 503 with delays of 2, 4 and 8 seconds, then give up and report; never retry 400 |

Embeddings are not provided on these endpoints. The API supports chat, streaming and tool-call responses; the application does the tool execution, retrieval and conversation history.

Priorities when requests contend: live child turns first, then eval runs, then ingestion. Because the key is shared with all developers, two processes can still collide; a 429 is then retried, and the disk cache keeps repeated calls off the endpoint; the `fake` provider is available for tests.

## Cross-cutting behaviour

- **Structured output:** Callers pass a JSON schema. The layer validates, retries with the error, and returns a typed object or a clear failure. If the endpoint supports guided decoding, use it; otherwise validate and retry. Check which the endpoint supports.
- **Token accounting:** Every call records prompt and completion tokens, latency and model id into the trace. This matters because the team endpoint has a per-team quota.
- **Disk cache:** Ingestion and eval calls are cached by request hash, so reruns are free and reproducible. Cache is off for live child traffic.
- **Retries and timeouts:** Bounded retries with backoff; a hard timeout so a slow endpoint cannot hang a child's turn.
- **Determinism:** Eval and ingestion run at temperature 0 by default.
- **Model id everywhere:** Traces, ingestion output (`pipeline_version`) and eval reports record the model id, so results stay comparable across swaps.

## Qwen3-8B notes

- It has a thinking mode that emits reasoning tokens. A sample response showed `reasoning: null` and plain content, but test a harder prompt before assuming thinking is off. If it is on, disable it for child-facing replies (latency, and tokens against the 8,192 limit) and strip it from outputs either way.
- The context limit is 8,192 tokens combined, not the model's native length. Size every prompt against it.

## Config sketch

```yaml
llm:
  provider: openai_compatible      # or: fake
  base_url_env: LLM_BASE_URL        # secret (IP and port), read from .env
  model: Qwen/Qwen3-8B
  api_key_env: LLM_API_KEY          # secret, read from .env; everything else here comes from config.env
  ca_cert_path: /certs/ca.crt       # git-ignored file; keep TLS verification on
  max_concurrency: 1
embedder:
  provider: none        # later: local or hosted
reranker:
  provider: llm_listwise
```

## Open questions

- Does the endpoint support JSON-schema guided decoding (vLLM `response_format` or guided JSON)? Test it.
- Does the deployed app get its own key, or share the group key with developers?
- Where will the separate embeddings service come from, when we add dense retrieval?
