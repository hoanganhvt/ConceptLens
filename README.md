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

## What you can do

- **Plan a course.** Draft a roadmap from a subject, learning goal, level, and schedule. Review and revise the draft before confirming it. Create a new version when you want to revise a confirmed roadmap.
- **Explore illustrated lessons.** Generate and reopen lessons with worked examples, interactive visuals, and quizzes. The lesson prompt asks for at least two illustrated examples per concept. Move through an event with a slider, or use the motion lab's playback, initial conditions, and position and velocity graphs. Lesson, quiz, and tutor formulas render as LaTeX.
- **Ask the tutor.** Open the collapsible panel on the right. Each new question starts a thread, and the current lesson's saved questions reopen with their full conversations. Select a passage or illustration caption to create a separate highlight thread. A simulation highlight keeps the values shown when you selected it. The tutor is prompted to give a short, direct answer in plain words. It can run Python calculations and simulations, and return source links for web lookups.
- **Check your understanding.** Answer choice questions or submit a number with units. Grading and feedback work locally, and the app saves quiz attempts, reading position, and motion settings.
- **Manage learner memory.** In **Settings**, turn capture on to save goals and preferences and track recurring unit mistakes. Two distinct quiz questions in the same roadmap must support the same unit diagnosis before it becomes recurring. Inspect the original answers, edit or forget a memory, and pause capture while keeping saved memories available for review. Forgetting a memory leaves the original quiz and chat history available.

## AI providers

Open **Settings**, select a provider, and save. The selection applies to the next generation or tutor request, including follow-ups in saved threads. Roadmap drafting, lesson generation, illustration repair, and tutor replies use the chosen provider. Saved lessons, simulations, and quiz grading run locally.

| Provider | Setup |
| --- | --- |
| **OpenAI API** | Enter a key in Settings or set `OPENAI_API_KEY` before launch. A saved key takes precedence and Windows protects it with DPAPI. Set `OPENAI_MODEL` before launch to override the default `gpt-4.1`. |
| **Codex CLI** | Install the CLI on the server's `PATH`. Run `codex login` and check `codex login status` in the same Windows account and terminal that starts ConceptLens. Choose a model in Settings or use the CLI default. |

### Tutor context and learner memory

To enable bounded tutor context, set `STUDY_BOUNDED_CONTEXT=1` before launching. This mode packs the current question, relevant lesson and highlight evidence, recent turns, and a summary of older turns into a configurable input budget. The reader keeps the full transcript. Set `STUDY_TUTOR_CONTEXT_WINDOW` for a common window or `STUDY_TUTOR_MODEL_WINDOWS` for model-specific overrides. [Phase 1 architecture](documents/phase-1-architecture.md) · [Verification](result/phase-1.md)

Learner memory capture is off by default and is enabled separately in Settings. The local memory worker processes quiz evidence without provider calls. Tutor replies currently use the active lesson and conversation branch. [Phase 2 architecture](documents/phase-2-architecture.md) · [Verification](result/phase-2.md)

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

The browser test uses an isolated study-data directory and requires Chrome or Chromium. Set `CHROME_PATH` if the browser is installed in a custom location. The replay commands use scripted providers and run without credentials. [Baseline verification](result/phase-0.md)

Rebuild after frontend changes and restart the server after backend changes. If port 8765 is occupied, check whether ConceptLens is already running there.
