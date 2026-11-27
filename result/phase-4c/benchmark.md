# Phase 4C scripted pipeline benchmark

The [runner](code/benchmark.py) exercises the production lesson, retry and repair route functions with scripted replies at the structured-generation boundary and a disposable SQLite database. Each scenario has three warm-up lessons followed by 20 measured lessons. Each lesson has two planned illustrations. The timed interval includes local storage and validation around the scripted responses. The 95th percentile is the 19th measurement in sorted order.

| Scenario | Operation | p50 (ms) | p95 (ms) |
| --- | --- | ---: | ---: |
| Both scenes succeed | Generate prose and two illustrations | 34.906 | 46.819 |
| Both scenes succeed | Manual repair | 14.600 | 19.427 |
| Second scene returns a scripted timeout | Generate prose and attempt two illustrations | 38.594 | 50.835 |
| Second scene returns a scripted timeout | Retry the second scene | 7.653 | 10.494 |
| Second scene returns a scripted timeout | Manual repair | 13.527 | 17.067 |

The runner asserts that each lesson makes one call for prose, one for the opening scene and one for repair in both scenarios. The timeout scenario makes exactly one additional call for the second scene. The injected timeout returns immediately, so the values measure application overhead and do not estimate actual wait times, token use or live provider latency. See the [per-run observations](evidence/benchmark.json) and [terminal summary](evidence/benchmark.txt).

Reproduce from the repository root with `..venvScriptspython.exe result/phase-4c/code/benchmark.py --samples 20 --output result/phase-4c/evidence/benchmark.json`.
