# Phase 3 — CPU-first bilingual learner memory retrieval

## Requirements

| ID | Acceptance criteria | Verification |
| --- | --- | --- |
| R1 | Local, optional CPU encoder. Windows x64 with two cores, 4 GB RAM and no GPU or AVX-512 requirement. On 1,000 memories, warm retrieval p95 ≤150 ms, added peak working set ≤350 MiB, optional installed footprint ≤250 MiB. A request waits at most 200 ms for optional retrieval. | V1 |
| R2 | English/Vietnamese retrieval with at least 80% recall@3, the canonical Vietnamese-to-English preference at rank one, and zero matches on the abstention fixtures. | V1 |
| R3 | Owner, status, current revision and supported scope are checked before ranking. Edits, forget and encoder rebuilds cannot resurrect stale vectors. Existing SQLite data survives migration. | V2 |
| R4 | Both tutor providers respect the complete serialized request budget, and saved references identify only memories actually sent. Revocation during a turn is retryable and atomic. The reader keeps its full transcript. | V3 |
| R5 | The existing memory toggle controls capture and use. Bilingual Settings explains provider disclosure and encoder readiness. Chat links to the exact memory and its evidence, with edit and forget controls. | V4 |
| R6 | An English scientific report records reproducible comparisons, errors, and limits, with links to exact code, fixtures, and raw measurements. | V1 |

## Tasks

- [ ] T1 (R1, R2) Compare Bekko a8m with OpenVINO vocabulary INT8, E5 Small with Xenova ONNX INT8, Univo static INT8 128d and SQLite FTS5/BM25. Use 30 answerable and 30 abstention queries per dev and held-out split, split by memory/topic. Include both cross-language directions, same-language, unaccented Vietnamese, negation, hard distractors and supersession. Benchmark batch one in three seeded warm passes and three fresh loads with 100, 1,000 and 10,000 memories. Calibrate on dev. Choose the highest recall eligible encoder, treating differences within two percentage points as a tie, then prefer lower RAM and lower p95. Freeze candidate and threshold before held-out. If no candidate passes or genuinely low-spec evidence is unavailable, leave semantic retrieval out of release and Phase 3 open. **Release qualification remains open. No encoder passed the exploratory dev quality gate and target hardware remains unavailable.** [Benchmark](../result/phase-3/benchmark.md)
- [x] T2 (R1–R3) Add optional local encoder loading in one isolated CPU process with two threads maximum, local configuration via `STUDY_EMBEDDING_MODEL_DIR` and an approved, checksum-qualified artifact. Add schema v3, versioned SQLite vectors and a bounded worker. Invalidate vectors transactionally on revision changes, then run inference outside transactions and recheck live revision before updates. Switch indexes after coverage. Select on owner, roadmap or learner scope, confirmed/recurring status and current live revision. Recurring memories require two valid sources. Rank normalized vectors by cosine, then quality and recency, deduplicate and fail closed. Use current question, topic and up to 256 anchor characters. Use no lexical fallback in production.
- [x] T3 (R4, R5) Use the existing capture toggle and bounded-context gate. Pack at most three memories and 1 KiB in the optional budget, after existing context. Under both adapters revalidate before provider calls and at commit. Save references to items actually sent and return a retryable 409 when a previously sent reference becomes invalid. Exclude memory-assisted replies and traces from future replay and summaries, preserving on-screen transcript. Expose encoder readiness in memory Settings and add a bilingual disclosure with source access and a link to edit/forget the exact revision.
- [x] T4 (R6) At each benchmark run save raw measurements, hardware and runtime settings, hashes and commands. Report abstract, research question, methods, results, error analysis, limitations and release decision. Separate published numbers from measured ones. Report recall@3, top 1, abstention false positives, 95% intervals for recall and false positive rates, warm p50/p95, timeouts, cold loads, RAM and disk. Save figures and raw evidence under `result/phase-3/evidence/` and reproducible scripts/fixtures under `result/phase-3/code/`.

## Independent verification

| ID | Requirements | Prerequisites, steps and expected evidence | Status |
| --- | --- | --- | --- |
| V1 | R1, R2, R6 | Use synthetic data and the four configurations. Record exact commands, versions, dev selection, locked held-out run and target-hardware timings. Run absent, failed and timed-out encoder cases and verify ordinary chat and grading continue. Archive comparative tables and raw outputs. Distinguish constrained VM or host measurements from hardware qualification. | Fail on exploratory quality. Target hardware blocked. Functional fallback passed. |
| V2 | R3 | Upgrade a populated v2 fixture. Interrupt rebuild and restart. Seed stale and foreign vectors, other scopes and statuses, and mutate while encoding. Verify only current authorized rows remain eligible and old data remains readable. Archive SQL/API assertions. | Pass |
| V3 | R4 | Use scripted OpenAI/Codex, repeated calls, a tight budget and revocation during a send. Compare actual serialized request against committed references, check retry and saved transcript, and run existing tests, build, browser smoke and both replays (including 19.62 m). | Pass |
| V4 | R5 | With Playwright, exercise both languages with keyboard, exact evidence, Settings navigation, edit, forget, pause and reload. Verify stale references and no memory sent in new turns after pause. Archive assertions and illustrations. | Pass |

## Delivery

Implementation and independent testing were delegated separately. See the [architecture](../documents/phase-3-architecture.md), [verification](../result/phase-3/document.md) and [scientific benchmark](../result/phase-3/benchmark.md). Leave `PLAN.md` status open until all checks pass.
