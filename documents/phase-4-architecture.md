# Phase 4 tutor orchestration

Set `STUDY_TUTOR_AGENT=1` before starting ConceptLens to use the shared tutor loop. `STUDY_BOUNDED_CONTEXT=1` independently enables the existing model-window budget and summary cache. The default turn deadline is 240 seconds and can be set with `STUDY_TUTOR_DEADLINE_SECONDS`. [Requirements](../plans/phase-4.md) · [Verification report](../result/phase-4/document.md)

## Chat lifecycle

1. The [chat endpoint](../backend/main.py) takes the question, search consent and optional request ID. The existing [SQLite reservation](../backend/chat_state.py) serializes edits to a branch and replays completed requests. The server snapshots provider settings. When bounded context is enabled, the [context builder](../backend/tutor_context.py) selects the relevant lesson, history, simulation and eligible memory evidence.
2. The [shared orchestrator](../backend/tutor_agent.py) chooses the adapter from the turn settings. Both adapters translate model output into a decision containing final text, actions and citations. OpenAI uses native function calls and keeps their call IDs in continuation messages. Codex requests a typed JSON response and receives tool observations in `results`.
3. The loop validates a route against its registered argument model, checks permissions, dispatches and validates output. A successful calculation contributes a trace. An invalid, unavailable or repeated action contributes a compact error observation. Before a new request, bounded context accounts for the provider wrapper, tool schemas and continuation. A direct answer or focused clarification can finish in the first decision.
4. The deadline and lease guard the final commit. The database still stores the full user/assistant pair, including sources and successful tool traces. Summary updates and memory reference verification use the same transaction. The reader receives the usual transcript array, and the request can be retried after a failed turn.

## Routes and limits

| Route | Input and verification |
| --- | --- |
| Calculator | A bounded arithmetic expression runs through the existing restricted AST evaluator. Its result must be a finite number. |
| Simulation | Acceleration, initial velocity and time are range checked. `use_snapshot` selects the active highlight’s captured parameters and time. Verified output contains time, distance and velocity with SI units. |
| Web search | The adapter advertises or enables its search capability only with consent. A sourced turn needs a completed search plus usable HTTP(S) citations. OpenAI uses its native ranges and Codex links are appended to the answer. |
| Physics explanation | The provider receives the learner’s question, a relevant lesson excerpt and one verified result. It returns a typed recommendation for the main tutor to use. The specialist request exposes no tools. |

The turn permits six model decisions and applies a six-action budget to search, tools and specialists. Local batches are admitted before dispatch. OpenAI requests at most one hosted search in its search-enabled decision. Codex hosts search inside its subprocess, so the adapter counts completed operations from the returned events and rejects over-budget results before local dispatch or commit. The tested CLI exposes no preemptive count limit for those hosted operations. [Verification report](../result/phase-4/document.md)

Summary, specialist, startup and continuation calls share the monotonic deadline. Each provider transport receives the remaining time, and the commit rejects expired work. Operational logs record route, status, reason, counts and durations with no prompts, credentials or learner text. [Scripted benchmark](../result/phase-4/benchmark.md)

The prior path is available by removing `STUDY_TUTOR_AGENT`. The Phase 4 setting affects chat. Roadmap and lesson generation and illustration repair continue through [structured generation](../backend/ai.py). The phase adds no database migration or executable-code route. Phases 4A–4C retain their own delivery criteria.
