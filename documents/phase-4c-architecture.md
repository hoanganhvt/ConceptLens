# Phase 4C illustration provider selection and recovery

Phase 4C uses the existing React reader, FastAPI server and SQLite `records` table. The lesson, the settings selection and a scene's latest attempt each have a separate lifetime. [Phase plan](../plans/phase-4c.md)

## Model discovery and settings

[Settings](../src/main.tsx) resolves the effective illustration provider and loads Codex or agy options from `GET /api/settings/models/{provider}`. Open Settings, change the effective provider, or use **Refresh illustration models** to request a new catalog. The picker filters the returned options by display name and ID. A removed saved ID appears in a status message. A new explicit selection must come from the current catalog. The general provider settings retain their previous controls and defaults.

[The Codex adapter](../backend/providers.py) initializes the installed Codex app-server on stdio from a temporary directory, then requests the visible models through `model/list` with a bounded deadline and pagination. Its `model` field is the ID sent to `codex exec --model`. [The agy adapter](../backend/google_providers.py) uses the installed CLI's `agy models` command and validates the parsed IDs and display names. Missing, empty, failed, timed-out and malformed responses disable the picker and leave a refresh control. Sign-in and usable model access are checked independently of model listing.

[Structured generation](../backend/ai.py) reads the visual override only for `IllustrationBatch` and `Illustration`. The same resolver serves initial generation, retry and repair. The request uses the exact stored ID when an illustration override exists. An inherited selection uses the general provider and its model when the visual model field is empty.

## Lesson storage and recovery

1. [Lesson generation](../backend/main.py) snapshots settings and validates prose, quiz and the illustration plan. It commits a new version with an empty illustration list and one pending record per planned slot. The plan is private to the server.
2. Each scene request receives its brief, topic, introduction, matching section and the [illustration contract](../prompts/illustrations/contract.md). The backend verifies that the output represents the requested section and updates the slot. A successful scene is appended to the illustration list and the slot records its index. A failed scene records the provider, status code and attempt count.
3. The reader uses the slot order for display and the committed illustration index for motion, repair and highlights. Because the list is append-only during generation, completing scenes out of order preserves earlier indices and anchors. Lessons saved before this phase continue to render using their existing illustration indices.
4. `POST /api/lesson/{rid}/{tid}/illustrations/{slot}` accepts the lesson version and the observed attempt count. The per-lesson lock and the attempt check prevent a duplicate click or concurrent stale request from launching a second call for the same attempt. A resumed request reads the plan from SQLite and snapshots the settings then in effect. A reload can recover any pending scene left by an interrupted generation request.

The reader displays status and retry for pending or failed slots and keeps prose and quiz available. A prose failure returns a localized error and leaves lesson generation retryable. The existing GET bundle includes additive scene status. Progress, notes and tutor threads retain their existing keys and use the saved lesson version.

## Repair and observability

The existing repair route uses the same provider selection and sends the affected illustration and runtime error. It commits the replacement HTML, CSS and JavaScript only after a valid structured response. The renderer continues through the existing [Lab iframe](../src/Lab.tsx) and [illustration interpreter](../src/frame.js). Automatic repair retains its previous once-per-scene behavior, and the learner can request manual repair.

The agy transport uses non-interactive stream JSON, a temporary workspace, a JSON schema and scoped permission rules. It rejects incomplete results. A shared 1 MiB limit covers stdout and stderr, and the deadline also covers delivery of the request on stdin. The backend terminates the CLI process if either limit is exceeded. [Antigravity headless mode](https://antigravity.google/docs/cli/headless/) · [CLI permissions](https://antigravity.google/docs/permissions?tab=cli)

Logs record the prose, illustration and repair stage, provider, outcome, elapsed milliseconds and number of previous app-level attempts. See the [verification report](../result/phase-4c/document.md) for the live CLI checks.
