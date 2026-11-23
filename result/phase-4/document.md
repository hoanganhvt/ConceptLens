# Phase 4 implementation and verification

The tutor can use one orchestration policy with either OpenAI or Codex CLI. It supports direct answers, clarification, calculator and motion results, sourced search, and a scoped physics explanation. Enable it with `STUDY_TUTOR_AGENT=1`. Existing study data, chat request IDs and the returned transcript format are compatible. [Requirements](../../plans/phase-4.md) · [Architecture](../../documents/phase-4-architecture.md)

## Independent checks

The source manifest records the base revision, checked working-tree files, commands and prerequisites. The tests used synthetic study data. The OpenAI checks passed through the installed SDK using a mock HTTP transport. The Codex checks recorded the actual subprocess arguments and returned scripted JSONL events. The browser suite used local Chrome and scripted chat responses. [Source manifest](evidence/manifest.json) · [Phase 4 assertions](code/verification/tests/test_tutor_agent.py) · [Phase 4 output](evidence/phase-4.txt)

| Check | Result | Expected behavior and observation |
| --- | --- | --- |
| V1 · Direct and clarify | Pass | Each adapter committed the answer or focused question after one model decision and zero dispatched actions. The logs recorded the counts. |
| V2 · Motion, batching and adapter switch | Pass | A native OpenAI batch preserved each call ID. The two adapters used the selected motion snapshot over conflicting inputs and returned the verified 19.62 m with provenance. A follow-up through the other adapter contained the earlier result. |
| V3 · Validation and application caps | Pass | Unknown, malformed, repeated and nonfinite actions produced typed observations. A correction succeeded and an over-cap batch caused no local dispatch. The six-decision test stopped without a reply when the model kept requesting work. |
| V4 · Search permission and citations | Pass for the application boundary | Search off removed the OpenAI tool and disabled Codex search. A sourced turn required a completed event and a usable HTTP(S) URL. Both adapters disabled search on follow-up decisions. Earlier citations moved to the end of the answer and OpenAI kept valid final ranges. An over-cap Codex search transcript was rejected before any local dispatch or commit. |
| V5 · Deadline, budget and retry | Pass | Transport timeout and injected late response both resulted in recoverable errors. A summary used part of the shared allowance and the next transport received the remainder. A tiny input budget stopped before the provider. Expiration during commit rolled back the writes. An interrupted lease left the transcript intact and same-ID retry committed once. |
| V6 · Specialist | Pass | The specialist received the original question, relevant excerpt and a verified result using the selected model with search disabled and no callable tools. Invalid, unavailable or over-budget delegation used the expected failure or fallback. |
| V7 · Application regression | Pass | All 30 Python tests passed. The frontend built with the existing bundle-size advisory. Chrome confirmed grading, illustrations, LaTeX, saved conversations, retry, settings and bilingual learner-memory flows. [Python output](evidence/unit.txt) · [Python source](code/verification/tests/test_study.py) · [Build output](evidence/build.txt) · [Browser output](evidence/browser.txt) · [Browser source](code/verification/tests/browser.mjs) |
| V8 · Codex-hosted search cap | Pass under approved exception | The tested Codex CLI reports hosted searches after execution. The user accepted counting completed events after return in place of a preemptive cap. The scripted test confirmed that seven completed search events cause rejection before any local dispatch or commit. [Phase 4 assertions](code/verification/tests/test_tutor_agent.py) · [Phase 4 output](evidence/phase-4.txt) · [Installed CLI options](evidence/codex-options.txt) |

The [scripted benchmark](benchmark.md) ran 160 measured turns. It captures request sizes and local overhead. Live provider latency, answer quality and the production deadline calibration remain unverified.

## Exit decision

Phase 4 is complete under the user-approved exception for Codex-hosted search. The shared loop is available for opt-in use. A Codex-hosted search may run before the application can count its event. Phases 4A–4C retain their separate gates.
