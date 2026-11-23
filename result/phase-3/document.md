# Phase 3 implementation and verification

Phase 3 adds optional CPU-based retrieval for learner memory, a revision-aware SQLite index, and a bilingual chat disclosure that opens the corresponding memory and quiz evidence. The normal installation has no approved encoder. The app continues to grade locally and answer tutor questions with lesson context when retrieval is unavailable.

## Delivered

- SQLite schema v3 indexes committed memory revisions and invalidates vectors on edit and forget. Owner, scope, status and live evidence are checked before ranking.
- Both tutor adapters fit memory in the existing bounded request, validate references before dispatch and save only the references actually included. A concurrent revocation aborts the turn with a retryable conflict. The reader keeps the full conversation.
- The existing learner-memory control governs both capture and use. Settings shows encoder readiness and explains provider disclosure. The reader opens the exact memory revision and its supporting quiz attempts.
- The scientific benchmark compares three real CPU encoders with SQLite BM25 and includes the experimental protocol, versioned artifacts, calibration, raw per-query measurements and analysis. [Architecture](../../documents/phase-3-architecture.md) · [Scientific benchmark](benchmark.md)

## Independent checks

The [verification manifest](evidence/verification-manifest.json) records base revision `62d6cc4766e0ab9d4726058de84a79fc876a6876`, the tested working-tree source digests and complete commands. The archived [unittest source](code/verification/tests/test_study.py), [browser source](code/verification/tests/browser.mjs), [replay runner](code/verification/tests/evals/runner.py) and [replay fixtures](code/verification/tests/evals/fixtures.py) match their shared versions. Tests used temporary study data, synthetic learner records, scripted providers and local Chrome.

| Check | Result | Expected and observed evidence |
| --- | --- | --- |
| **V1 · Quality and CPU qualification** | **Fail on exploratory quality. Target hardware blocked.** | The agreed release gates require recall@3 of at least 80% with all dev abstention cases rejected and a qualified end-to-end measurement on a two-core Windows machine with 4 GB RAM. The exploratory comparison used a Core i5-12450H with 16 GiB RAM. Its outcome leaves the production encoder unapproved. Missing, failed and timed-out encoder fallback passed the functional suite. A separate Windows process smoke loaded the real static weights, encoded synthetic English and Vietnamese, rejected a modified checksum and closed the child. [Benchmark](benchmark.md) · [Unit evidence](evidence/verification-unit.txt) · [Worker assertions](evidence/encoder-process-static.json) · [Worker smoke code](code/encoder_process_smoke.py) |
| **V2 · Index and migration** | **Pass** | Migration from schema 0, 1 or 2 preserved legacy data and repeat starts. The rollback fixture preserved the original database. The revision and scope fixtures excluded foreign, stale, tentative and unsupported records. Rebuild and concurrent edits or forget could not write obsolete vectors. [Unit evidence](evidence/verification-unit.txt) |
| **V3 · Tutor provider behavior** | **Pass** | Request assertions exercised both adapters, reference capture, constrained budgets, later tool calls, revocation and same-ID retry. The assistant transcript remained available with the old memory-assisted reply excluded from later model context. All 22 backend tests passed. The ordinary replay passed 32 cases and 216 turns, including expected missing-provider responses. The bounded replay passed four cases and 100 turns, including the 19.62 m result. [Unit evidence](evidence/verification-unit.txt) · [Replay](evidence/verification-replay.txt) · [Replay assertions](evidence/verification-replay-evidence.json.gz) · [Bounded replay](evidence/verification-bounded.txt) · [Bounded assertions](evidence/verification-bounded-evidence.json.gz) |
| **V4 · Bilingual reader and Settings** | **Pass** | TypeScript and Vite built successfully. Playwright used keyboard navigation in English and Vietnamese, opened exact historical quiz evidence, focused the matching revision in Settings, and confirmed stale disclosure after edits and forget. Tests also exercised pause and reload. Vite printed its existing bundle-size advisory. [Build](evidence/verification-build.txt) · [Browser](evidence/verification-browser.txt) · [English Settings](evidence/verification-memory-settings-en.png) · [Vietnamese disclosure](evidence/verification-memory-disclosure-vi.png) |

## Exit decision

V2–V4 and the operational fallback checks passed. The scientific comparison did not qualify a release encoder, and end-to-end timing and working set on the specified Windows 4 GB machine remain unverified. Phase 3 remains open under the agreed exit criteria.
