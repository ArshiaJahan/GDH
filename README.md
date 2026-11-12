<div align="center">

<img src="src-tauri/icons/128x128@2x.png" width="110" alt="GameDevWorkstation icon">

# GameDevWorkstation

**A local AI agent workstation for solo Unity developers, on your Mac.**

[![macOS](https://img.shields.io/badge/macOS-13%2B%20·%20Apple%20Silicon-000000?logo=apple&logoColor=white)](#quick-start)
[![Unity](https://img.shields.io/badge/Unity-6-222222?logo=unity&logoColor=white)](#built-for-unity)
[![Version](https://img.shields.io/badge/version-0.4.0-4c1)](VERSION)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
<br>
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](frontend/package.json)
[![Tauri](https://img.shields.io/badge/Tauri-v2-24C8DB?logo=tauri&logoColor=white)](src-tauri/Cargo.toml)

[Highlights](#highlights) ·
[Built for Unity](#built-for-unity) ·
[How it works](#how-it-works) ·
[Security](#security-model) ·
[Quick start](#quick-start) ·
[Roadmap](#roadmap) ·
[Full guide](docs/GUIDE.md)

</div>

---

Coding agents are good at writing C#; they are bad at knowing when a game change is actually
*done*. GameDevWorkstation is a desktop app (called **Workspace** in the code) that puts Claude
in charge as the orchestrator, hands units of work to Claude and OpenAI (Codex) subagents in
parallel, and drives the Unity Editor through MCP. The harness, not the model, decides
when a turn may end: it enforces compile and test gates, asks for fresh evidence before a story
is marked done, and keeps your project's taste and past mistakes in front of the agent.
Everything runs locally; the backend listens on `127.0.0.1` only.

## Highlights

| | |
|---|---|
| **Orchestrator + subagents** | Claude plans the job and delegates units to Claude and OpenAI subagents (API or Codex CLI), choosing model tier and effort per unit, with parallel git worktrees for code. |
| **Unity skill pack** | 16 Unity 6 skills behind a router: compile/fix loops, Play Mode verification, headless builds, safe scene/prefab edits, perf and game-feel passes, shipping. |
| **Unity MCP built in** | The MCP for Unity server is preconfigured and turns on automatically when you invoke a Unity skill. |
| **Hooks and gates** | A hooks engine runs checks at fixed points of a turn: compile before finishing, tests in verify phases, blocked edits to generated files. |
| **Quality ladder L1-L4** | Stories reach `done` only with fresh, app-observed evidence: compile, tests, play evidence and screenshots, design critique. |
| **Taste and scars** | `TASTE.md`, `POSTMORTEMS.md` and an anti-pattern ratchet keep design judgement and past failures in the loop. |
| **Fleet** | Parallel waves of subagents in their own worktrees, each with a claimed scope, scope-checked merges, a conflict circuit breaker and discoveries relayed to the next wave. |
| **Progressive skill disclosure** | A compact skill index in the system prompt; full skill text is loaded only when used and survives compaction. |
| **Cost control** | Daily and per-session spend limits, job budgets, approval for high effort, and a My usage page per model. |
| **ElevenLabs** | Speech, transcription, sound effects and music, in chat and on their own page. |
| **Native shell, local updates** | Tauri v2 app with a frozen FastAPI backend, keys in the macOS Keychain and in-app updates from a local folder. |

## Built for Unity

### The skill pack

`unity-router` is the entry point: it picks which skills a task needs (at most a few at a time)
and whether to work through the Editor (MCP) or batchmode.

| Skill | Purpose |
|---|---|
| [`unity-router`](skills/unity-router/SKILL.md) | Routes a task to the right Unity skills; ships the Unity gates preset |
| [`compile-fix-loop`](skills/compile-fix-loop) | Compile, read the console, fix, repeat, with stop conditions |
| [`play-verify`](skills/play-verify) | Play Mode checks with `[VERIFY]` signals, screenshots and scripted input |
| [`headless-ops`](skills/headless-ops) | Batchmode compile, tests and builds when the Editor is closed |
| [`scene-prefab-safety`](skills/scene-prefab-safety) | Safe scene and prefab edits |
| [`gdd-to-backlog`](skills/gdd-to-backlog) | Turns a GDD into a linted `BACKLOG.md` with acceptance criteria |
| [`project-memory`](skills/project-memory) | `PROJECT.md`: ADRs, conventions, gotchas, current milestone |
| [`architecture-patterns`](skills/architecture-patterns) | Architecture templates for Unity code |
| [`asset-pipeline`](skills/asset-pipeline) | Import settings and asset workflows |
| [`perf-pass`](skills/perf-pass) | Profiling plus the static anti-pattern audit |
| [`game-feel-pass`](skills/game-feel-pass) | Juice and feedback tuning |
| [`build-ship`](skills/build-ship) | Builds and release prep |
| [`vcs-hygiene`](skills/vcs-hygiene) | Git hygiene for Unity projects |
| [`unity-mcp-orchestrator`](skills/unity-mcp-orchestrator) | MCP for Unity tool reference and workflows |
| [`design-critique`](skills/design-critique) | L4 review by three independent reviewers against `TASTE.md` |
| [`postmortem`](skills/postmortem) | Writes `POSTMORTEMS.md` entries and proposes how to enforce the lesson |

General skills ship too: `delegation` (on by default), `game-designer`, `graphify`, `grill-me`,
`claude-handoff` and two Claude delegation strategies.

### Unity MCP

The built-in `unity` server runs [MCP for Unity](https://github.com/CoplayDev/unity-mcp) 10.3
through `uvx`. Install the `com.coplaydev.unity-mcp` package in your project and open the Editor;
invoking any Unity skill turns the server on for that session. With the Editor closed, the gates
and `headless-ops` fall back to batchmode.

### Quality ladder

A level passes only on evidence that is **observed** by the app itself (an agent's report never
counts), **fresh** (newer than the last change to the files it depends on) and **bound** to a
`BACKLOG.md` story or acceptance criterion.

| Level | Passes when | Observed from |
|---|---|---|
| **L1** Compile | The newest compile is newer than the newest code change, with 0 errors | Unity log / console, compile gate |
| **L2** Behaviour | Each EditMode/PlayMode criterion's tests passed after the last content change | NUnit XML, MCP `run_tests` |
| **L3** Play evidence | Play-verify criteria passed on a fresh log; visual stories have a fresh screenshot | `check_criteria`, screenshots on disk |
| **L4** Critique | `critique()` passed, or you accepted it on the escalation card | Three reviewer subagents |

Flipping a story to `done` in `BACKLOG.md` without the evidence it needs is denied (fail closed).

### Gates

The Unity gates preset ([`skills/unity-router/hooks.toml`](skills/unity-router/hooks.toml)) is
off per project until you accept a one-time offer, which consents to exactly the tools and
commands it runs:

- **block-generated**: edits to `Library/`, `Temp/`, `*.csproj` and other generated files are refused.
- **cs-compile** (L1): a turn that changed code can't finish until the project compiles, with up to 2 fix attempts before it's handed to you.
- **merge-compile**: a worktree merge that brought code is compiled.
- **verify-tests** (L2): EditMode tests in a campaign's verify phase.
- **antipatterns**: an advisory scan of changed scripts.
- **backlog-lint**: lint errors after `BACKLOG.md` is written.

Your own hook files (`.workspace/hooks.toml`) are ignored until you trust them by hash. A
tool-failure breaker stops a turn that keeps hitting the same error.

### Anti-pattern ratchet

[`unity_antipatterns.py`](skills/perf-pass/scripts/unity_antipatterns.py) (stdlib-only Python)
traces hot methods (`Update`, `FixedUpdate`, `On*Stay*` and what they call) and flags
`GetComponent`, `Find*`, `Camera.main`, LINQ, string and collection allocations, `Debug.Log`,
missing event unsubscribes and more, with a weighted score. A baseline in
`.workspace/antipatterns-baseline.json` means only *new* findings count.

### Taste, critique and postmortems

- **`TASTE.md`**: three words, ranked heuristics, anti-patterns and hard constraints for your game.
- **`design-critique`**: Spec Auditor, Player Advocate and Art Director review fresh screenshots; the minimum score counts, two rounds at most, then you decide.
- **`POSTMORTEMS.md`**: each rule has an `Applies to:` glob, and the rule is shown to the agent the first time it touches a matching file in a session.

## How it works

```mermaid
flowchart LR
    UI["React UI"] --> Shell["Tauri v2 shell"]
    Shell -->|"starts, token"| API["FastAPI backend<br/>127.0.0.1"]
    UI <-->|"REST + WebSocket events"| API
    API --> Loop["Agent loop<br/>Claude orchestrator"]
    Loop --> Hooks["Hooks, gates<br/>quality ladder"]
    Loop --> Subs["Subagents<br/>Claude / OpenAI / Codex CLI"]
    Loop --> MCP["MCP servers"]
    Loop --> EL["ElevenLabs"]
    Subs --> WT["Git worktrees"]
    MCP --> Unity["Unity Editor<br/>MCP for Unity"]
    Hooks --> Unity
    API --> DB[("SQLite + FTS5")]
```

The Tauri shell starts the frozen backend on a random port with a random token and shows the UI.
The backend runs the agent loop, subagents, MCP servers and gates; every change is published on
an event bus and streamed to the window over a WebSocket, which replays what it missed after a
reconnect. Config and data live under `~/Library/Application Support/Workspace/`, logs under
`~/Library/Logs/Workspace/`.

## Security model

- **Approvals and allowlist.** Shell commands, deletes, edits in Ask mode, non-read-only MCP tools
  and effort above high show an approval card. Allowlist rules (`run_command:git status*`) never
  match command lines with `;`, `|`, `$(…)` and similar.
- **Modes.** Plan only, Ask and Accept edits; in Plan only no rule lets an edit or command through.
- **Untrusted content.** Web, MCP, subagent and Unity console output reaches the model inside
  randomly tagged `<untrusted-…>` blocks, marked as data, never instructions.
- **Secrets.** API keys and secret-looking MCP env vars and headers live in the macOS Keychain;
  the UI shows only the last four characters.
- **Isolation.** Hook files need trust by hash; the app's own git calls disable repository hooks;
  `web_fetch` refuses private and local addresses.

## Quick start

**Prerequisites:** macOS 13+ on Apple Silicon, Xcode Command Line Tools, Node 20+,
[uv](https://docs.astral.sh/uv/) (Python 3.11+), Rust stable (for the desktop app), and
optionally the Codex CLI (`npm i -g @openai/codex`).

```bash
git clone https://github.com/ArshiaJahan/GameDevWorkstation.git
cd GameDevWorkstation
make dev        # build the UI, start the backend on 127.0.0.1:8765, open it in your browser
```

Add keys in **Settings → Accounts** (Anthropic required; OpenAI and ElevenLabs optional). To
click around without keys, run with `WORKSPACE_FAKE_PROVIDERS=1`.

| Command | What it does |
|---|---|
| `make dev` | Build the UI and run the backend in your browser |
| `make backend` + `make ui` | Backend plus hot-reloading UI on :5173 |
| `make live` | The desktop window from this checkout, with UI hot reload |
| `make app` | Build `dist/Workspace.app` and `dist/Workspace.dmg` (ad-hoc signed) |
| `make install` | Copy the built app to `/Applications` |
| `make release` | Bump the version and publish to the local updates folder |
| `make test` | Backend tests, UI type check and UI tests |

**For Unity:** install `com.coplaydev.unity-mcp` in your project, run
`uvx --from mcpforunityserver==10.3.0 mcp-for-unity` once while online to cache the server, open
the Editor, and invoke `unity-router` from the composer's skill button or with `/skill unity-router`.

### Configuration

Defaults ship with the app; [`config.example.toml`](config.example.toml) lists them with
comments. Your `config.toml` holds only what you change, and most of it is editable in Settings:
model tiers, delegation budgets, spend limits, modes and allowlist, `[skills]`, `[hooks]` and
`[ladder]`. See the [guide](docs/GUIDE.md#configuration).

## Roadmap

Coming next:

- **Campaigns and chains**: multi-session goals with a plan, phases, a decision log and exit
  evidence, so work survives across sessions with autopilot and budget limits.

<details>
<summary><b>Project layout</b></summary>

```
backend/workspace/      FastAPI backend
  agent/                agent loop and context
  providers/            Anthropic, OpenAI and ElevenLabs adapters
  features/             subagents, worktrees, MCP, hooks, ladder, unity_bridge, updates, ...
frontend/src/           React UI (Vite)
src-tauri/              Tauri v2 desktop shell
skills/                 built-in skills (Unity pack, delegation, design tools)
scripts/                build, release, version and dev scripts
packaging/              PyInstaller packaging
tests/                  backend tests (pytest)
docs/GUIDE.md           the full manual
config.example.toml     default configuration with comments
```

</details>

<details>
<summary><b>Development and testing</b></summary>

```bash
uv run pytest -q                          # backend tests; no network
cd frontend && npx tsc -b && npx vitest run   # UI type check and tests
make test                                 # both of the above
make test-live                            # real API smoke tests (skipped without keys)
make app-test                             # build, launch and check the app
```

The unit tests run against recorded provider fixtures and fakes (a fake `codex` binary, a fake
Unity bridge), so they need no keys. Live API paths have not yet been exercised end to end;
`make test-live` and `make app-test` are the first runs against real APIs.

Contributions are welcome: open an issue to discuss a change, keep pull requests focused, and
run `make test` before submitting.

</details>

## Documentation

The [full guide](docs/GUIDE.md) covers every page and panel, sessions, keyboard shortcuts,
delegation rules, MCP and skills, building the app, versions and updates, where data lives, and
troubleshooting.

## Acknowledgements

- The campaign file sections, exit-evidence table, discovery records, scope claims, lifecycle hook
  ideas and postmortem format are adapted from [Citadel](https://github.com/SethGammon/Citadel)
  by Seth Gammon (MIT). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Unity Editor control uses [MCP for Unity](https://github.com/CoplayDev/unity-mcp) by Coplay.
- Built with [Tauri](https://tauri.app), [FastAPI](https://fastapi.tiangolo.com),
  [React](https://react.dev) and [Vite](https://vite.dev).

## License

[MIT](LICENSE) © 2026 ArshiaJahan
