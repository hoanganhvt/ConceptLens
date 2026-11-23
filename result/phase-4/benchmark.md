# Phase 4 scripted chat benchmark

The [runner](code/benchmark.py) submitted 160 measured turns through `POST /api/chat` using disposable SQLite study data on Windows with Python 3.12.14. Bounded context was enabled in both implementations. OpenAI returned fixtures through an HTTPX mock transport and Codex returned equivalent JSONL through a subprocess stub. Every measured turn used a new branch. Each group had three warm-up turns followed by 20 measured turns.

The direct case took one model call and the calculation took two. The runner checked the expected text, the 19.62 calculation, and the expected routing mode at the provider boundary. Times are elapsed milliseconds from the local client POST to the response. The byte count sums the SDK request bodies or the Codex prompt and output schema across each turn. The p95 is the 19th value in each ordered group of 20.

| Provider | Scenario | Legacy p50 / p95 (ms) | Phase 4 p50 / p95 (ms) | Legacy → Phase 4 mean request bytes |
| --- | --- | ---: | ---: | ---: |
| OpenAI | Answer | 22.5 / 26.8 | 18.6 / 20.7 | 2,922 → 4,328 |
| OpenAI | Calculation | 26.5 / 29.6 | 25.8 / 28.7 | 6,087 → 9,041 |
| Codex | Answer | 19.6 / 21.4 | 27.2 / 38.0 | 3,972 → 5,441 |
| Codex | Calculation | 25.7 / 33.5 | 31.7 / 39.2 | 8,022 → 11,067 |

The run measures local application overhead with serialized fixtures. Sequential runs and the sample size limit timing comparisons. The new routing prompts, schemas and observations increased the measured request size in all four scenarios. Live network and model latency, token consumption, and search or specialist performance are outside these measurements. The deadline remains configurable pending live p95 measurements.

Reproduce from the project root using `.\.venv\Scripts\python.exe result/phase-4/code/benchmark.py --samples 20 --output result/phase-4/evidence/benchmark.json`. [Recorded summaries](evidence/benchmark.txt) · [Per-turn measurements](evidence/benchmark.json) · [Source manifest](evidence/manifest.json)
