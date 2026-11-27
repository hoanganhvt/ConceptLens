# Phase 4C implementation and verification

ConceptLens loads the illustration model catalog from the selected CLI, persists the exact model ID, and uses that model for scene creation and repair. A generated lesson remains readable and its quiz remains usable when an illustration fails. Retrying uses the saved brief for the affected slot. Existing scene indices, progress, highlights and tutor threads remain valid after recovery. [Requirements](../../plans/phase-4c.md) · [Architecture](../../documents/phase-4c-architecture.md)

## Independent checks

The [source manifest](evidence/manifest.json) identifies the base revision and tested working-tree files. The checks used synthetic lessons in a disposable study directory. The offline Chromium harness served the compiled app and relayed its API requests to the real FastAPI application over stdio. It supplied scripted replies at the CLI boundary and retained the same SQLite directory across process restarts. [Browser harness](code/offline_browser.mjs) · [API bridge and fixtures](code/offline_api.py)

| Check | Result | Expected and observed behavior |
| --- | --- | --- |
| V1 · CLI catalogs and picker | Pass | The Codex and agy pickers displayed only IDs from successful CLI replies. The browser filtered by name and ID, changed providers, reopened Settings and refreshed the catalog. The removed saved model appeared as a status and was absent from selectable options. [Browser assertions](evidence/browser-offline.txt) · [Removed-model screenshot](evidence/offline-model-removed.png) |
| V2 · Catalog errors | Pass | The harness supplied empty, malformed, failed and timed-out replies. The selector remained empty and disabled, with localized errors and recovery through refresh. Scripted Codex pagination omitted hidden entries and added only the visible options. [Browser assertions](evidence/browser-offline.txt) · [Vietnamese error screenshot](evidence/offline-catalog-vietnamese.png) · [Python assertions](code/verification/tests/test_study.py) |
| V3 · Provider and exact model routing | Pass | Codex received the prose request. agy received one brief and the relevant section per scene. The saved visual selection survived backend restart. Changing it affected the next retry and repair, and the inherited path used the configured Codex model. [Browser assertions](evidence/browser-offline.txt) · [API fixture](code/offline_api.py) |
| V4 · Partial lesson and retry | Pass | A scripted prose timeout reported the writing stage and left the lesson retryable. A later illustration timed out while prose, the quiz and the completed scenes stayed usable. After a reload, the browser retry dispatched only the failed scene. [Browser assertions and stage logs](evidence/browser-offline.txt) · [Partial-lesson screenshot](evidence/offline-partial-lesson.png) |
| V5 · Stable scene references | Pass | The harness submitted two copies of the browser's retry concurrently. One call completed the missing scene and left the version and committed indices stable. The 19.62 m highlight and correct quiz attempt survived restart and out-of-order scene completion. A stale lesson version was rejected. [Browser assertions](evidence/browser-offline.txt) · [Python assertions](code/verification/tests/test_study.py) |
| V6 · Repair and regression | Pass with offline Chromium | A malformed automatic repair preserved the saved scene. A manual repair used the selected model and rendered in the sandboxed frame. The offline harness reopened a pre-4C lesson and replayed the full shared Chromium assertions through its ASGI bridge. The Python suite passed all 42 tests, including the real subprocess output and timeout checks, and the Vite build passed. The standard loopback browser command was blocked before page load. [Phase browser assertions](evidence/browser-offline.txt) · [Full browser regression](evidence/browser-regression-relay.txt) · [Loopback diagnostic](evidence/browser-loopback.txt) · [Python output](evidence/unit-independent.txt) · [Build output](evidence/build-independent.txt) |
| V7 · Live Codex and agy | Blocked | Installed Codex 0.172.0 returned 11 models in a disposable CLI home. The normal CLI home could not start the catalog in this session, and the structured inference probe returned HTTP 502. Installed agy 1.5.18 reported sign-in required and could not read the Windows credential store. The mixed-provider generation, repair and live permission checks remain open. [Live probe](evidence/live.txt) · [Codex protocol probe](evidence/live-codex-catalog.txt) · [Codex inference probe](evidence/live-codex-inference.txt) |

## Reproduction

Run from the repository root with the existing Python environment, Node.js and Chrome or Chromium. The normal browser suite needs access to a local TCP listener. In the managed Windows session, the independent test used named pipes for the Python event loop wakeup and a stdio bridge for Chromium's API requests.

```powershell
npm.cmd run build
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd run test:ui
```

The archived checks used these commands and runners.

```powershell
.\.venv\Scripts\python.exe result/phase-4c/code/run_unit_windows.py
node result/phase-4c/code/offline_browser.mjs
node result/phase-4c/code/offline_browser.mjs --regression
.\.venv\Scripts\python.exe result/phase-4c/code/live_smoke.py --codex-catalog-only
.\.venv\Scripts\python.exe result/phase-4c/code/live_smoke.py --codex-proof-only --codex-model gpt-6.2-sol
.\.venv\Scripts\python.exe result/phase-4c/code/live_smoke.py
```

[Windows test runner](code/run_unit_windows.py) · [Loopback browser source](code/verification/tests/browser.mjs) · [Live smoke source](code/live_smoke.py) · [Scripted benchmark](benchmark.md)

## Exit decision

The implementation and scripted verification are complete. Phase 4C remains open until the signed-in Codex-to-agy flow generates and repairs a synthetic lesson and the live agy permissions check passes. The live command needs a Windows session that can use both CLI installations and their sign-in state.
