# ConceptLens

ConceptLens is a local-first personal AI tutor for Windows. Build a course, learn from illustrated lessons, try simulations, and ask focused questions without leaving the reader. Use the app in English or Vietnamese.

![ConceptLens showing the free-fall lesson, an interactive graph, and the right-side tutor panel on desktop](documents/screenshots/conceptlens.png)

*The built-in Free fall lesson at 2 seconds, with an example conversation in the tutor panel.*

## Quick start

Install Python 3.12 with the Windows `py` launcher and Node.js 22.12 or later with npm. From the project directory, run:

~~~powershell
.\start.cmd
~~~

Open [ConceptLens on localhost](http://127.0.0.1:8765/). The first run installs dependencies and builds the reader. Keep the terminal open while studying and press `Ctrl+C` to stop the server.

The built-in Free fall lesson works before you configure a provider. Set its time slider to **2 s**. With the default acceleration and initial velocity, the marble falls **19.62 m**. Enter `1962 cm` in the quiz to try grading with equivalent units.

## Verified features

The checks below use automated backend tests, browser tests, and scripted OpenAI and Codex responses. Live-provider answer quality and latency remain unmeasured in these reports.

| Feature | What the tests confirmed | Evidence |
| --- | --- | --- |
| **Roadmaps and lesson generation** | Draft and confirm a course, generate a lesson from a scripted response, and reopen the saved lesson. Invalid Codex lesson output triggers a retry. | [Backend tests](result/phase-3/evidence/verification-unit.txt) |
| **Interactive lessons and local grading** | The free-fall slider shows **19.62 m** at **2 s** with default settings. Playback and changes to initial conditions update the simulation. The quiz accepts `1962 cm`, rejects `19.62 s`, and keeps saved feedback after reload. Browser checks also covered LaTeX rendering and the illustration repair interface. | [Baseline replay](result/phase-0.md) · [Browser tests](result/phase-3/evidence/verification-browser.txt) |
| **Tutor threads and provider switching** | Reopen saved conversations, keep main and highlight threads separate, and retain the simulation values captured at selection. Scripted requests exercised calculations, source links, and switching between OpenAI and Codex within a thread. | [Baseline replay](result/phase-0.md) · [Browser tests](result/phase-3/evidence/verification-browser.txt) |
| **Provider settings** | The Codex provider and model selection survive a reload. On Windows, the settings API reports whether an OpenAI key is saved without returning the key. | [Browser checks](tests/browser.mjs) · [Test results](result/phase-3/evidence/verification-browser.txt) |
| **Bounded tutor context** | Long conversations stay within the configured request budget while retaining the original 19.62 m result and the full transcript in the reader. Retries preserve the draft and avoid duplicate replies. | [Phase 1 verification](result/phase-1.md) |
| **Local learner memory** | In **Settings → Learner memory**, save goals and preferences or track unit mistakes. Two distinct quiz questions in the same roadmap must support the same diagnosis before it becomes recurring. English and Vietnamese browser checks covered opting in, pausing, opening the original quiz answer, editing, and forgetting while preserving study history. | [Phase 2 verification](result/phase-2.md) |
| **Memory retrieval in the tutor** | Functional tests covered filtering by scope and revision, sending references through both adapters, and opening the exact supporting quiz attempt from **Memories used**. Editing or forgetting makes old references unavailable. | [Phase 3 verification](result/phase-3/document.md) |
| **Study-data migration and restore** | Upgrading and reopening populated databases preserved progress, roadmaps, chat, and summaries. A restored copy retained study history, and an injected migration failure rolled back. | [Phase 2 verification](result/phase-2.md) · [Phase 3 verification](result/phase-3/document.md) |

**Encoder release status.** No tested encoder met the recall threshold, and end-to-end latency and memory use are still unverified on the target two-core Windows machine with 4 GB RAM. The standard installation falls back to lesson and conversation context. Local learner memory works independently of the encoder. [Phase 3 benchmark](result/phase-3/benchmark.md)

## AI providers

Open **Settings**, select an **AI provider**, and save. That source handles roadmap drafts, lesson text, and tutor replies, including follow-ups in saved threads. Saved lessons, simulations, and quiz grading run locally.

Use **Illustration provider** and **Illustration model** to configure who builds and repairs illustrations. The illustration provider defaults to the lesson provider, and a blank illustration model uses the selected provider's general model. New lessons request the teaching text and scene plan first, then the illustrations.

| Provider | Setup |
| --- | --- |
| **OpenAI API** | Enter a key in Settings or set `OPENAI_API_KEY` before launch. A saved key takes precedence and Windows protects it with DPAPI. Set `OPENAI_MODEL` before launch to override the default `gpt-4.1`. |
| **Codex CLI** | Install the CLI on the server's `PATH`. Run `codex login` and check `codex login status` in the same Windows account and terminal that starts ConceptLens. Choose a model in Settings or use the CLI default. |
| **Google Gemini API** | Save a Gemini API key from Google AI Studio in Settings or set `GEMINI_API_KEY` or `GOOGLE_API_KEY` before launch. After saving a key, reopen Settings and use **Load Gemini models**. The default Gemini model is `gemini-3.6-flash`; use `GEMINI_MODEL` or the per-source model field to override it. |
| **Google Antigravity CLI (agy)** | Put `agy` on the server's `PATH` and run it in a terminal to sign in. Use **Load agy models** or paste a model slug from `agy models`. ConceptLens submits one structured prompt at a time from a temporary workspace. |

Tutor web search is available with OpenAI and Codex CLI. The Gemini and agy tutor flows can still use ConceptLens's local calculator and physics simulation.

### Tutor context and learner memory

To enable bounded tutor context, set `STUDY_BOUNDED_CONTEXT=1` before launching. This mode packs the current question, relevant lesson and highlight evidence, recent turns, and a summary of older turns into a configurable input budget. The reader keeps the full transcript. Set `STUDY_TUTOR_CONTEXT_WINDOW` for a common window or `STUDY_TUTOR_MODEL_WINDOWS` for model-specific overrides. [Phase 1 architecture](documents/phase-1-architecture.md) · [Verification](result/phase-1.md)

Learner memory is off by default. Once enabled in Settings, quiz evidence is processed locally without provider calls. [Learner memory architecture](documents/phase-2-architecture.md)

Tutor retrieval requires bounded context and an approved local encoder package configured through `STUDY_EMBEDDING_MODEL_DIR` before launch. Settings shows encoder readiness. [Retrieval architecture](documents/phase-3-architecture.md)

When retrieval is ready, ConceptLens ranks memories locally and may send up to three relevant memory statements and source details to the selected AI provider. Expand **Memories used** below a tutor reply to open the referenced memory and any supporting quiz attempts. After you edit or forget a memory, the old reference is shown as unavailable.

## Data and backups

| Location | Contents |
| --- | --- |
| `data/<roadmap-id>/roadmap.json` | Confirmed roadmaps with stable topic IDs. |
| `data/study.sqlite` | Generated lessons, quiz attempts, highlights, tutor threads and summaries, reading position, motion state, provider settings, and learner memory. |

Stop the server and copy the entire `data` directory to back up your study history. Restore it to the study-data location before relaunching. Set `STUDY_DATA` before launch to use a different directory. A saved API key is tied to the Windows user who saved it.

The backend sends the relevant context to the provider when you request AI help. Web lookups use the tutor's search option.

## Development and verification

The reader uses React, TypeScript, and KaTeX. FastAPI handles routes and SQLite storage, and Pint checks units. Generated visuals run in a sandboxed iframe. See the [lesson prompt](prompts/lessons/generate.md), [illustration contract](prompts/illustrations/contract.md), and [tutor instructions](prompts/tutor/instructions.md) to change teaching behavior.

Run these commands from the project directory after setup:

~~~powershell
npm.cmd run build
.\.venv\Scripts\python.exe -m unittest discover -s tests
npm.cmd run test:ui
.\.venv\Scripts\python.exe tests/evals/runner.py --output "$env:TEMP\conceptlens-evals"
.\.venv\Scripts\python.exe tests/evals/runner.py --bounded --output "$env:TEMP\conceptlens-evals"
~~~

The browser test uses an isolated study-data directory and requires Chrome or Chromium. Set `CHROME_PATH` if the browser is installed in a custom location. The replay commands use scripted providers and run without credentials.

Rebuild after frontend changes and restart the server after backend changes. If port 8765 is occupied, check whether ConceptLens is already running there.
