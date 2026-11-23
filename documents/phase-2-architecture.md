# Phase 2 — Learner memory

ConceptLens stores learner-confirmed goals and preferences and recognizes recurring unit mistakes from quiz attempts. Each study-data directory has one server-assigned owner. English and Vietnamese share that owner's memory settings. An automatic pattern belongs to its original roadmap, and the learner can inspect it from either interface language. Tutor replies and Phase 1 working context continue to use their existing inputs. [Requirement and verification plan](../plans/phase-2.md)

## Quiz and worker flow

1. The reader sends a quiz attempt UUID and retains it when retrying the same answer. The quiz endpoint accepts requests without a UUID for older clients. A repeated ID for the same answer and source returns the saved progress. Reuse with a different answer, question, lesson version, or course returns a conflict. [Reader](../src/main.tsx) · [Quiz route](../backend/main.py)
2. The grader uses Pint to distinguish omitted units from incompatible units and to evaluate the numeric result using the existing tolerance. Wrong magnitudes and choice mistakes carry no automatic unit diagnosis. In a single SQLite transaction, the quiz route saves the progress entry, indexes its source, and queues eligible diagnostic work if capture is enabled. [Grader](../backend/physics.py) · [Quiz route](../backend/main.py)
3. A worker runs with the FastAPI application and attempts a bounded batch at startup and about once per second. It reads events in submission order. Each event is applied and consumed in a separate transaction from grading. An interrupted event stays pending for another pass. The worker logs the failure category and the queue stores the retry count. [Application lifespan](../backend/main.py) · [Worker](../backend/learner_memory.py)
4. Each automatic memory groups evidence by roadmap, expected physical dimension, and diagnostic. Only the latest qualifying observation for a question contributes. Two independent questions establish a recurring mistake. A later correct answer removes that question's support, reducing the memory to tentative at one source and resolved at zero. Unclassified failures leave its evidence unchanged. Learner edits make a record learner-managed and protect its correction from queued work. [Evidence projection](../backend/learner_memory.py)

## Storage and lifetime

The transactional schema upgrade adds version 2 to the existing `study.sqlite` database. The `records` table continues to hold the original attempts, chat, and lessons. Roadmaps still use their existing files. Stop the server before copying the study-data directory for a backup. [Database initialization](../backend/main.py) · [Backup procedure](../README.md#data-and-backups)

| Table | Responsibility |
| --- | --- |
| `learner_memory_settings` | Opt-in state, collection generation, and the processed submission watermark. |
| `quiz_submissions` | Per-owner UUID and stable location of the original answer, with a lesson version, timestamp, and sequence. |
| `learner_memories` | Automatic and learner-managed records, wording, scope, status, and revision. The API derives confidence from status. |
| `learner_memory_evidence` | Links current supporting observations to original submissions. |
| `learner_memory_pending` | Durable diagnostic work linked to the committed submission, with revision and retry metadata. |
| `learner_memory_suppression` | Pattern key and sequence cutoff used when forgetting or resuming collection. |

Pausing capture cancels queued work and advances the generation so stale work cannot be applied after re-enabling. The learner can review and change retained records while paused. Forgetting removes the memory and its evidence links and cancels work for that pattern. Suppression keeps the diagnostic, scope, and a sequence cutoff. An explicit remember action on eligible new quiz feedback starts the pattern again from that attempt. The original study history remains in the existing records. A backup taken before forgetting retains the state saved at that time. [Memory repository](../backend/learner_memory.py)

## Settings and API

Settings provides a localized capture switch, goal and preference entry, evidence details, revision-aware edit, and a forget confirmation. It reads an exact attempt through its memory and submission IDs and verifies the saved lesson version before displaying the source. The view preserves the language of explicit learner text. [Memory settings](../src/MemorySettings.tsx) · [Reader and quiz](../src/main.tsx) · [Request and data types](../src/types.ts)

`GET/POST /api/memories` lists or creates records. `PATCH/DELETE /api/memories/{id}` uses the revision shown to the learner. `PUT /api/memories/capture` changes the setting, `GET /api/memories/{id}/evidence/{attempt_id}` reads one attached source, and `POST /api/memories/resume` starts fresh collection from a validated attempt. The memory API inherits the application's loopback host and write-origin checks. It makes no provider requests. [Memory routes](../backend/main.py)
