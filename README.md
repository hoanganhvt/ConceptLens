# ConceptLens

ConceptLens is a personal AI tutor for learning. It runs on your Windows PC and opens in a browser. Start with a question, work through a short illustrated lesson, and check your reasoning with a quiz or a Python simulation. The built-in free-fall lesson works before you connect an AI provider.

## Quick start on Windows

Install Python 3.12 with the Windows `py` launcher and Node.js 22.12 or later with npm. Open PowerShell in the project directory and run:

```powershell
.\start.cmd
```

On first launch, the script creates a Python virtual environment, installs dependencies, builds the frontend, and starts FastAPI on the loopback interface. The first installation requires internet access. Open [ConceptLens on localhost](http://127.0.0.1:8765/). Keep the terminal open while studying and press `Ctrl+C` to stop the server.

Choose **English** or **Tiếng Việt** in the header. ConceptLens remembers the language in this browser and uses it for new roadmaps, lessons, and tutor replies. Each language has its own free-fall sample and progress. Saved custom courses stay in their original language.

**Try the sample.** In the free-fall lesson, set the time to 2 seconds. With zero initial velocity and an acceleration of 9.81 m/s², the object has fallen 19.62 m. Try entering `1962 cm` in the quiz. Python checks both the value and its unit.

## Connect an AI provider

Open **Settings** in the upper-right corner, choose an AI source, and save. Your selection applies to the next AI request, including questions in an existing highlight conversation.

| Source | Setup | Model selection |
| --- | --- | --- |
| OpenAI API | Enter an API key in Settings, or set `OPENAI_API_KEY` in the environment that starts the backend. A saved key takes precedence. Windows encrypts saved keys for the current user with DPAPI. | Set `OPENAI_MODEL` before starting the backend. The default is `gpt-4.1`. Choose a model that supports structured output, function calls, and web search. |
| Codex CLI | Install the CLI on the backend's `PATH`. Run `codex login` from the same Windows account that runs ConceptLens, then verify with `codex login status`. | Pick a model in Settings or keep the CLI default. ConceptLens reads the CLI model catalog and passes an explicit selection to `codex exec --model`. |

The Codex integration uses non-interactive execution with `--ephemeral`, `--ignore-user-config`, and `--output-schema`. Generating roadmaps, lessons, illustrations, repairs, or tutor replies requires a working provider connection. The saved lesson, simulation controls, and quiz grading run locally.

## Study workflow

1. **Plan a course.** Enter a subject, current level, goal, and available study time. Review the proposed chapters, request changes, then confirm the roadmap. To revise a confirmed course, create a new version.
2. **Open a lesson.** The tutor generates the explanation, worked example, interactive illustrations, and quiz together. Reopening a saved lesson loads the same material.
3. **Explore the illustration.** Predict what will happen, adjust a control, and compare the result with your prediction. The motion lab lets you vary acceleration, initial velocity, and duration, then inspect position and velocity over time.
4. **Ask about a passage.** Select text in a lesson paragraph or illustration caption to open a separate conversation. A selection on a simulation caption captures the simulation values at that moment. Click the highlight later to continue the same thread.
5. **Check your understanding.** Submit a choice or a numerical answer with units to see feedback. In tutor chat, ask for a calculation or enable web search to get linked sources.

## Data and backups

| Location | Contents |
| --- | --- |
| `data/<roadmap-id>/roadmap.json` | A confirmed roadmap with stable topic IDs. Each version has its own directory. |
| `data/study.sqlite` | Generated lessons and illustrations, quiz attempts, highlights, chat threads, reading positions, simulation state, and provider settings. |

To back up your work, stop the server and copy the entire `data` directory. To restore it, place the copy in the data location before starting ConceptLens. Set `STUDY_DATA` before launch to choose a different directory. A saved API key is tied to its Windows user context and may need to be entered again after a restore.

Content is stored locally. For an AI request, the backend sends the relevant learning context and conversation to the selected provider. Highlight threads have their own history. The web-search option also requests online sources.

## Development

| Path | Responsibility |
| --- | --- |
| [src/](src/) | React and TypeScript reader, quizzes, settings, highlight conversations, and simulation controls |
| [backend/](backend/) | FastAPI routes, SQLite persistence, AI providers, numerical tools, and unit-aware grading |
| [prompts/](prompts/) | English instructions for roadmaps, lessons, illustrations, tutoring, tools, and provider context |
| [tests/](tests/) | Python regression tests and a Playwright browser smoke test |

**Edit teaching behavior.** Start with [the lesson prompt](prompts/lessons/generate.md) for writing style or [the illustration contract](prompts/illustrations/contract.md) for visual behavior. Prompt files use UTF-8 and are read at request time. Edits apply to newly generated content. Learner-facing text is Vietnamese.

**Work on illustrations.** Each visual contains filtered HTML or SVG, limited CSS, and an ES5 `render(t,s,v,k)` function. The browser runs it with JS-Interpreter inside a sandboxed iframe. The drawing can use `text(id,value)` and `attr(id,name,value)`. For motion lessons, Python computes the time series shared by the drawing and the chart. If rendering fails, the app attempts one automatic repair and offers a manual retry alongside the written explanation.

**Build and test.** From the project directory after setup, run:

```powershell
npm.cmd run build
.\.venv\Scripts\python.exe -m unittest discover -s tests
npm.cmd run test:ui
```

The build type-checks the frontend and writes the static site to `dist/`. Rebuild after frontend changes and restart the server after Python changes. The browser test starts an isolated backend with temporary study data and requires Chrome or Chromium. Set `CHROME_PATH` to the browser executable if it is installed in a custom location. The tests do not require a paid model call.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Port 8765 is in use | Open the local URL first. An instance may already be running. Stop that instance before starting another on the same port. |
| The CLI says you are signed in, but Settings says you are signed out | Start `start.cmd` in the same Windows account and terminal environment where `codex login status` succeeds. Check `CODEX_HOME` if you use a custom CLI profile directory. |
| A frontend change is missing | Run `npm.cmd run build` and refresh the browser. The launcher reuses an existing build. |
| An API key or model change is missing | Save changes made in Settings. For changes made to environment variables, restart the backend from the terminal containing the new values. |

