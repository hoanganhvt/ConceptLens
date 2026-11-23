# Phase 3 architecture

ConceptLens keeps learner memories in SQLite and uses an optional local encoder to rank them for tutor questions. Memory capture and retrieval share the existing learner control. Bounded tutor context must also be enabled for retrieval. The normal installation ships without encoder weights or optional runtime dependencies. With no approved manifest, the tutor answers using the existing lesson and branch context.

## Encoder and index

The [FastAPI lifespan](../backend/main.py) runs the index worker independently of quiz evidence processing. The [encoder process](../backend/embedding_process.py) loads local model and tokenizer files only from `STUDY_EMBEDDING_MODEL_DIR`. It checks the manifest, file paths, checksums and probe dimensions before accepting work. It exposes a single CPU inference slot. Each [inference adapter](../backend/embedding_cpu.py) applies the model-specific tokenization, pooling and normalization. Native runtime imports stay in the encoder child. The benchmark uses the same encoder adapter and its exploratory manifests stay unqualified. [Scientific benchmark](../result/phase-3/benchmark.md)

The [schema v3 migration](../backend/memory_retrieval.py) adds a vector table keyed by owner, encoder and memory ID, with the memory revision and dimensions stored alongside the float32 BLOB. An owner-scoped pointer identifies the ready index. Revision and delete triggers remove superseded vectors in the source transaction. The worker reads a bounded batch of committed memories, releases the transaction for inference, and checks that each revision is still live before storing its vector. The ready pointer changes after coverage, in the same transaction that retires the old vectors. During a rebuild the app returns an empty memory selection.

## Tutor request and replay

1. The chat route reserves the thread using the existing turn lease. It creates a query from the question, topic title and a bounded excerpt of the current lesson's active highlight.
2. Retrieval checks the learner setting, capture generation and ready encoder. It scopes candidates to the owner and current roadmap or learner-wide records, then checks status and live evidence. Exact cosine ranking runs on those candidates. It deduplicates matching statements and returns at most three items. Busy, failed and expired retrievals yield an empty selection.
3. [WorkingContext](../backend/tutor_context.py) fits items after existing context using the final request serializer of [each provider](../backend/ai.py). The tutor receives memory statements and supporting provenance as context. The context builder tracks the ID and revision of each item included in an outbound request.
4. If a sent reference is withdrawn, the turn returns a retryable conflict. The [turn commit](../backend/chat_state.py) verifies references using the transaction that saves the reply, turn lease and optional summary. The assistant message persists references alongside its existing fields. Conversation GET and POST continue to return the full transcript.
5. Before later calls or summarization, model history replaces assistant replies that used memory with a short placeholder and drops their associated traces. Sequence positions remain stable, including those used for summary checkpoints. The saved conversation remains readable in the reader.

## Reader interfaces

The `/api/memories` list and mutation response includes `encoder_status`. A revision-qualified `GET /api/memories/{id}?revision=N` resolves a current memory and its evidence links. The [reader disclosure](../src/MemorySettings.tsx) uses this lookup on expansion. For a valid revision it opens the matching entry in Settings and uses the existing attempt endpoint for the exact stored quiz evidence. After editing or forgetting, the reader refreshes open disclosures and shows obsolete revisions as unavailable. The memory toggle pauses capture and use while keeping management controls available.
