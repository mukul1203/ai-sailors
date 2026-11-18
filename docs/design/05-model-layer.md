# 05 — Model Layer

Scope: the boundary between the application and any model provider. Nothing outside this layer knows which model is in use.

## Interfaces

| Interface | Methods | Current implementation |
|---|---|---|
| `LLMClient` | `chat(messages, schema=None, temperature, max_tokens, stream=False)` → text or validated JSON, with token usage | Hosted `Qwen/Qwen3-8B` (vLLM, OpenAI-compatible chat endpoint); also a `fake` provider for tests and offline work |
| `Embedder` | `embed(texts, query=)` → unit vectors, `model_id`, `dim` | `openai_compatible` (default: the course's separate embedding endpoint, `bge-small-en-v1.5`, 384 dimensions, at most 16 texts per request, its own CA certificate), `gemini` (the Gemini embedding API, `gemini-embedding-001`, 768 dimensions), `fake` (tests); wrapped by a disk cache, and optionally by a query prefix. The chat endpoint's own `/embeddings` returns 404 "not available in this pilot" |
| `Reranker` | `rerank(query, passages)` → ordered passages with scores | Optional local `sentence-transformers` cross encoder; deterministic fake for tests |

Implementations are chosen in config. Enable the local cross encoder with
`RERANKER_PROVIDER=cross_encoder` and install the optional `reranker` dependency group. Models are
loaded lazily on the first reranking request. M4/M4S retrieve the configured candidate pool first,
then rerank those spoiler-filtered passages down to `RETRIEVAL_TOP_K`; if scoring fails, the
original retrieval order is used and the turn is flagged.

## Endpoint limits (from the Track B API guide)

| Limit | Value | What the layer does |
|---|---|---|
| Active requests per key | 1, across everyone using the group key | A single global queue with concurrency 1 inside each process |
| Requests per minute | 60 | Rate limiter below the cap |
| Input plus output tokens | 8,192 per call | Budget prompts before sending; fail early if too large |
| Output tokens | 512 default, 1,024 max | Always set `max_tokens` explicitly |
| Errors | 429 and 503 are transient; 400 means a bad request | Retry 429 and 503 with delays of 2, 4 and 8 seconds, then give up and report; never retry 400 |

Embeddings are not provided on the chat endpoint. The course provides a separate embedding endpoint (from 13 Nov 2026): OpenAI-style `POST /v1/embeddings` serving `bge-small-en-v1.5`, 384-dimension vectors, at most 16 texts per request and 512 model tokens per text, with its own CA certificate (`certs/vm02-ca.crt`). Its URL and key go in `.env` as `EMBEDDING_BASE_URL` and `EMBEDDING_API_KEY`. The model has no query/document task type; BGE recommends an instruction in front of short search questions, set with `EMBEDDING_QUERY_PREFIX` (applied to queries only, outside the cache so prefixed and plain queries are cached apart). Each chunk is embedded with up to `EMBEDDING_CONTEXT_CHARS` (default 1200) of the text around it in its own beat, which raised the gold passage in the top 6 from 18 to 20 of 23 dev questions and the facts' evidence from 35 to 42 of 47 (Gemini: 22 and 45); the vectors are tagged `+ctx1200`. Texts are cut to `EMBEDDING_MAX_CHARS` (1,600): the endpoint refuses more than 512 tokens with HTTP 422, and long Jungle Book passages run about 4.2 characters a token. Before it arrived the team used the Gemini API (`EMBEDDING_PROVIDER=gemini`, key in `.env` as `GEMINI_API_KEY`), which is kept for comparison; Google's free tier may use submitted content to improve its products, so it is for development and evaluation only. A key is never sent to Google when an `EMBEDDING_BASE_URL` is set unless it is named `GEMINI_API_KEY`. The API supports chat, streaming and tool-call responses; the application does the tool execution, retrieval and conversation history.

Priorities when requests contend: live child turns first, then eval runs, then ingestion. Because the key is shared with all developers, two processes can still collide; a 429 is then retried, and the disk cache keeps repeated calls off the endpoint; the `fake` provider is available for tests.

## Cross-cutting behaviour

- **Structured output:** Callers pass a JSON schema, sent as `response_format` (json_schema). The endpoint enforces it, so output is valid JSON matching the schema, enums included (verified). Truncation by `max_tokens` can still cut it short, so check `finish_reason`. Plain parse-and-retry remains the fallback for providers without guided decoding.
- **Token accounting:** Every call records prompt and completion tokens, latency and model id into the trace. This matters because the team endpoint has a per-team quota.
- **Disk cache:** Ingestion and eval calls are cached by request hash, so reruns are free and reproducible. Cache is off for live child traffic.
- **Retries and timeouts:** Bounded retries with backoff; a hard timeout so a slow endpoint cannot hang a child's turn.
- **Determinism:** Eval and ingestion run at temperature 0 by default.
- **Model id everywhere:** Traces, ingestion output (`pipeline_version`) and eval reports record the model id, so results stay comparable across swaps.

## Qwen3-8B notes

- **Thinking mode: effectively off.** Measured on the real endpoint: no `reasoning` field and no `<think>` block, even for a reasoning prompt; `chat_template_kwargs.enable_thinking` makes no difference. The client still splits a `<think>` block out of the text if one ever appears.
- **Context is enforced at 8,192 tokens combined.** An oversized prompt returns HTTP 400 with the counts, which the client raises as an `LLMError` without retrying. Size every prompt against it.

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
  provider: openai_compatible       # or: gemini, fake
  base_url_env: EMBEDDING_BASE_URL  # secret, read from .env
  model: bge-small-en-v1.5
  dim: 384
  batch_size: 16
  ca_cert_path: certs/vm02-ca.crt
  query_prefix: ""                  # e.g. "Represent this sentence for searching relevant passages:"
reranker:
  provider: llm_listwise
```

## Open questions

- Does the deployed app get its own key, or share the group key with developers?
- Is the course embedding endpoint available to the deployed server, and with what rate limits?
