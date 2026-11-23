# Phase 1 — Bounded tutor context and branch persistence

Phase 1 constrains what a tutor provider receives while preserving the complete conversation for the learner. The unit of working memory is one conversation branch within one lesson. The same branch can continue after switching between OpenAI and Codex. The [Phase 1 verification report](../result/phase-1.md) records the results and rollout commands.

## Reader and API

The React reader opens the tutor in a side panel with saved questions and a new-question action. The chat API supports generated `question-<id>` branches, saved highlight IDs, and the legacy `main` branch. `GET /api/chat/{rid}/{tid}` lists saved branches using the first user message as a label. `GET` and `POST /api/chat/{rid}/{tid}/{branch}` return the complete message array for the selected branch. Selecting a passage saves the quote, lesson version, block, offsets, and any available simulation snapshot before opening its branch. [Reader](../src/main.tsx) · [Reader layout](../src/style.css) · [Chat and note routes](../backend/main.py)

The reader sends `text`, `search`, and `request_id`. It holds the UUID and draft in the mounted chat so retrying the same text and search setting on the same branch reuses the UUID. A successful response replaces the displayed history and clears the draft. Older API clients can omit `request_id` and receive a server-generated ID for that send. [Chat client](../src/main.tsx) · [Request schema and send route](../backend/main.py)

## Send lifecycle and storage

1. FastAPI resolves the lesson and branch. A short SQLite transaction checks for a committed request, then reserves the branch at the current transcript length with a unique lease token and a five-minute expiry. The request fingerprint binds the ID to the question text and search setting. An identical committed retry returns the current transcript. An in-flight duplicate or competing send receives HTTP 409 with `Retry-After`. [Send reservation](../backend/chat_state.py)
2. The provider runs outside the transaction so other branches can proceed. The adapter renews the lease before each tutor or summary call. The backend releases the lease on failure and leaves the existing transcript intact. [Route orchestration](../backend/main.py) · [OpenAI and Codex tutor loops](../backend/ai.py) · [Codex call boundary](../backend/providers.py)
3. Commit checks the unexpired lease token and recorded transcript length. One transaction appends the user and assistant messages, records the committed request, saves any successful summary advance, and removes the lease. This prevents an expired worker from appending after another send takes over. Older arrays retain their positional sequence and remain readable. [Atomic commit](../backend/chat_state.py)

SQLite schema version 1 adds three tables under the server-assigned `local` owner. The existing `records` table keeps the transcript as a JSON array under `thread:{rid}:{tid}:{branch}`. [Database initialization](../backend/main.py) · [Table definitions](../backend/chat_state.py)

| Table | Scope and purpose |
| --- | --- |
| `tutor_leases` | One active send per owner and branch, with lease token, request ID, reserved revision, and expiry. |
| `tutor_requests` | Committed request IDs, fingerprints, and transcript revisions per owner and branch. |
| `tutor_summaries` | Summary content and covered-through message position per owner, roadmap, topic, lesson version, branch, and summary format. |

## Context assembly and provider calls

- **Evidence.** Required context includes the topic and goal, lesson version, study language, and any validated highlight anchor. A captured simulation snapshot carries the highlight provenance and takes precedence over later playback. For unanchored questions, relevant current playback can be included. The builder ranks lesson sections and submitted quiz feedback by relevance and includes up to three qualifying prior calculator or motion observations with source positions. Quiz context uses submitted feedback, keeping unsubmitted answer fields out of the request. [Evidence collection](../backend/tutor_context.py)
- **Packing.** Each adapter measures its own request envelope. The packer fits mandatory context and the current question first, followed by verified results, an eligible older summary, a suffix of complete turns, and optional details. OpenAI checks serialized request data with instructions and tool schemas. Codex checks UTF-8 stdin plus the response schema. Tool continuations are repacked and checked on each model call. Oversized tool payloads are bounded, and mandatory input that cannot fit returns a localized HTTP 422. [Context packer](../backend/tutor_context.py) · [Adapter loops](../backend/ai.py) · [Codex serialization](../backend/providers.py)
- **Compaction.** When the complete history cannot fit, the builder can summarize a prefix of complete turns using the previous summary plus newly covered turns. It validates the structured summary and stages the covered-through position for the same commit as the reply. A failed summary call leaves the last good summary and fitting verified observations available. Summary calls use the same size and timing checks as tutor calls. [Compaction](../backend/tutor_context.py) · [Summary instructions](../prompts/tutor/summary.md) · [Working-context instructions](../prompts/tutor/working-context.md)

`STUDY_BOUNDED_CONTEXT=1` enables bounded requests. The default prompt path sends full branch history and shares the same retry-safe writes. The fallback window is 16,384, with 4,096 reserved for output and 2,048 for overhead. Override the fallback with `STUDY_TUTOR_CONTEXT_WINDOW` or set a provider-and-model map with `STUDY_TUTOR_MODEL_WINDOWS`. The guard uses a UTF-8 byte estimate and logs counts, timing, status, and available provider token usage without learner text. Live token calibration remains open, and the Codex adapter's output reservation is a budgeting allowance. [Budget and logging](../backend/tutor_context.py) · [Rollout instructions](../result/phase-1.md)

## Reader and lesson changes shipped alongside tutor memory

The reader renders inline and display LaTeX through KaTeX in lessons, quizzes, highlights, and tutor replies. It preserves the original formula source in `data-tex` so selection can reconstruct saved offsets from the source text. Citation placement moves a source marker to the end of a formula if its offset falls inside one. The lesson prompt asks for illustrated worked examples and LaTeX formulas, the illustration contract describes slider-driven changes, and numeric grading normalizes multiplication dots in compound units. [Math renderer](../src/math.tsx) · [Reader integration](../src/main.tsx) · [Lesson prompt](../prompts/lessons/generate.md) · [Illustration contract](../prompts/illustrations/contract.md) · [Grading](../backend/physics.py)

## Verification entry points

The `--bounded` evaluation exercises both providers and languages with a 4,856-byte limit, 20 intervening turns, and a provider switch. It checks that the selected branch retains the original **19.62 m** evidence, excludes sibling context and hidden quiz answers, and still returns the full saved transcript. Backend tests exercise reservation conflicts, expired workers, summary fallback, and oversized input. The browser smoke test checks retry IDs, draft preservation, and transcript reload. [Bounded replay](../tests/evals/fixtures.py) · [Backend tests](../tests/test_study.py) · [Browser smoke test](../tests/browser.mjs) · [Recorded results](../result/phase-1.md)
