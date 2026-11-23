# ConceptLens tutor memory, orchestration and sandbox plan

## Follow the plan

Read this file when the user says "follow the plan". Once the user chooses a delivery phase, the coordinating agent carries it through planning, implementation, and independent testing without separate approval at each step. The delivery sequence and its exit checks guide the work. Ask the user only when a decision or permission is required to proceed.

### Planning before implementation

1. Before changing code for a delivery phase, save its full requirements and implementation plan under `plans/`, for example `plans/phase-2.md`.
2. Give every mandatory requirement a stable ID such as `R1`. State what must be achieved, how to recognize success, and which test will verify it. Include the scope, constraints, dependencies, affected interfaces, expected behavior, and relevant failure cases in enough detail that another implementer can follow the plan.
3. Split implementation into small tasks with stable IDs such as `T1` and link each task to the requirements it fulfills. Start tasks with `[ ]` and change them to `[x]` only after the planned work is complete. Note blockers and partial progress next to the relevant task.
4. Include an independent test checklist. Give each test a stable ID, link it to its requirements, and write out the prerequisites, steps, expected result, and evidence to record. Start every test as `Pending`.

### Implementation phase

After saving the plan, delegate the planned tasks to an implementation subagent. Give it the plan, task IDs, and relevant constraints. The coordinating agent reviews the changes, updates task markers in `plans/`, and records what changed and what remains open. Leave test statuses pending and proceed to the test phase once implementation is ready.

Before marking a delivery phase's implementation complete, save an architecture document in `documents/`, for example `documents/phase-2-architecture.md`. Document everything implemented in that phase as it exists in the code. Cover components and responsibilities, how they interact, data and control flow, interfaces, storage and dependencies, and the reasons for key design decisions. Link to the relevant source files and update the document whenever follow-up implementation changes that architecture.

### Test phase

Delegate testing to a separate subagent using the saved requirements, test checklist, and delivery phase's exit check. The testing subagent records each test as `Pass`, `Fail`, or `Blocked` with evidence and reports defects without changing product code. The coordinating agent reviews the evidence, sends in-scope fixes back to the implementation subagent, and has the testing subagent rerun affected checks. Repeat until the completion conditions are met or a blocker requires user input.

Write an English report in `result/` listing the delivered functionality, test results, and any outstanding items. Prefix the delivery phase title with `done` only after the planned implementation is complete, every mandatory requirement and exit check has passed in the test phase, and the report is saved.

## Intended outcome

A learner asks why their free-fall answer was marked wrong. The tutor can see the relevant attempt, the selected passage, and the simulation values at the time of selection. Twenty turns later it can still explain which values produced 19.62 m. In a later lesson it can recall a recurring unit mistake, cite the evidence for that memory, and stop using it when the learner corrects or deletes it. The evaluation should show whether this improves independent problem solving enough to justify the added latency and tokens.

Plan for the existing Windows, local-first application. Start with one local learner per study-data directory and an explicit owner on every new learner record. Treat English and Vietnamese as presentation choices for that learner. A shared-device profile selector requires a separate ownership migration for existing courses and progress. All file names, tables, thresholds and interfaces described as additions below are proposed.

## Repository findings

| Current behavior | Implementation consequence |
| --- | --- |
| [FastAPI routes and persistence](backend/main.py) store confirmed roadmaps as JSON files and most other data as JSON values in the SQLite `records` table. Reading a lesson returns the document, attempts, notes, main chat and scroll position. | Extend the same database with versioned tables. Preserve roadmap files, stable topic IDs, the existing backup procedure and the shape of the reader bundle. |
| `thread()` sends the topic, all sections and illustration descriptions. A highlight adds a validated version, quote, offsets and optional simulation snapshot. `send()` holds a striped lock while calling the provider with the entire branch history, then rewrites the list. | Keep the branch as the unit of working memory. Assemble a smaller model input separately from the full transcript the learner sees. Move network work outside the lock with an explicit commit protocol. |
| The quiz route stores submitted answer, correctness and explanation per question. Motion playback stores parameters, points and a selected index. Drafting accepts level, goal and schedule, while confirming a roadmap persists the roadmap schema and generated IDs. | Use local grading as evidence. Preserve the difference between an explicit learner goal and a generated topic goal. Capture new preferences explicitly. Old attempts have list order but no reliable timestamps. |
| [Tutor logic](backend/ai.py) already runs two six-iteration loops. OpenAI replays role/text from previous messages and handles native function outputs and citation offsets. Codex receives history objects and requests schema-validated actions. Both use the [Python tools](backend/physics.py). | Share policy, budgets and result checks while retaining provider-specific wire formats. Existing traces are useful evidence, but the providers currently see different portions of them on later turns. |
| [Codex execution](backend/providers.py) uses an ephemeral subprocess and a 180-second timeout. OpenAI has a 90-second client timeout and one retry. OpenAI always advertises web search. The Codex loop can enable it after a model request. | A six-step cap alone does not bound wall time or the number of tools in a batch. Define a turn deadline and make the reader's search checkbox authoritative for both adapters. |
| [Reader and settings](src/main.tsx) expect chat POST to return the updated message array. Sources and Python traces render in the reader. [API types](src/types.ts) send the study language header. [Backend tests](tests/test_study.py) exercise provider routing, tools and branch isolation. [Browser tests](tests/browser.mjs) exercise the reader. | Preserve these contracts, including provider switching within a thread, linked sources, offline grading and separate progress for the two sample courses. Add fixtures for memory and failure paths. |

## Delivery sequence

| Phase | Deliverable | Dependency |
| --- | --- | --- |
| 0 | Baseline replay and measurements | Current application |
| 1 | Bounded working context and resumable summaries | Baseline fixtures |
| 2 | Evidence-backed learner memory with edit and forget controls | Ownership and turn identifiers |
| 3 | Embedding retrieval with metadata filters | Versioned learner memories and context budget |
| 4 | Tutor orchestrator with tool and specialist routing | Context builder, adapters and tool fixtures |
| 4A | Disposable local execution sandbox and isolation tests | Can prototype after phase 0, required before enabling executable tools |
| 4B | Python calculation and programming, optional Node.js | Shared loop and verified phase 4A runner |
| 4C | Choose a provider and model for illustration code | Existing provider settings and illustration contract |
| 5 | Paired evaluation, learning study and staged rollout | Feature switches and measurements from all phases |

### done — Phase 0 — Capture the baseline before changing prompts

1. Add an evaluation runner under `tests/evals/` using a fresh temporary `STUDY_DATA` per case, initialized before importing the backend. Seed a lesson, attempts, two highlight threads and a main thread through the same routes as the reader. Include both sample languages and a generated-course fixture with unrelated content.
2. Record the current inputs at the provider boundary, the final public reply, sources, tool results and elapsed time. Keep raw prompt snapshots confined to synthetic fixtures. Operational metrics should contain counts, durations, status and versions. Exclude learner text and provider settings from those metrics.
3. Capture baseline cases for a direct answer, unit conversion, simulation follow-up, search on/off, provider switch, long conversation and missing provider. Script both adapters for deterministic replay. Keep a separately invoked live-provider suite for answer quality and real latency.

**Exit check.** A clean checkout can replay both adapters without credentials, recover the expected calculation and distinguish the two branches. Save the fixture revision, model or stub name, prompt hashes and measurement method with each report. Capture existing search behavior as an observation so the intentional change in phase 4 is visible.

### done — Phase 1 — Build short-term memory for one branch

1. Introduce a context builder, for example `backend/tutor_context.py`, called by `send()`. Supply the current question, study language, lesson version, topic goal, relevant section, branch anchor and recent complete turns. Include relevant submitted quiz results and a compact simulation record with inputs, units and selected point. For a highlight question about “here”, prefer its captured snapshot even if playback has since moved. Record whether each value came from the anchor, current playback or a prior tool call. Keep hidden quiz answers out of the pre-attempt context.
2. Configure a model-specific input allowance. Subtract instruction and tool-schema overhead, reserved output tokens and a safety margin from the context window. Count the serialized request including provider wrappers. Use a conservative calibrated estimate when the tokenizer or CLI model limit is unknown. Record estimated versus reported usage separately. Reapply the check after every tool response.
3. Pack mandatory data first (instructions, question and necessary anchor evidence), then relevant recent turns and verified tool results, then summary, optional lesson detail and retrieved memories. Trim at section or completed-turn boundaries. Cap each tool payload. If the mandatory input alone exceeds the limit, return a localized request to shorten the question or selection. Preserve the student's original transcript.
4. Add a summary cache keyed by owner, roadmap, topic, lesson version and branch, with a covered-through message sequence and summary format version. Summarize only the older complete prefix when the next request would overflow. Retain unresolved questions, decisions and verified numerical results with units and source references. Merge only the new prefix on subsequent compactions. A failed summary call falls back to recent turns and deterministic evidence within budget. Include summary calls in latency and usage accounting.
5. Give each new send a client-generated request ID reused on retry. Under a short transaction, reserve the branch revision and request ID with an expiring lease. Run the provider outside the transaction. Commit the user/assistant pair and new revision atomically only if the reservation still matches. Replay a committed request, report an in-flight duplicate, and reject a conflicting send with a retryable localized response. A late result from an expired lease cannot append. Continue returning the full message array from both chat routes. Read old arrays with stable positional sequences until upgraded on write.

**Exit check.** Force a tiny context window over a long bilingual fixture. Every serialized request fits, the final answer can recover the earlier 2-second calculation, and neither a sibling highlight nor a newer slider position appears as its source. Reloading the UI shows the full history. Inject summary failure, duplicate sends and an expired reservation to verify fallback and exactly one committed reply.

### done — Phase 2 — Persist and maintain long-term learner memory

See the [Phase 2 architecture](documents/phase-2-architecture.md) and [verification report](result/phase-2.md).

Create additive SQLite migrations and apply each version transactionally before serving requests. Use the current data directory and backup path. Keep new writes independently switchable. Suggested logical records:

| Record | Required fields and invariant |
| --- | --- |
| Learner memory | ID, owner, kind (learned concept, recurring mistake, goal, preference), normalized concept key, statement, scope, language, status, confidence, revision and timestamps. A correction creates a newer revision for that memory. |
| Evidence | Memory ID, owner, source type, roadmap/topic/lesson version, optional branch, stable attempt or turn reference and observation time when known. Enforce a unique source key so retries count once. |
| Pending work | Unique source event, action, expected revision, retry state. Commit the source event and pending work in the same transaction. Finish extraction or indexing outside that transaction. |
| Suppression | Owner and minimal source/concept identifiers needed to prevent automatic re-extraction after forgetting. Keep forgotten text out of this record. Allow an explicit learner action to remember the fact again. |

1. Add a small memory repository, for example `backend/learner_memory.py`. Resolve the owner server-side. Store explicit goals and preferences from learner-confirmed input. Treat lesson generation and simply opening a lesson as insufficient evidence of mastery.
2. Begin with deterministic updates from grading and explicit learner edits. For an initial rule, two independently identified mistakes with the same well-defined cause can promote a recurring mistake. Deduplicate retries of one submission. An incorrect answer alone cannot distinguish arithmetic from a unit error. Use a diagnostic from the unit-aware grader where available, otherwise keep the observation unclassified. Later correct answers can weaken or resolve a misconception. Show tentative knowledge as tentative.
3. Default chat evidence to its branch. Promote a highlight-derived fact to broader learner scope only on explicit confirmation. Store the minimum fact needed, with a source link. If model-assisted extraction is added, validate candidate type and evidence reference before promotion and preserve a learner correction over subsequent automated updates.
4. Add owner-scoped list, create, edit and delete operations under `/api/memories`. Validate edits against the expected revision. In Settings add a bilingual memory view with source, scope, edit, forget and enable/disable controls. Explain what disabling does to future retrieval and capture. On forget, remove the text, embeddings and derived caches carrying the memory, cancel queued work and suppress re-extraction. Explain that a separately saved original chat or quiz attempt remains in study history.
5. Start collection prospectively. If importing old progress, offer an explicit, restartable import. Use roadmap/topic/question/list position as legacy evidence identity, keep unknown dates unknown and avoid inferring historical lesson versions that cannot be verified. Test migration against a populated copy with legacy records and restored backups.

**Exit check.** A repeated unit error can be inspected with its two evidence references after restart. A single wrong answer does not become a permanent misconception. Editing a preference wins over a stale extraction job. Forgetting it survives restart, import replay and a subsequent indexing retry. Offline quizzes still grade successfully while extraction is unavailable.

### Phase 3 — Retrieve relevant memories within the prompt budget

1. Introduce an embedding interface independent of the selected chat provider. Start with a locally installed bilingual embedding model and a per-owner SQLite vector table with memory ID, memory revision, encoder ID, dimension and vector. Select the encoder against the English/Vietnamese fixtures and measure its disk and latency cost on the target PC. Supply installation status in Settings. Codex-only and disconnected users must be able to study while the encoder is unavailable.
2. Index after a memory transaction commits. Upsert only if the source revision is still active. Replace superseded vectors, discard stale jobs, and rebuild on an encoder change using a versioned index. Switch reads after the replacement is ready. Check live memory status and ownership again when reading candidates.
3. Form the query from the question, topic and a bounded excerpt of the active anchor. Filter by owner, active status and allowed scope **before** similarity ranking. Support cross-language matches for learner-wide facts. Keep branch facts restricted to their exact branch and version. For a personal library, start with an exact cosine scan over filtered vectors. Benchmark the scan with growing libraries before adding another service.
4. Rank by semantic relevance, evidence quality and recency where dates are known. Deduplicate equivalent facts. Start with at most three memories and tune the similarity cutoff on a development set with irrelevant distractors and “retrieve nothing” cases. Fill only the optional memory allowance from phase 1. If embeddings fail, fall back to scoped exact concept matches or return no memories. Track fallback separately.
5. Pass selected items as contextual data with memory IDs and provenance. Keep teaching instructions separate from learner-authored text. Add a compact “Memories used” disclosure to replies with an edit/forget link. Store references that can be invalidated when a memory changes.

**Exit check.** A Vietnamese paraphrase can recover the appropriate English-language learner preference. An unrelated topic produces no match. Deleted, other-owner and sibling-highlight fixtures produce zero unauthorized matches, including during index rebuild and fallback. Report retrieval scores and latency on the held-out cases in phase 5.

### Phase 4 — Add a tutor orchestrator and unify the agent loop

Implement the shared turn policy in a small module such as `backend/tutor_agent.py`. Keep roadmap generation, lesson generation and illustration repair on their existing structured-generation paths.

| Stage | Implementation |
| --- | --- |
| Analyze and decide | Assemble the context once, snapshot provider/model settings and search permission for the turn, then request an answer or typed tool action. A direct answer can finish on the first call. |
| Select and execute | Adapt OpenAI native calls and Codex `TutorStep` to a shared action representation. Reuse `TOOLS`, `Motion`, `calculate` and `motion`. Validate names, arguments and limits before dispatch. Preserve OpenAI call IDs when sending results back. |
| Verify | Check finite results, expected fields and units. Require completed search and usable HTTP(S) sources when search was requested. Preserve OpenAI citation ranges and Codex end-of-answer links. Treat retrieved web text as source material. |
| Continue or answer | Append compact success or typed failure observations, recheck budget and request a follow-up decision. Bound repeated identical actions. Return the current message shape with sources and successful Python traces. |
| Stop | Start with the existing six model iterations plus a separate total tool-action cap of six, counting individual batch actions. Set a configurable monotonic end-to-end deadline. Charge summary calls, adapter setup, retries and tools to it. Give each blocking SDK/subprocess call only the remaining time and terminate expired subprocess work. Tune the deadline using observed p95 latency. |

#### Tool and specialist routing

Give the orchestrator a typed decision with four options: answer directly, ask a clarifying question, call a registered tool, or delegate to a registered specialist. The selected OpenAI or Codex adapter proposes the decision. The orchestrator validates it and owns dispatch, retries, and the final reply.

| Learner need | Route |
| --- | --- |
| An explanation supported by the lesson or a previous verified result | Answer directly using the current branch context. |
| A calculation or unit conversion supported by the calculator | Call the calculator with validated inputs. |
| Motion at a selected time | Call the motion tool with the relevant inputs, preferring the saved highlight snapshot when the learner refers to that selection. |
| An external source | Call the selected provider's search capability when the learner enabled it and policy permits it. |
| A worked physics explanation that combines an equation, assumptions, and a verified result | Delegate to a physics explanation specialist using the selected provider. Pass the question, relevant lesson excerpt, and verified result. The orchestrator validates the recommendation and writes the reply. |
| Missing information that prevents a reliable answer | Ask a focused clarifying question. |

Register each callable tool or specialist with a stable ID, input and output schemas, required permissions, and availability checks. Specialists receive only the context needed for the assigned task and return structured recommendations. Keep delegation one level deep. Charge each delegation and tool call to the same turn deadline and action budget. If a route is unavailable, use a permitted alternative when it can answer the question or return a localized explanation. Record the destination ID, decision reason category, result status, and elapsed time in operational metrics.

Make search-off authoritative at the adapter boundary. Remove web search from the OpenAI tool list for that turn and keep it disabled on every Codex subprocess. With search on, preserve the current expectation of a sourced answer. Handle invalid arguments with at most one corrected attempt inside the existing caps. Map provider unavailability, timeout, invalid tool output and missing required sources to localized recoverable outcomes. Record termination reason and step counts even when no assistant message commits. Preserve the reader's typed question on failure.

**Exit check.** Run the same scripted action sequences against both adapters. Cover answer-only, batch tool calls, invalid then corrected arguments, repeated calls, missing citations, search disabled, timeout and interrupted commit. Confirm identical policy decisions, bounded work and valid UI output. Verify that an explanation skips dispatch, a calculation reaches the calculator, a simulation uses the selected snapshot, and a worked physics explanation reaches the registered specialist with scoped inputs. Reject unknown targets and cover unavailable specialists and exhausted delegation budgets. Switch providers mid-thread and verify that the second provider can use the earlier verified result.

### Phase 4A — Confine model-directed work to a disposable VM

**Boundary.** Treat model output, submitted programs and program output as untrusted. The host application owns the UI, learner database and provider connection. It supplies a bounded copy of the question and selected inputs. Every model-selected computation, including the existing calculator and motion tools, executes in the guest. Ordinary quiz grading and learner-operated sliders can continue calling trusted application functions locally. The existing Codex temporary directory, read-only CLI mode and [browser illustration iframe](src/Lab.tsx) serve different purposes. None provides the execution boundary for tutor programs.

1. **Prototype the worker on Windows.** Use a dedicated Hyper-V Linux VM with a pinned base image and a disposable writable disk per job. Preinstall Python and the pinned numerical dependencies needed by the tools. Offer Node.js as an optional image variant. Before enabling execution, verify the host edition, virtualization support, image digest and runner health. On an unsupported PC, expose an unavailable status for code tools and retain offline lesson and quiz access. A host interpreter fallback would defeat confinement. [Microsoft Hyper-V prerequisites](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v)
2. **Restrict what the guest can reach.** Attach zero network adapters and zero host directory mounts. Disable device pass-through, file sharing, clipboard and unused integration services. Keep the repository, study database, API keys, Codex login, host environment and virtualization management interface outside the guest. Use a nonprivileged guest account and a fresh private scratch directory. The hypervisor, runner and host remain trusted dependencies. Maintain their updates and rerun isolation tests on each image or configuration change.
3. **Give the broker a narrow interface.** Add a backend sandbox client and a separately installed local runner. FastAPI keeps ordinary user privileges. Authenticate the client through an OS-access-controlled endpoint. The runner accepts a fixed job schema and manages only its own VMs. Prototype a host-initiated, bounded request/reply stream over a virtual serial channel. The broker assigns job IDs, selects the image and starts a fixed guest entry point. Only length-limited data frames cross the channel. Reject host paths, command lines, environment overrides and VM settings in requests. Treat guest replies as plain data with a strict size and schema limit.
4. **Close alternate action paths.** In confined tutor mode advertise only guest-backed tools. Disable provider-native search and hide the web-search checkbox in that mode. Model inference through the selected provider remains an explicit outbound host operation. Verify the actual Codex setup exposes only structured replies and no native file, shell, connector, network-search or other action capability. If that cannot be established for the installed version, mark Codex unavailable in confined mode. Enforce the same policy on retries and provider switches. Any other model entry point available in this mode must use the same capability restrictions.
5. **Bound and clean up every job.** Start with one active job per learner, a bounded global queue, one vCPU, 512 MiB guest RAM, 32 MiB scratch and 64 KiB combined output. Benchmark these starting values with each image. Give code ten seconds after guest readiness, with a separate startup cap and the overall phase 4 deadline. Enforce VM limits from the host and process/disk limits in the guest. On timeout, cancellation, output overflow or broker failure, stop the whole VM and discard its writable disk. On startup, reconcile orphaned jobs before accepting new work. Disable tools if isolation configuration or cleanup cannot be verified.

**Exit check.** Run integration tests on a virtualization-capable Windows machine with synthetic data. Verify that the guest can use its scratch directory, cannot see a host-only marker, receives no host environment secret, cannot connect to a host test listener or an external destination, and cannot see a marker from a previous job. Inspect VM configuration as well as the program-visible results. Exercise output overflow, timeout, broker restart and a missing VM runtime. Verify no surviving worker, retained scratch data or host execution fallback. Unit tests with a mocked runner cover routing only. Gate tool availability on the real isolation suite.

### Phase 4B — Teach the tutor to calculate and program inside the guest

| Tutor request | Tool and observable result |
| --- | --- |
| Calculate a value or simulate constant acceleration | Dispatch the existing calculator or motion action to the guest using the same validated inputs and Python functions as today. Compare results against the local grader fixtures. |
| Solve a multi-step problem, process a small dataset or run an example | Default to `run_python`. Supply source and bounded JSON input. A script may create temporary files and import preinstalled libraries. Return exit status, bounded stdout/stderr and an optional validated JSON result. |
| Demonstrate JavaScript or check Node-specific behavior | Offer `run_node` only when the optional image is healthy. Apply the same job contract, isolation policy, resource limits and trace format. |

1. Extend the tool definitions in [backend/ai.py](backend/ai.py), the Codex action schema and tutor prompts together. Resolve the executable from a fixed runtime enum inside the guest. Deliver code as file contents and data as JSON stdin. Package dependencies at image build time. Expose the runtime version and installed libraries so the tutor can choose a supported approach.
2. Bind each job to the owner, branch, turn request ID and action sequence on the server. Deduplicate dispatch after retries. Pass only the input required for that calculation. Keep each call independent. For a follow-up, pass the earlier bounded result as explicit input. Give the tutor typed outcomes for success, syntax/runtime error, timeout, output overflow and unavailable runtime. Allow one corrected program within the turn budget. Require successful execution evidence before the tutor claims a computed answer.
3. Extend [the chat types](src/types.ts) and [trace display](src/main.tsx) to show language, code, actual result, elapsed time and errors as escaped text in English and Vietnamese. Persist bounded traces in the thread. Give summaries the result, units and trace reference. Keep program output out of automatic long-term memory extraction unless supported by separate learner evidence.
4. Add paired adapter fixtures and real guest smoke tests. Have Python compute free-fall distance from supplied inputs and return 19.62 m. Have Node.js transform an input array and verify its exact JSON output. Include a syntax error followed by a successful correction, missing Node.js, duplicate delivery and a deadline reached during VM startup. Measure guest startup, execution time, peak memory and outputs truncated by policy separately from provider latency.

**Exit check.** Both eligible provider adapters can request the same guest-backed calculation and present its observed result. A programming error produces a visible failed trace. A disabled or unhealthy runtime yields a localized unavailable response. Roll out Python first, then enable Node.js after it passes the same real-VM checks.

### Phase 4C — Choose a provider and model for illustration code

1. Add a **Visualization coding** section in Settings with a provider selector and a model selector. Default to **Use the lesson provider** for existing installations. Offer supported OpenAI models, Codex CLI models, and Antigravity models through the local `agy` CLI when available. Persist the visualization selection independently so the tutor and lesson provider can stay on Codex while Antigravity writes the visualization code. Show provider readiness and provide a searchable model picker. When Codex or Antigravity is selected, populate the picker exclusively from the output of that provider's local model-list command. Verify the command and output format for each supported CLI version. Include only model IDs returned by a successful command. Exclude app-maintained lists, inferred IDs, manual entries, and fallback options. If discovery fails, leave the picker empty and show the error with a refresh action. Display provider-reported names and IDs, and filter by either field as the learner types. Refresh the catalog when Settings opens or the provider changes, and offer a manual refresh. Save the exact provider and model ID and pass that ID to the CLI on every visualization request. If the catalog cannot be loaded or a saved model disappears, show its status and prompt the learner to refresh or choose an available model.
2. Separate illustration planning from code generation when a dedicated visualization model is selected. The lesson provider produces the prose, quiz, and illustration brief. Pass the brief and browser runtime contract to the visualization provider, then validate the returned HTML, CSS, and JavaScript against the existing `Illustration` schema before saving the lesson. Keep the reader's lesson response shape and previously saved illustrations compatible. Use the same selected visualization provider for automatic and manual code repairs.
3. Verify the installed `agy` version supports non-interactive, bounded requests, explicit model selection where offered, and a way to keep file, shell, and connector capabilities outside the request. Use an isolated working directory, typed output validation, a timeout, and bounded output. Pass only the illustration brief and, for repairs, the relevant code and error. If the CLI is missing, signed out, or incompatible, show the reason and let the learner select a different provider. Require an explicit selection before switching providers after a failure.
4. Preserve the existing HTML filtering, sandboxed iframe, and JavaScript interpreter. Keep the lesson readable if the selected visualization provider fails. Apply a successful repair only after validation and retain the previous saved illustration if a repair fails.

**Exit check.** With Codex selected for lessons and Antigravity selected for visualization, generate a lesson and verify that only the illustration code request reaches Antigravity. Verify automatic and manual repairs use the same visualization selection and that it persists after restart. Verify each picker contains exactly the model IDs returned by its CLI command and can find them by name or ID. Test empty, failed, and malformed command output and confirm that none adds selectable entries. Change the model and confirm the next coding request passes the exact selected ID. Refresh a changed catalog and verify how the picker handles a removed saved model. Exercise missing CLI, unavailable model, timeout, and malformed output with scripted adapters. Verify the sandboxed rendering path and run a live smoke test with a compatible local `agy` installation before enabling Antigravity.

### Phase 5 — Evaluate quality, cost and learning impact

Hold the sandbox policy and runtime image constant across comparison arms. Report end-to-end programming task completion and isolation-suite results separately.

Use three replay arms with identical lesson snapshots, questions, model settings, search fixtures and grading rules. **A** supplies current question and required lesson/anchor only. **B** adds bounded branch history, tool observations and summaries. **C** adds persistent retrieval to B. Route all three through the same phase 4 engine to isolate the effect of memory. Keep the phase 0 behavior as a separate regression reference. Reset the data directory between arms and seed only evidence available before the question.

| Measure | How to compute and interpret it |
| --- | --- |
| Memory retrieval accuracy | Label relevant IDs and expected empty results per case. Report precision@3 and recall@3 on positive cases, false retrieval rate on empty cases, and scope violations separately. Split tuning and test sets by learner scenario. |
| Task completion | Predefine pass criteria per task, e.g. correct numeric value and unit, correct anchor snapshot or required citation. Count timeouts and errors in the denominator. Use a bilingual blind reviewer and a fixed rubric for explanatory quality. |
| Latency | Measure end-to-end p50/p95 per completed turn, timeout rate over all turns and time spent on retrieval, compaction, model and tools. Separate cold/warm encoder and provider/model runs. |
| Token usage | Sum input and output across every model call per attempted and successful task. Break out summary, retrieval overhead and retries. Report embedding usage separately. Label absent CLI usage as unavailable or estimated, alongside the estimator version. |
| Learning effectiveness | Compare first-attempt accuracy on a new matched problem and delayed retention on a second problem after a fixed interval, e.g. seven days. Record starting proficiency, sample size, attrition and uncertainty. A correct tutor answer alone supplies no learner outcome. |

1. Build a held-out suite covering bilingual paraphrases, ambiguous pronouns, stale goals, changed preferences, corrected misconceptions, empty retrieval, oversized context, branch isolation and timeouts. Include similar but wrong memories to test ranking. Version fixtures and rubrics. Repeat live trials and report paired per-scenario differences and uncertainty alongside aggregate rates.
2. For the learning pilot, assign consenting learners to memory-on/off arms with comparable starting proficiency and topic difficulty. Use unseen, independently answered problems and the same grading policy. If only the project owner participates, alternate matched topic sets, record the order and label the result a personal pilot. Report delayed-learning impact as pending until follow-up data exists.
3. Proposed initial release gates: zero scope violations, zero use of forgotten facts from the memory store, all requests within configured limits, all deterministic regression cases passing, and held-out recall@3 of at least 0.80 on labeled positive cases. Establish token and p95 latency ceilings for each provider from phase 0 measurements **before** comparing release candidates. Require task completion at least equal to B before enabling C by default. Interpret a small or inconclusive pilot as insufficient for a learning-benefit claim.

## Rollout and verification

Ship the runner and the Python/Node tool switches separately. A sandbox rollback must remove executable tools from both provider schemas and reject dispatch of in-flight actions. Keep confined-mode policy active during rollback.

Ship additive migrations first, then enable bounded context, memory capture, retrieval and the shared loop behind independent switches. Use synthetic data for shadow retrieval, then enable read/write memory for an opt-in local pilot. Keep the prior chat path callable during rollout. Run a migration and rollback rehearsal on a disposable populated data directory. Disable retrieval first if relevance deteriorates, disable capture if evidence is unreliable, and revert the loop independently for provider regressions. Enforce deletion and scope rules on every enabled path. Disable dependent features together when reverting their prerequisites.

Use these checks in the independent test phase. Cover each delivery phase's exit check in the Python suite and use the browser smoke test for highlight isolation, retry behavior, linked evidence, bilingual memory controls and persistence after reload where relevant. Use the repository's development commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
npm.cmd run build
npm.cmd run test:ui
```

**First implementation milestone:** deliver the phase 0 fixture and phase 1 context builder for the two-second free-fall follow-up. It gives the project a measurable improvement in conversation continuity and a repeatable test before introducing embeddings or changing provider orchestration.
