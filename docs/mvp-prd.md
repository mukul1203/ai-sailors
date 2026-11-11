# StoryQuest Copilot — MVP Product Requirements

Track B (API-side, hosted ≤8B model). Status: draft for team review.

## 1. Problem

Generic chatbots told to "tell a story from The Jungle Book" hallucinate plot details, blend in film adaptations, drift into adult vocabulary, spoil later chapters and keep no game state. Parents have no way to trust or bound the experience.

## 2. Product vision

A parent-approved, book-grounded storytelling game for children aged 6–9. Each session is a short interactive "quest" built from a public-domain children's book. Facts come from the book text, not from model memory.

## 3. Users

| User | Need |
|---|---|
| Child (6–9) | Short, fun, understandable story beats; choices that matter; rewards; room to ask curious questions |
| Parent | Control over which books and how long; confidence that content is safe and faithful; visible progress |

## 4. MVP scope

### In scope

1. **Parent setup:** pick from approved books, set session cap (default 1 mission, ~10 minutes), no child account or personal data stored.
2. **Quest session:** a sequence of 4–5 story beats from one chapter, each 2–4 sentences at the target reading level, followed by a choice (clickable cards plus optional free text).
3. **Show → Ask → Reward:** each beat narrates the scene and surfaces the clue/vocabulary before asking the child to use it; never quiz on unseen facts.
4. **Free-text "ask the sidekick":** the child can ask off-script questions; the system answers from retrieved book text, stays spoiler-safe for the current position, then returns to the quest.
5. **Rewards:** vocabulary badges and a simple end-of-session summary shown to the parent. (Proposed for after the first end-to-end version; see docs/design/00-architecture-overview.md.)
6. **Session wrap-up:** a gentle ending when the cap is reached or the quest completes. (Same: session cap is proposed for after the first end-to-end version.)
7. **Safety:** refusal and redirect for off-topic or unsafe input; prompt-injection resistance; no PII collection.

### Out of scope for MVP

- Multiple simultaneous books per session, user accounts, long-term profiles, voice input/output, illustrations generation, multiplayer, native mobile apps, payments.

## 5. Key design constraints (from product decisions)

- **Quest Spine:** each chapter is pre-processed offline into a structured beat sequence (JSON) so the story always has a beginning, middle and end. Reviewed by a human before use.
- **Live RAG is justified only by free-text questions.** If a flow can be fully served from the spine, it must not call retrieval.
- **Spoiler boundary:** retrieval is filtered to text at or before the child's current position in the book.
- **Small-model compensation:** JSON schema validation, retries, constrained output, and a non-LLM output check on every child-facing message (a critic step is planned for later).
- **Public-domain sources only** (e.g. Project Gutenberg, Internet Archive); no film-derived content.

## 6. User flow

1. Parent chooses a book and session cap.
2. Child meets the sidekick and enters the book portal.
3. For each beat: narrate → present choice → child picks or types → system responds and advances state.
4. If the child types a question: pause the spine, retrieve canon, answer, nudge back.
5. Badge awarded on vocabulary use; session wrap-up; parent summary.

## 7. Capstone alignment (Track B)

| Capstone requirement | How the product satisfies it |
|---|---|
| Task spec, refusals, gold-answer eval set (60–100 queries) | Section 8 and a frozen eval set covering canon Q&A, spoiler traps, off-topic, unsafe and injection inputs |
| Prompt-strategy comparison (≥3) | Beat generation and Q&A tested with structured few-shot, CoT/self-consistency and decomposition |
| RAG over 500–2,000 docs with hybrid retrieval, reranker, citations, recall@k | Corpus is many chapters/books chunked, not one chapter; spine covers only the quest path |
| Agentic layer: ≥3 tools, planner→executor→critic, persistent state, error handling, ≤10 steps | Tools: retrieve_canon, get_next_beat, award_badge (and check_reading_level); state = quest position, badges, time used |
| Evaluation, failure taxonomy, tracing | Metrics in section 9; trace each turn |
| Ship: UI, container, rate limit, cache, responsible AI, human-in-the-loop | React front-end; parent is the human-in-the-loop boundary |

## 8. Functional requirements

| ID | Requirement |
|---|---|
| FR1 | Parent can select an approved book and session cap before a session starts |
| FR2 | System delivers beats from the Quest Spine in order, preserving state across turns |
| FR3 | Every child-facing message passes a non-LLM output check (spoiler list and banned terms) before display; an LLM critic for faithfulness, reading level and safety is added later |
| FR4 | Free-text questions are answered using retrieved passages with citations; answers never include content beyond the child's position |
| FR5 | If retrieval confidence is low, the sidekick says it does not know in-character rather than guessing |
| FR6 | Malformed model output is retried and then falls back to a canned, safe response |
| FR7 | Session ends at the cap; parent summary lists the book, beats completed and badges |
| FR8 | Agent loop is capped at 10 steps per child turn and a token budget per session |
| FR9 | No personal data from the child is stored beyond the active session |

## 9. Success metrics

- Answer faithfulness on the eval set (grounded in retrieved text).
- Retrieval recall@k, measured separately from end-to-end quality.
- Spoiler-leak rate (target: 0 on the eval set).
- Unsafe or off-topic input handled correctly (refusal/redirect rate).
- Schema-valid output rate after retries.
- Reading-level compliance of child-facing text.
- Task completion rate, average tool calls per turn, p50/p95 latency per turn.
- Failure taxonomy: retrieval miss, reasoning error, tool-call error, hallucination.

## 10. Risks

| Risk | Mitigation |
|---|---|
| 8B model drifts in vocabulary or invents facts | Critic step, schema validation, grounding in retrieved text, low-confidence fallback |
| Latency from planner→executor→critic hurts a child's attention | Pre-generate or cache spine beats; keep critic lightweight; budget steps |
| Corpus too small for the capstone's RAG criteria | Ingest many public-domain children's books; the spine covers only the guided path |
| Child data / privacy exposure | No accounts, no PII storage, parent-gated setup |
| Prompt injection via child text or book content | Input sanitisation, content-vs-instruction separation, injection tests in eval |
| Scope creep into gamification | Rewards limited to badges and summary for MVP |

## 11. Open questions

- Which books and chapters form the first corpus and the first spine?
- Reading-level measure and target (for example a Flesch-Kincaid band)?
- Reading-level measure and target?
