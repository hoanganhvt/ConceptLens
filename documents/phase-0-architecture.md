# Phase 0 — Tutor baseline replay

Phase 0 added a repeatable evaluation harness for the existing tutor. It exercises the same FastAPI routes and Python tools as the reader while controlling the provider boundary. The historical measurements and observed behavior are in the [Phase 0 verification report](../result/phase-0.md). The current runner reproduces the baseline prompt path with `STUDY_BOUNDED_CONTEXT=0` on the current application.

## Runner and fixture lifecycle

1. The parent runner starts a Python worker for each combination of OpenAI or Codex, English or Vietnamese, and eight scenarios. The 32 default cases cover direct answers, unit conversion, simulation follow-ups, search on and off, provider switching, long conversations, and provider unavailability. Each worker creates a temporary `STUDY_DATA` directory before importing the backend so local settings, SQLite records, and saved roadmaps are isolated per case. [Runner](../tests/evals/runner.py)
2. FastAPI's in-process `TestClient` sends the study-language header and drives the production lesson, quiz, motion, note, roadmap, settings, and chat routes. The fixtures check an incorrect unit and a correct conversion, capture two highlight snapshots on the same lesson, and create an unrelated generated course from schema-validated fixture data. Scenario setup and chat turns exercise the main thread and both highlight branches. The primary highlight captures **19.62 m** at **2 s**. The sibling snapshot and later playback hold **10 m**, making leaked context visible. [Fixtures](../tests/evals/fixtures.py) · [FastAPI routes and storage](../backend/main.py)
3. The tutor builds its normal requests. OpenAI uses the real SDK with an `httpx.MockTransport` that returns scripted Responses API data. The Codex stub intercepts the subprocess boundary, inspects stdin, CLI arguments, and the response schema, and returns scripted JSONL. Both adapters dispatch calculator and motion calls through real Python code. This keeps provider serialization, response parsing, tool dispatch, and transcript persistence in the replay while making it independent of credentials and provider availability. [Boundary recording and stubs](../tests/evals/runner.py) · [Tutor adapters](../backend/ai.py) · [Codex CLI integration](../backend/providers.py) · [Physics and grading](../backend/physics.py)

## Reports and interpretation

| Output | Contents |
| --- | --- |
| `replay-metrics.json` | HTTP and model-call status, provider, search setting, call kind, request size, elapsed time, and provider-reported token counts when available. |
| `replay-evidence.json` | Synthetic provider inputs and public replies, including returned sources and Python traces where present. |

Both outputs include fixture and runner SHA-256 digests, prompt file hashes, adapter or model identifiers, and measurement definitions. Chat timing covers the in-process POST. Model-call timing covers the SDK call or CLI execution. The baseline size proxy uses serialized OpenAI SDK arguments and Codex stdin plus the response schema. Keeping evidence and measurements in separate files lets the same scenarios support performance comparisons and request inspection. [Report generation](../tests/evals/runner.py)

The recorded baseline sends full branch history, including 44 prior messages in the final long-conversation request. Branch selection excludes sibling and main messages from a highlight request. The search-off case records provider behavior for later comparison. OpenAI still advertises search, and Codex can enable search on a later iteration after a model request. [Scenario assertions](../tests/evals/fixtures.py) · [Phase 0 verification report](../result/phase-0.md)

Run the replay from the project root after installing the project's Python dependencies.

```powershell
.\.venv\Scripts\python.exe tests/evals/runner.py --output "$env:TEMP\conceptlens-evals"
```

The separate `--live` suite runs five scenarios against real providers using synthetic data. OpenAI requires `OPENAI_API_KEY`. Codex requires a signed-in CLI and an explicit `--codex-model`. The live reports retain public replies and available usage while omitting raw provider inputs. Live latency and answer quality were outside the recorded baseline measurements. [Live mode and commands](../tests/evals/runner.py) · [Phase 0 verification report](../result/phase-0.md)
