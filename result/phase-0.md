# Phase 0 baseline results

ConceptLens is a local-first learning app. The React reader uses FastAPI endpoints to load lessons, grade quizzes, save simulation playback, and manage tutor threads. Confirmed roadmaps are stored as JSON files. SQLite holds lessons, attempts, highlight snapshots, and chat history. The OpenAI and Codex adapters use the same Python calculator and motion functions.

## Completed

- Added a credential-free replay runner that exercises the same HTTP routes as the reader. Each case starts a new process with its own temporary `STUDY_DATA`. It seeds a built-in lesson, correct and incorrect attempts, two highlight conversations, a main conversation, and an unrelated generated course.
- Added 32 cases covering both adapters and both built-in language samples. The cases cover direct answers, unit conversion, simulation follow-ups, search on and off, provider switching, a long conversation, and provider unavailability.
- Captured SDK requests and Codex CLI inputs, public replies, citations, and tool traces in synthetic replay evidence. A separate metrics file records request sizes, durations, statuses, and reported token counts when available. Both files include fixture and runner revisions, prompt file hashes, adapter or model names, and measurement definitions.
- Added a separately invoked live-provider suite for collecting real latency and reviewing answer quality on synthetic data. It records public replies and usage when available.

## Verified behavior

| Case | Observed result |
| --- | --- |
| Direct answer | Both adapters returned the scripted answer through the reader's chat endpoint. |
| Unit conversion | The calculator returned `19.62` for `1962 / 100`. The quiz accepted `1962 cm` and rejected `19.62 s`. |
| Simulation and branch isolation | The original highlight retained `t = 2 s`, `g = 9.81 m/s²`, and `s = 19.62 m` after playback changed to `10 m`. The request kept the selected branch history and excluded sibling and main thread messages. |
| Search on | OpenAI forced a search on the first call. Codex started with live search enabled. Both adapters returned a citation. |
| Search off | OpenAI still advertised web search with automatic tool selection and accepted a scripted citation. Codex began with search disabled and enabled it on the next call after a scripted search action. These are baseline observations for Phase 4. |
| Provider switch | Switching in either direction preserved the original branch and exposed the previous result to the next adapter. |
| Long conversation | The original calculation remained visible at the provider boundary after 20 intervening turns. The app sent all 44 prior messages for the final follow-up. |
| Provider unavailable | The chat endpoint returned HTTP 503 and preserved the prior transcript for each adapter and language. |

## Replay measurements

The verified run on November 23, 2026 completed all 32 cases with no unexpected HTTP failures.

| Adapter | Stub | Successful chat requests | Expected HTTP 503 responses | Provider calls | Chat p50 | Chat p95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| OpenAI | `scripted-openai-http-v1` | 106 | 2 | 114 | 14.09 ms | 952.04 ms |
| Codex | `scripted-codex-jsonl-v1` | 106 | 2 | 116 | 14.86 ms | 22.92 ms |

Percentiles use nearest rank over successful in-process chat requests, including fixture chat turns and adapter setup during those requests. They describe local replay time on this machine. Stub token usage is unavailable. Live-provider latency and answer quality remain unmeasured.

| File | SHA-256 |
| --- | --- |
| `tests/evals/fixtures.py` | `fd467c43cda04af0b34b6b96e16894ec28a162e0022960f4f9455249853c2e50` |
| `tests/evals/runner.py` | `135ff0cbc2fab2c7b0d10ed2c6dc3c5630f5278a980698e2238fb5ef1892f5d2` |
| `prompts/tutor/instructions.md` | `34692fdfee8732c10db727ff3328e0fa1f78164131331910664fb5243eff29e8` |
| `prompts/tutor/codex-tools.md` | `8f02122f893195b9d3c2643097c81b8b77a4855da2a1721a13f9a8eff57a3334` |
| `prompts/providers/openai-context.md` | `ce0bbc9cde14dd43091f346542c84d268c8bf431b0f91cd9a633737ba0fbd273` |
| `prompts/providers/codex-context.md` | `85bd5bb64564ee7025e067bb4d895e2052ecfc6d93b72e2037ed22e79a100326` |
| `prompts/tools/calculator.md` | `9dcfd9040f2b06310bf5a49fd6e1bf5783e08cf2a481b2006ed1a78bfc1efc21` |
| `prompts/tools/simulate_motion.md` | `da5a2febdfe94fe7d758d71a86df7aabce1b984c623e65661b8effc794508100` |

The existing Python tests, frontend build, and Playwright browser smoke test also passed.

## Reproduce

Run after installing the project's Python dependencies.

```powershell
.\.venv\Scripts\python.exe tests/evals/runner.py --output "$env:TEMP\conceptlens-evals"
```

This writes `replay-metrics.json` and `replay-evidence.json`. For live evaluation, configure `OPENAI_API_KEY` for OpenAI. For Codex, sign in locally and replace `MODEL_ID` with a model available to that CLI.

```powershell
.\.venv\Scripts\python.exe tests/evals/runner.py --live --provider openai --output "$env:TEMP\conceptlens-live-openai"
.\.venv\Scripts\python.exe tests/evals/runner.py --live --provider codex --codex-model MODEL_ID --output "$env:TEMP\conceptlens-live-codex"
```

For live review, check whether each direct reply explains the relationship in the selected language, whether conversion and simulation replies give the expected value and unit, and whether search replies cite a source that supports the answer. Use `live-metrics.json` for timing and provider-reported token counts.
