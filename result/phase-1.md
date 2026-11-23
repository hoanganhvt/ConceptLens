# Phase 1 implementation and verification

ConceptLens can build bounded tutor requests for a single conversation branch. In the English and Vietnamese free-fall fixtures, both adapters retained the original selected state and the verified **19.62 m** result after 20 intervening turns and a provider switch. The reader continued to receive the complete branch transcript.

## Delivered

- Requests carry the active question, study language, lesson version, and topic goal. Highlight requests use the captured quote, offsets, and simulation snapshot. Current playback and prior tool observations carry separate provenance. Quiz context uses previously submitted feedback.
- The backend checks the assembled request before each model call, including tool continuations and summaries. The budget accounts for provider instructions, request wrappers, and tool schemas. It uses serialized UTF-8 bytes as a conservative input estimate and logs provider-reported counts separately when available. Operational metrics exclude learner text.
- SQLite stores versioned summaries by local owner, roadmap, topic, lesson version, and branch. The summary advances over complete turns and records the covered sequence. The original transcript stays available, and a failed summary call leaves the last good summary and fitting verified evidence available for the next request.
- The reader reuses a request ID for retries of the same text and search setting. SQLite reserves one send per branch with a renewable lease, then commits the message pair, request record, and any summary update in one transaction. Provider calls run outside the transaction. Committed retries return the full current transcript. Competing sends receive a retryable response, and an expired worker cannot append a reply.
- The rollout switch controls bounded context. Both modes share retry-safe writes and continue returning the same chat arrays. Existing course data and transcripts remain readable.

## Verification

| Check | Result |
| --- | --- |
| Python regression suite | 8 tests passed. Covered legacy transcript append, duplicate and competing sends, unrelated branch progress, expired worker replacement, provider failure, cached summary reuse and fallback, and localized oversized input. |
| Baseline replay | 32 credential-free cases completed with zero unexpected HTTP failures. |
| Bounded replay | 4 credential-free cases and 100 successful chat requests across both adapters and both languages. Checked branch isolation, captured playback, hidden quiz answers, summary reuse, the original tool evidence, provider switching, and the full saved transcript. |
| Frontend build and browser smoke test | Passed. The smoke test used scripted chat responses to verify retry ID reuse, draft preservation on failure, and transcript display after reload. |

The bounded replay used a 4,856-byte input guard. The OpenAI HTTP body reached 4,851 bytes across 66 calls, including 14 summaries. Codex stdin and schema reached 4,837 bytes across 93 calls, including 41 summaries. These figures describe the intentionally small scripted fixture. Live answer quality, latency, and token-estimate calibration remain unmeasured. The Codex budget reserves room for output, since the adapter does not enforce a CLI output-token limit.

## Enable and reproduce

The feature is off by default. Run these commands from the project directory to enable it for the local server.

```powershell
$env:STUDY_BOUNDED_CONTEXT = "1"
.\start.cmd
```

Set the variable to `0` before restarting to return to the baseline prompt path. The default estimated model window is 16,384 tokens, with 4,096 reserved for output and 2,048 for additional overhead. Use `STUDY_TUTOR_CONTEXT_WINDOW` to set the fallback or `STUDY_TUTOR_MODEL_WINDOWS` to supply a JSON map keyed by provider and model, such as `{"openai:gpt-4.1":16384}`. The Codex CLI default uses the key `codex:default`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe tests/evals/runner.py --output "$env:TEMP\conceptlens-phase1"
.\.venv\Scripts\python.exe tests/evals/runner.py --bounded --output "$env:TEMP\conceptlens-phase1"
npm.cmd run build
npm.cmd run test:ui
```

The replay reports contain fixture and prompt hashes, call sizes, timings, and synthetic provider-boundary evidence.
