# Phase 2 implementation and verification

ConceptLens now stores optional learner memory locally. In Settings, a learner can enable capture, save goals and preferences, inspect the quiz attempts behind a recurring unit mistake, and correct or forget a memory. The controls work in English and Vietnamese. Two distinct questions in the same roadmap must support the same unit diagnosis before the app marks it recurring.

## Delivered

- SQLite schema version 2 adds learner memory and a durable evidence queue. Quiz grading saves a stable attempt ID, and retrying an identical attempt returns saved progress. A separate local worker applies qualifying evidence and retries failed work.
- Memory sources open the original question and submitted answer, even after a newer attempt. Learner edits take precedence over automated evidence updates. Forgetting deletes the memory and its evidence links, suppresses automatic recreation, and leaves the original study history available. A learner can explicitly start tracking a forgotten pattern from a new eligible attempt.
- Capture is off by default. Pausing keeps saved memories available for review, edit, and forget. Memory processing makes no provider calls. [Architecture](../documents/phase-2-architecture.md)

## Independent verification

| Check | Result | Evidence |
| --- | --- | --- |
| V1 · Migration and restore | Pass | Upgraded populated schema 0 and 1 copies and reopened each twice. A restored copy retained progress, chat, roadmap bytes, and applicable summaries. An injected migration failure rolled back both schema and version. The legacy quiz request without an ID still worked. |
| V2 · Capture boundaries | Pass | Default-off and paused attempts produced no memory. Opening lessons, confirming generated goals, and sending chat added no records. Explicit goals and preferences survived a fresh process and were visible in both languages. The captured tutor call contained no learner-memory payload. |
| V3 · Evidence and grading | Pass | Replaying the UUID appended once, and reusing it for another answer or question returned `409`. Resubmitting one question with a new UUID stayed tentative. Two distinct questions with the same diagnosis and dimension became recurring, and subsequent correct answers weakened and resolved the memory. A separate roadmap stayed tentative. `1962 cm` still graded as `19.62 m`. |
| V4 · Worker and concurrency | Pass | Concurrent requests with the same ID saved one attempt. With the worker failing, the quiz succeeded and pending work retained a retry count. A fresh process applied it once. A subsequent queued update preserved the learner correction and edited preference. Pausing cancelled queued capture. |
| V5 · Evidence and forget | Pass | The exact prior answer remained inspectable after a newer submission. A changed lesson version, unknown source, stale revision, and foreign owner were rejected. Forgetting survived restart, source replay, and a stale revision lookup. Explicit resumption produced one fresh tentative observation and the original attempt remained in quiz history. |
| V6 · Bilingual browser workflow | Pass | Playwright exercised keyboard opt-in and pause, goal and preference creation, saved drafts after an injected failure, quiz request retry, two evidence disclosures, memory edit, reload, language switch, and forget while paused. It verified the original attempt was still saved exactly once. |
| V7 · Regressions | Pass | The Python suite passed all 17 tests. TypeScript and Vite built successfully, and the browser smoke test passed. Credential-free baseline replay passed 32 cases. Bounded replay passed four cases and 100 turns across both adapters and languages, preserving the original 19.62 m result, branch isolation, and full transcript. |

In a separate offline exit check, a fresh process using Vietnamese headers opened both evidence IDs from an English lesson and returned the two original submitted answers. All 100 bounded replay turns returned HTTP `200` under the fixture's 4,856-byte input guard.

Verification used disposable study-data directories and scripted providers. The build reported the existing Vite bundle-size advisory. Live providers, indexing, retrieval, and historical import were outside this phase. [Verification commands and checklist](../plans/phase-2.md)
