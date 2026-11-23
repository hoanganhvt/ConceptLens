# Phase 4 — Tutor orchestration

Scope is Phase 4 in [PLAN.md](../PLAN.md). Phases 4A–4C have separate delivery gates. Use the existing calculator and motion functions and keep structured generation on its current path. Add `STUDY_TUTOR_AGENT=1` for rollout and exercise the new loop both with and without bounded context. Keep the chat API, transcript, citations, traces, and reservation protocol compatible.

## Interfaces and constraints

- `POST /api/chat/{rid}/{tid}/{branch}` keeps its question, search flag and optional request ID, and returns the full transcript on success. A rejected turn leaves the existing transcript intact and releases its lease for retry. Use the existing context builder and verify memory revisions on provider calls and commit when retrieval is active.
- OpenAI continues to use Responses function calls and native citations. Codex uses schema-validated JSON decisions and detects search from subprocess events. Both translate their output into the same routing policy. Retain the per-model bounded input allowance and record the remaining time passed to blocking calls.
- Register existing `calculator` and `simulate_motion` functions, native web search when authorized, and the `physics_explanation` specialist. A selected simulation supplies the captured values when the action refers to the snapshot. Keep messages from a different branch, hidden quiz answers, and unrelated learner data out of specialist inputs.
- Reuse the SQLite reservation and transcript tables. The phase needs no migration, subprocess code execution feature or deployment change. Verification uses synthetic data and scripted adapters. The Phase 3 encoder qualification remains a separate release gate.

| Requirement | Acceptance | Verification |
| --- | --- | --- |
| R1 | One loop validates both adapters’ decisions for direct answer, clarification, tools and one-level specialist delegation. Preserve native call IDs and allow provider switching within a branch. | V1, V2 |
| R2 | Validate callable identity, strict input shape and finite output. Use the saved simulation for references to the selected time, preserve successful tool traces with SI unit metadata and send compact typed failures. Allow one correction and bound repeats. | V2, V3 |
| R3 | Snapshot search permission, omit OpenAI search and disable Codex search when off. With search on, require a completed search and usable HTTP(S) citations. Preserve provider citation placement. | V4 |
| R4 | Bound work to six decisions and six individual actions (including search and delegation). For Codex-hosted search, the approved exception allows counting completed events when the CLI returns and rejecting over-budget results before local dispatch or commit. A monotonic deadline covers context assembly, adapter setup, summary, provider calls and commit eligibility. Recheck the serialized budget before each bounded request. Record reason, destination, status and duration without learner text. | V3, V5, V8 |
| R5 | Delegate a worked physics explanation using only the question, relevant lesson excerpt and verified result with the selected provider/model. The specialist returns a validated recommendation and cannot call tools. Handle invalid or unavailable routes with localized errors or a permitted fallback. | V6 |
| R6 | Keep interrupted or timed-out results from committing and preserve the question for retry. Existing generation, persistence and reader behaviors pass their regression checks. | V5, V7 |

## Implementation

- [x] T1. Add the shared loop, typed decisions/observations and callable registry. Wire search, budgets, verification and metrics (R1–R5). The application limits and validation pass under the approved Codex-hosted search exception.
- [x] T2. Implement the two provider adapters and deadline propagation. Connect the new path to chat reservation/context and keep rollback available (R1–R6).
- [x] T3. Add deterministic coverage for both adapters, the shared policy and reservation regressions. Record architecture and verification evidence (R1–R6).

## Independent verification

Use fresh synthetic study data and scripted provider responses without credentials. Save exact commands, scripts, and measured output under `result/phase-4/`.

| ID | Requirements | Steps, expected result and evidence | Status |
| --- | --- | --- | --- |
| V1 | R1 | Return a direct answer and a clarification through each adapter. Verify only one model call and no dispatch, then compare public reply shape and metrics. | Pass |
| V2 | R1, R2 | Replay calculator and motion, including a native batch and provider switch. Assert exact call IDs, units, successful traces, selected snapshot provenance and reuse of the verified result. | Pass |
| V3 | R2, R4 | Send unknown, malformed, corrected and repeated actions plus an over-cap batch. Inject invalid output and record dispatch counts, statuses and typed observations. | Pass |
| V4 | R3 | Record both provider requests with search off and on. Inject failed search, absent/unusable citations and a successful sourced response. Verify links and placement. | Pass |
| V5 | R4, R6 | Inject deadline expiry, a tiny input budget and an interrupted reservation. Verify remaining transport time, no late commit, retryability, and termination metrics. | Pass |
| V6 | R5 | Invoke the physics specialist through each provider, inspect its scoped payload and test unavailable and exhausted routes. Verify a structured recommendation and single-level dispatch. | Pass |
| V7 | R6 | Run the existing Python and browser suites and build the frontend. Record exit codes and test counts, including the reader retry regression. | Pass |
| V8 | R4 | Verify over-cap Codex search events prevent local dispatch and commit. The approved exception allows enforcement after the CLI returns. | Pass under approved exception |

[Recorded results and evidence](../result/phase-4/document.md)
