# Phase 4C - Illustration provider selection and recovery

## Outcome and starting point

A learner can keep Codex for lesson text and tutor replies, choose a specific Antigravity model for illustrations, and read or take the quiz even when illustration generation fails. A retry uses the saved illustration brief, and a failed repair leaves the last working illustration available.

[PLAN.md](../PLAN.md) defines the Phase 4C exit check. The current checkout already has independent illustration settings, split lesson and scene generation, and shared routing for illustration repairs. Codex model options currently come from a cache file. The agy picker uses a manually loaded datalist and accepts free input. The working tree also contains an agy timeout change and per-scene calls, but initial generation still persists the lesson only after every scene succeeds. Review those changes before implementation. Phase 4A/4B and Phase 5 retain their existing delivery gates.

## Requirements and acceptance

| ID | Behavior and acceptance | Verification |
| --- | --- | --- |
| R1 | For the illustration selector, populate Codex and agy options exclusively from their successful CLI responses. Use `agy models` and validate the installed Codex `app-server` `model/list` protocol. Search by display name or exact ID. Refresh on opening Settings, changing the illustration provider, or manual refresh. Empty, failed, timed-out, and malformed responses produce zero selectable IDs and a localized status. A saved ID missing from a refreshed catalog remains visible as a status and cannot be reselected or replaced silently. Keep existing general provider/model settings compatible. | V1, V2 |
| R2 | Persist the explicit illustration provider and model ID independently. Pass the exact ID on generation, scene retry, automatic repair, and manual repair. Existing configurations with no explicit illustration selection inherit the lesson provider and model. A provider or model failure requires an explicit settings change before any switch. Construct the visual request from the scene brief, required lesson excerpt and runtime contract. Repairs receive the affected scene and error. Lesson prose, quiz and tutor calls continue to use the general selection. | V3, V4, V7 |
| R3 | Save the validated lesson text, quiz, and scene briefs once. Keep successful scenes when a later scene fails. Display a recoverable status at the affected section with a retry that calls only illustration generation. Resume after reload or restart. Preserve lesson version, progress, highlights and tutor threads. Concurrent or repeated retries must produce at most one committed scene per planned slot. | V4, V5 |
| R4 | Keep the existing illustration validation, HTML filtering, iframe sandbox and interpreter. Identify scenes by a stable slot within the lesson version so a late scene or repair cannot redirect existing highlights or replace the wrong scene. Failed repairs preserve the previous scene. Keep agy non-interactive with the existing temporary workspace and scoped permission settings. Verify the installed CLI honors those settings for the illustration flow. | V4, V5, V6, V7 |
| R5 | Report provider and stage failures in Vietnamese and English. Bound calls and record elapsed time, outcome and retry count by stage without storing prompt text or credentials in logs. Record live agy generation and repair results on a synthetic lesson before considering the Phase 4C agy gate passed. | V2, V4, V7 |

## Implementation

- [x] T1. Review the existing timeout and batching changes and capture baseline checks. Add a Codex source to the settings catalog API alongside agy and Gemini. Validate CLI responses, distinguish catalog failure states, and wire the searchable illustration picker and refresh behavior. The installed protocol was exercised with disposable CLI state. Live model access is tracked by V7. (R1, R2)
- [x] T2. Reuse the existing lesson/illustration dispatch and snapshot settings for each request. Add staged persistence to the existing SQLite record flow. Keep public lesson data compatible through additive visual status fields. Preserve planned slot identity when a scene is missing or completed out of order, and make retry operate on that slot under the existing per-lesson coordination. Surface a stage-specific failure when the prose itself fails. (R2-R5)
- [x] T3. Render visual status and retry in the reader. Keep repair on the existing route and validate a replacement before committing it. Keep old saved lessons readable and their indices stable. Reuse the same scene contract and dispatch for generation and recovery. (R2-R5)
- [x] T4. Add focused tests, update the README and architecture document, and archive independent checks and measurements under `result/phase-4c/`. The live gate is tracked by V7. (R1-R5)

The saved provider/model selection belongs to Settings. Each generation or retry snapshots that selection at the start of the request. Saved scene briefs and outcomes belong to the lesson version. Keep the existing data-directory backup and restore flow. Use the current synchronous routes and explicit retries for this phase.

## Independent verification

Use an isolated `STUDY_DATA` directory, scripted CLI outputs, and synthetic lessons. Record the tested revision, exact commands, fixture identifiers, CLI versions, and applicable screenshots or elapsed timings.

| ID | Requirements | Steps and expected result | Evidence | Status |
| --- | --- | --- | --- | --- |
| V1 | R1 | Stub each CLI with known IDs and display names. Open Settings, change providers and refresh. Search by name and ID. Display exactly the returned usable IDs. Verify a pre-existing saved ID with a successful refresh that omits it. | CLI invocation record and browser assertions | Pass |
| V2 | R1, R5 | Inject empty, malformed, timed-out and unavailable catalog responses. Verify the localized reason and refresh control, zero selectable IDs, and no stale or invented options. | Backend assertions and VI/EN browser output | Pass |
| V3 | R2 | Generate with Codex for prose and an explicit agy visual model. Inspect both boundaries for scope and exact model routing. Restart, change the visual model, and verify the next generation or repair uses the new exact ID. Check the inherited path with existing settings. | Scripted provider requests and restart assertions | Pass |
| V4 | R2-R5 | Generate a lesson with multiple scenes. Fail a later scene with a timeout or malformed payload. Reload the reader, grade a quiz, use the completed scene, and retry the failed slot with the selected model. Verify only that slot is regenerated and the lesson version stays stable. Also fail a prose request and verify the writing-stage error. | API assertions, browser recording and stage timings | Pass |
| V5 | R3, R4 | Retry the same slot concurrently and complete scenes out of order. Reopen the lesson with an existing highlight and quiz attempt. Verify one committed result per slot, correct scene references, and intact progress. | SQLite and browser assertions | Pass |
| V6 | R4 | Trigger one automatic repair, then a manual repair. Fail one replacement and verify the old scene still renders. Run the Python suite, frontend build and browser regression suite, including saved lessons and the existing iframe runtime. | Regression logs and repair assertions | Pass with offline Chromium |
| V7 | R2, R4, R5 | With compatible signed-in CLIs, discover catalogs and run the Codex-prose/agy-illustration flow on a disposable synthetic course. Confirm the exact model, non-interactive mode, permission settings and a successful agy repair. Record outcomes and elapsed time separately for prose, scene generation and repair. If CLI compatibility, credentials, or quota block the run, record the cause and leave the live gate open. | Sanitized commands, CLI versions and timing report | Blocked by CLI state and sign-in access |

**Exit check.** V1–V7 pass. A learner can save the provider split, reopen a partially illustrated lesson, retry the failed scene, and repair a saved illustration with the selected model. The rendered lesson, historical study data and existing tool behavior pass regression checks.

The [verification report](../result/phase-4c/document.md) records the passed scripted flow and the remaining V7 live gate.

## Delivery estimate

Allow two to three focused coding days. The first milestone is a working searchable CLI catalog and exact model routing. The second is a reader demonstration where agy times out on a later scene and the lesson and quiz remain usable after reload. Finish with independent regression checks and a live smoke test. Live verification depends on compatible CLI versions, sign-in and quota.
