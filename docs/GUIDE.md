# GameDevWorkstation: the full guide

> The complete manual for GameDevWorkstation. For the overview,
> see the [README](../README.md).

A personal agent workstation for your Mac. Claude is the main agent: it plans jobs and hands
units of work to Claude and OpenAI (Codex) subagents in parallel, picking the model tier and
thinking effort per unit to keep things fast and cheap. ElevenLabs handles speech,
transcription, sound and music. Everything runs locally; the backend listens on 127.0.0.1 only.

## Contents

- [All features](#all-features)
- [Prerequisites](#prerequisites)
- [Setup and development](#setup-and-development)
- [Adding API keys](#adding-api-keys)
- [Configuration](#configuration)
- [Pages and panels](#pages-and-panels) (and [Gallery](#gallery))
- [Task board](#task-board)
- [Campaigns and workflows](#campaigns-and-workflows)
- [Sessions](#sessions)
- [Claude Code sessions](#claude-code-sessions)
- [Prompt improver](#prompt-improver)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [How delegation works](#how-delegation-works)
- [Built-in skills](#built-in-skills) (and [Record and replay](#record-and-replay), [Unity: MCP or CLI](#unity-mcp-or-cli))
- [CI failure triage](#ci-failure-triage)
- [Eval Forge](#eval-forge)
- [Agent Review Desk](#agent-review-desk)
- [ComfyPlug (ComfyUI generation)](#comfyplug-comfyui-generation)
- [Building the app](#building-the-app)
- [Versions & updates](#versions--updates)
- [Upgrading from Workspace 0.4](#upgrading-from-workspace-04) <!-- rename:keep -->
- [Testing](#testing)
- [Where things live](#where-things-live)
- [Notes and differences from the original spec](#notes-and-differences-from-the-original-spec)
- [Troubleshooting](#troubleshooting)

## All features

Every feature at a glance; the sections below have the details. The README lists the top eight.

| | |
|---|---|
| **Orchestrator + subagents** | Claude plans the job and delegates units to Claude and OpenAI subagents (API or Codex CLI), choosing model tier and effort per unit, with parallel git worktrees for code. |
| **Unity skill pack** | 18 Unity 6 skills behind a router: compile/fix loops, Play Mode verification, record and replay, headless builds, safe scene/prefab edits, perf and game-feel passes, trailers, shipping. |
| **Unity: MCP or CLI** | Drive Unity through MCP for Unity or the official Unity CLI (live Editor via `com.unity.pipeline`, or batch when it's closed), switchable per project and session, with a status chip and one `unity` tool for the agent. |
| **Hooks and gates** | A hooks engine runs checks at fixed points of a turn: compile before finishing, tests in verify phases, blocked edits to generated files. |
| **Quality ladder L1-L4** | Stories reach `done` only with fresh, app-observed evidence: compile, tests, play evidence and screenshots, design critique. |
| **Taste and scars** | `TASTE.md`, `POSTMORTEMS.md` and an anti-pattern ratchet keep design judgement and past failures in the loop. |
| **Campaigns and workflows** | Multi-session goals with a plan you approve, phases whose checks the app evaluates itself, a campaign file in the project (decisions, discoveries, handoffs), checkpoints, autopilot with budget and stall breakers; or a one-session workflow with `/workflow`. 9 Unity templates ship, including a trailer workflow. |
| **Fleet** | Parallel waves of subagents in their own worktrees, each with a claimed scope, scope-checked merges, a conflict circuit breaker and discoveries relayed to the next wave. |
| **Progressive skill disclosure** | A compact skill index in the system prompt; full skill text is loaded only when used and survives compaction. |
| **Prompt improver (game dev)** | On by default. When a game-dev request in a Unity session is unclear, it checks your project first, then asks up to 3 grounded questions with recommended options, and drafts a task card (goal, acceptance, quality level, route). A Backlog task is created automatically only after you answer a question; start a message with `*` to skip the improver for that turn. |
| **Task board** | A Kanban board (Tasks tab) you and the agent share: tasks with codes like `Task00001`, subtasks and checklists, comments, history and linked sessions, live updates. In chat: `/task new`, `/task <code>`, `/task move`, `/task done`, `/task list`, `/task link`; the agent uses `task_*` tools. Scheduled prompts live on the Schedule page. |
| **New session screen** | "What should we work on?": type a task, pick **Chat only** or a **Folder** (or a recent one), the Claude model, effort and mode, and send. New sessions from this screen use your Claude subscription; scheduled tasks, campaigns, fleet and subagents keep the built-in loop. Existing sessions keep their harness. |
| **Claude Code sessions** | Run your own `claude` CLI and login (checked against claude 2.1.308 on a claude.ai subscription), with GDW tools, approvals, Plan mode and `--resume`. Subscription estimates stay outside spend limits; API key logins record `billing='api'` and check spend limits before each turn. See [Claude Code sessions](docs/GUIDE.md#claude-code-sessions). |
| **CI failure triage** | `gdw triage <run-id\|log>` sorts a failed CI run's failures into compile, test, flaky, infra, dependency and timeout, and names the file and line. It reads GitHub Actions, pytest, vitest, tsc, cargo, npm and uv logs, plus Unity Editor.log and NUnit XML. Rules come first, and a model handles only what the rules can't place. A GitHub Action posts the report on failed PRs. On 26 labelled failed logs the rules got 24/26 categories right before tuning and 26/26 after. See [CI failure triage](docs/GUIDE.md#ci-failure-triage). |
| **Eval Forge** | `gdw eval forge <commit>` turns a merged commit or PR into an agent task: the start state, a leak-filtered prompt and the commit's tests as hidden graders, plus differential, Unity (EditMode tests, scene asserts, replay hashes) and rubric graders. `gdw eval validate` checks each grader: the reference must pass and generated flawed solutions (mutants, partial fixes, test tampering) must fail. `gdw eval run` runs Claude Code, Codex and the built-in agent for pass@k, cost, time and tool calls, and blames each failure on the agent, the environment or the grader. Tasks export to the Harbor / Terminal-Bench 2.0 format. On the 13-task seed suite every reference passes and 111 of 168 flawed solutions are caught. A first Claude Code run (Opus 5.5, k=3, 2026-11-20) scored 28% pass@1 and 31% pass@3, and its failures exposed three under-specified tasks, now fixed or dropped. See [Eval Forge](docs/GUIDE.md#eval-forge). |
| **Agent Review Desk** | Review an Eval Forge trial like a teammate's PR: the agent's steps (Claude Code or Codex log), its diff and the hidden-test results side by side. Score it on a rubric (correctness, maintainability, test quality, 1-5), tag a failure mode from a fixed taxonomy, prefer one trial over another, and export a labelled JSONL dataset of reviews and chosen/rejected preference pairs. An optional model pre-review proposes a verdict, and `gdw review agreement` measures how often it matches the human. See [Agent Review Desk](#agent-review-desk). |
| **Cost control** | Daily and per-session spend limits, job budgets, approval for high effort, and a My usage page per model. |
| **Trailer maker** | Brief → beat sheet → scripted Play Mode capture (Unity Recorder) → ffmpeg edit from a JSON edit list → ElevenLabs music cut to the beat sheet → three reviewers → Steam, YouTube and vertical exports. |
| **Record and replay** | Record instrumented Unity sessions in the open Editor, replay them with frame-by-frame checkpoint verification (SHA-256 state hashes), and export silent gameplay GIF/MP4. Input System only; the guarantee is same-environment repeatability for the state you register, and a mismatch is reported, not refused. |
| **ElevenLabs** | Speech, transcription, sound effects and music (including composition plans with exact section lengths), in chat and on their own page. |
| **ComfyPlug** | Images, image edits, 3D models (GLB), sound and any other ComfyUI workflow, video included, on your own ComfyUI (this machine or another one). The agent's `comfyplug` tool saves each output as an item and looks at the images; `gdw comfyplug` is the same from a terminal. See [ComfyPlug](#comfyplug-comfyui-generation). |
| **Native shell, local updates** | Tauri v2 app with a frozen FastAPI backend, keys in the macOS Keychain and in-app updates from GitHub Releases or a local folder. |

## Prerequisites

| Tool | Why | Install |
|---|---|---|
| macOS 13+ on Apple Silicon | target platform (built for an M4 Air) | |
| Xcode Command Line Tools | compiler, `codesign`, `git` | `xcode-select --install` |
| Rust (stable) | builds the desktop shell (Tauri v2) | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Node 20+ | builds the UI | `brew install node` |
| uv | Python 3.11+ backend | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Codex CLI (optional) | `codex.cli` subagents and the Codex CLI harness | `npm i -g @openai/codex` |
| Claude Code (optional) | [Claude Code sessions](#claude-code-sessions) on your own Claude subscription | see code.claude.com, then `claude auth login` |
| ffmpeg (optional) | the `trailer-maker` skill's edit, exports and checks (run as an external program, never bundled) | `brew install ffmpeg` |

`make app` checks all of these first and prints exactly what is missing.

## Setup and development

```bash
make frontend          # build the UI once (frontend/dist)
uv run gamedevworkstation       # backend on 127.0.0.1:8765, opens the UI in your browser
```

`uv run gamedevworkstation` prints a link with a one-time session token; the UI keeps the token out of
the address bar after it loads. For UI work with hot reload, run `make backend` in one terminal
and `make ui` in another, then open the link printed by the backend but on port 5173.

Without keys you can still click around: set `GDW_FAKE_PROVIDERS=1` to use an echo
model that makes no API calls.

## Adding API keys

Open **Settings → Accounts** and paste each key. Keys go to the macOS Keychain (service
`GameDevWorkstation`), never to the config file or logs; the UI only ever shows the last four
characters. You can add several profiles per provider (for example `work` and `personal`).
Each session picks one profile per provider in the **Environment** card (Accounts row), and
everything the session runs uses it: the main agent, Claude and OpenAI subagents, Codex CLI
units and the Codex CLI harness (`CODEX_API_KEY`), the Agent SDK harness, `web_search`,
Compact and the ElevenLabs tools. New sessions start on each provider's default profile, the
first one listed. In Settings → Accounts you can add a profile (the key can come later), make
one the default, or delete one. Deleting a profile also deletes its Keychain key; a provider
always keeps at least one profile, and sessions that used a deleted profile switch to the
default. The ElevenLabs page has its own profile picker when there is more than one.

In development you can use environment variables instead: `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, or `GDW_KEY_<PROVIDER>_<PROFILE>` for other
profiles.

After saving or removing a key, **My usage** re-runs that provider's auth checks so you can see
its status at once.

## Configuration

The defaults ship with the app ([`config.example.toml`](../config.example.toml) has them with
comments). `~/Library/Application Support/GameDevWorkstation/config.toml` holds only what you change, so
later changes to the defaults (tiers, prices, delegation) reach you; most of it is editable in
Settings. Older versions copied every default into that file: the first start of this version keeps
only the values that differ (the full copy stays as `config.toml.pre-overrides.bak`, which is
never overwritten). Every save is atomic and keeps the previous file as `config.toml.bak`. If the
file can't be read (bad TOML or an invalid model, tier or account entry), the app starts with the
defaults, keeps the file as `config.toml.broken-<time>` and says so in a banner. In the plain
sections (`[orchestrator]`, `[delegation]`, `[assistant]`, `[limits]`, `[elevenlabs]`, `[modes]`,
`[data_policy]`, `[appearance]`, `[updates]`, `[sessions]`) a value must have the type of its
default: numbers must be numbers and not negative (`"32000"` is read as 32000), switches `true` or
`false`, and so on. A value that doesn't fit is ignored (its default is used), the file is left as
it is, and a banner lists the keys to fix; Settings refuses such values with an error.
Most of it is editable in Settings, where every field saves itself (menus and checkboxes at once,
numbers and allowlist rules a moment after you stop typing) and shows **Saved ✓** beside it. API keys
keep an explicit **Save**.

- `[orchestrator]` default model and effort for new sessions, and the tool output cap
  (`tool_output_chars`, 30,000; `tool_output_images`, 4). A longer result reaches the model cut, with
  the full text saved as an item it can page through with `read_output(id, offset)`.
- `[accounts]` key profiles per provider.
- `[tiers]` what `claude.fast / standard / deep` and `codex.fast / standard / deep / computer / cli` mean. Defaults:

  | Tier | Model | Shown as |
  | --- | --- | --- |
  | `claude.fast` | `claude-haiku-5-5` | Haiku 5.5 · claude.fast |
  | `claude.standard` | `claude-sonnet-5-5` | Sonnet 5.5 · claude.standard |
  | `claude.deep` | `claude-opus-5-5` | Opus 5.5 · claude.deep |
  | `codex.fast` | `gpt-6.1-sol` | GPT-6.1 Sol · codex.fast |
  | `codex.standard` | `gpt-6.1-sol` | GPT-6.1 Sol · codex.standard |
  | `codex.deep` | `gpt-6.2-sol` | GPT-6.2 Sol · codex.deep |
  | `codex.computer` | `gpt-6.1-terra` | GPT-6.1 Terra · codex.computer |
  | `codex.cli` | `gpt-6.1-sol` (passed to `codex exec`) | GPT-6.1 Sol · codex.cli |

  OpenAI rule: fast and standard handle regular coding (fast is for quick mechanical work);
  deep handles complex coding and design; computer handles computer use, screenshots and visual checks.
  The tier keys keep their names (the delegation skill routes by them); the `codex.*` tiers run
  GPT-6 models because OpenAI retired its `*-codex` API models.
- `[delegation]` `max_parallel` (4 Claude+Codex API subagents and 2 Codex CLI runs by default,
  sized for a fanless Air), `confirm_over_usd`, `job_budget_usd`, per-subagent spend cap and
  max turns.
- `[assistant]` model, effort (up to high), max turns and spend cap for the Skills & MCP
  assistant boxes.
- `[limits]` daily and per-session spend limits. Hitting the daily limit pauses all agents and
  shows a one-line banner at the top of the window with today's spend; hitting the session limit
  pauses that session and shows the banner on its chat (the ⓘ button has the details). The daily
  pause lifts by itself at local midnight or when you raise the limit; **Resume today** (or
  **Resume this session**) allows another limit's worth of spend.
- `[elevenlabs]` default voice, model, output format, `confirm_over_characters`.
- `[modes]` default mode and the approval allowlist (`run_command:git status*`, `edit:*`,
  `mcp:github__get_*` for MCP tools and `shared_tool:laptop__*` for shared ones, as
  `<server>__<tool>`, …). A `run_command` rule covers one simple command: a command line with any of
  `;` `&` `|` `$` `(` `)` `<` `>`, a backtick or a line break always asks, so `git status*` can't
  approve `git status; curl … | sh`. Only the exact rule `run_command:*` allows every command. A rule
  with an empty pattern (`run_command:` or a bare `edit`) covers nothing. In Plan only mode no rule
  lets an edit, delete, merge or command through.
- `[campaigns]` campaigns and workflows: `handoff` (`per_phase`: each phase in a new session;
  `on_cost`: stay in the session until a request reaches `rollover_input_tokens`),
  `max_auto_turns` and `stall_turns` (autopilot), `default_budget_usd`, `max_sessions`,
  `validator_tier` (the plan check), `drift_tier` (the check every 2 phases) and `claim_stale_s`.
  See [Campaigns and workflows](#campaigns-and-workflows).
- `[fleet]` parallel waves: `enabled`, `max_units` (writing units per wave), `unit_timeout_min`
  (`build`, `research`) and `relay_tokens` (discoveries passed to the next wave).
- `[sessions]` `auto_title` (name new sessions after the first reply, default on), `trash_days`
  (sessions in Trash are deleted for good after this many days, default 30),
  `event_retention_days` (how long the event log keeps events, default 7; see Settings → Storage)
  and `default_harness` (the harness of every new session, also `POST /api/sessions` without one:
  `claude_code`, your Claude subscription through your own `claude` CLI; or `builtin`, `agent_sdk`,
  `codex_cli`). Scheduled tasks, campaigns, fleet and subagents keep the harness they always used.
- `[mcp.presets.<key>]` built-in MCP servers (name, transport, command, args, description) added
  once to Skills & MCP; `[skills.mcp_on_invoke]` maps a skill to the MCP servers that invoking it
  turns on for the session (every Unity skill → `unity`).
- `[unity]` the Unity backend (`backend = "auto" | "mcp" | "cli"`, see
  [Unity: MCP or CLI](#unity-mcp-or-cli)), `auto_live_order`, `cli_path` (empty: find the Unity
  CLI), `editor_path` / `editor_root`, `pipeline_version` (what "Install Pipeline package" pins),
  the Unity job timeouts (`live_timeout_s`, `live_test_timeout_s`, `batch_timeout_s`,
  `test_timeout_s`, `build_timeout_s`), `nographics`, `extra_editor_args` and `eval` (`ask` | `off`), `harness_scripts` (`ask` | `never`),
  `harness_git_exclude` (default `true`) and `clone_when_open` (`ask` | `never` | `always`).
  Settings → Unity edits it.
- `[claude_code]` [Claude Code sessions](#claude-code-sessions): `cli_path` (empty: find `claude`),
  `load_user_mcp` (default `false`), `setting_sources` (default `""`: none), `pre_tool_hook`
  (default `true`), `max_processes` (default 4) and `interrupt_wait_s` (default 5). Settings →
  Claude Code edits it.
- `[data_policy]` which providers may receive files you mark sensitive.
- `[models."…"]` the model catalog: prices per million tokens, context windows, accepted effort
  levels, how each model expresses "no thinking", and a `display_name` (Opus 5.5, Sonnet 5.5,
  Haiku 5.5, Fable 5.1, GPT-6 Astra, GPT-6.1 Sol, GPT-6.1 Terra, GPT-6 Luna). The app shows
  models by that name plus the tier routing to them, e.g. "GPT-6.1 Sol · codex.standard", in
  Settings, the side panel, subagent cards, My usage, Schedule, `/model`, approvals, background
  tasks and Artifacts. Entries without `display_name` (older config files, custom models) get a
  name derived from the ID. Model IDs and prices were checked against provider docs on
  2026-11-05 and again on 2026-11-06.

## Pages and panels

**Sidebar.** Your sessions: pinned ones, then groups, then the rest, with search over titles and
message text. See [Sessions](#sessions). The footer has Archived and Trash, then one row of icon
buttons (names in their tooltips) for Artifacts, ElevenLabs, Tasks (the task board), Schedule,
Campaigns, Skills & MCP, My usage,
Settings and the theme switch (system / light / dark). The list fades out at the bottom while
there's more to scroll.

**Chat.** Streaming replies with collapsible thinking and tool calls, subagent cards (tier,
effort meter, status, tokens, cost, stop), inline players for ElevenLabs audio, and drag and
drop attachments. Slash commands are `/model`, `/effort`, `/mode`, `/compact`, `/clear`,
`/skill`, `/task` (see [Task board](#task-board)) and, in built-in loop sessions with an API key, `/workflow` (see
[Campaigns and workflows](#campaigns-and-workflows)). A task code such as `Task00012` in a message
(yours or the agent's) shows as a chip that opens the task; the chat header shows the tasks
linked to the session.
**Approval cards** appear here for effort above high (Approve / Run at high instead / Cancel),
shell commands, edits in Ask mode, deletes, large ElevenLabs generations, shared-tool jobs and MCP
tools that aren't read-only (see [MCP tools and modes](#how-delegation-works)).
For the main agent above high the card estimates the extra cost and time per turn: this
session's average output tokens and latency per turn (normalised to high; 2,000 tokens and 30 s
with no history) × 1 more for xhigh or 3 more for max, at the model's output price.
**Stop** cancels the main agent and everything this session started: subagents, Codex CLI runs
(their whole process group), agent commands (background ones too) and open approval cards.
Other sessions keep running. On a rate limit the main agent retries with backoff (2 s doubling
to 60 s, 5 retries, or the provider's retry-after) and shows "Rate limited, retrying in Ns".
A failed turn shows as an alert row; the message is stored with `meta.error = true` and
`meta.error_kind` (`error`, `budget`, `harness`, …). Your own messages render `inline code`,
**bold**, *italic* and fenced code blocks.
A reply cut off at the output limit, or a turn that reaches 60 model calls, ends with a note and
a **Continue** button; notes are never sent to the model. Long chats open on their newest 150
messages and load older ones as you scroll up; compacted messages are hidden behind "N earlier
messages compacted · show". Images are checked when attached: HEIC and other formats the
providers don't take are converted to JPEG, photos over 3.75 MB are shrunk and images over
2000 px on the longer side are resized (macOS `sips`; Anthropic rejects larger ones in requests
with more than 20 images), keeping the original as the item. Images in tool results (screenshots)
and older attachments are checked the same way on every request. An image that's later deleted or
unreadable is replaced by a short note in the request instead of failing every turn, and if a
provider still rejects an image's size, the turn retries once with that image left out (a note
in the chat says so). If the live connection drops or falls
behind, the app shows "Reconnecting…", replays what it missed, or reloads its state when it
missed too much.

**Session tabs**, above the chat when a session is open. The tab you pick is remembered per
session (Chat is the default), and Chat stays loaded while you look at another tab, so its
scroll position and your unsent draft are still there when you come back. Arrow keys, Home and
End move between the tabs.

1. **Chat** — the conversation.
2. **Subagents** — every subagent this session started, newest first, updating live. Each row
   shows the name, tier and model, effort, status (queued, running, done, failed or cancelled),
   elapsed time, tokens and cost, and a **Stop** button while it runs. Click a row to see its
   brief, its result (or error) and its worktree path. The tab's badge counts the ones running.
3. **Gallery** — the session's whole gallery as a grid of thumbnails, with the screenshot box
   (see [Gallery](#gallery)). The tab shows how many items there are.

**Side panel**, per session, in this order. Until you show or hide it yourself, it's open in
windows at least 1200 px wide and closed in narrower ones:

1. **Environment** — where it runs (Local), folder, model and effort, account profile per provider,
   mode, and the session's harness (read-only: new sessions run Claude Code; older sessions keep
   the harness they were made with).
2. **Context** — tokens by system, tools, skills, messages and attachments, as a share of the
   window, plus this session's cost per model. **Compact** summarizes older turns with
   `claude.fast` at low effort (the last 3 turns, or inside one long turn the last 4 tool
   exchanges, stay as they are); the originals stay in history. The summarizer sees the start
   of the conversation (the goal) and its end when the middle is too long. The card warns at 70%
   and 90% full. Before each model call the main agent estimates how full the request is
   (calibrated by the last real request) and at 80% compacts by itself; if it still doesn't
   fit, the oldest tool output is left out of that request with a note. A provider "prompt too
   long" error or a reply cut off by the window compacts and retries once.
3. **Connectors** — MCP servers and skills for this session: the skills it uses, each with a
   remove button, and **Add skill…** with a filter. MCP servers are checkboxes; with more than
   six, the card lists the ones that are on and offers **Add server…** the same way.
4. **Shared tools** — let the session use MCP servers from other machines. This is off by
   default, every job asks first, and it can only be changed while the session is idle.
5. **Outputs** — what this session produced, with a link to the Artifacts page.
6. **Changes** — changed files (git diff in a repo, including subagent worktrees; snapshots
   otherwise), +/− counts, side-by-side diff and per-file revert. Files over 5 MB aren't
   snapshotted: they're listed as "too large to snapshot", without diff or revert. Each subagent worktree has
   **Discard worktree** (removes it and its `gdw/<unit>` branch; asks again, saying what
   would be lost, when it holds work that isn't merged).
7. **Background tasks** — subagents, commands, Codex CLI runs and ElevenLabs jobs with a log
   tail and cancel.

### Gallery

The **Gallery** tab sits at the top of the session, next to **Chat** and **Subagents**. It shows what
the session *generated* (media items from the agent, its tools and commands that announce
`ARTIFACT:` / `TRAILER_OUTPUT:` lines; your own attachments are left out) as a grid, newest first,
with every item shown. Click an image or a video to open it larger, with its prompt, how it was captured
and **Open in Finder**. Videos and audio show a play badge.

Images a tool generates (ComfyPlug, screenshots, MCP tools) also appear in the **Chat** itself, inline
at the tool call that made them. A reply (everything the agent does between two of your messages) that
produced images ends with a row of small thumbnails of all its images, in order. Click an inline image or a
thumbnail to open the same preview; with several images, Left / Right (or the arrows) step through them and
Escape closes it.

**Take a screenshot.** Type what the picture should show in the box ("player at the cave entrance,
night, low angle") and press **Take screenshot** (or Enter). A spinner card appears right away and says
whether the shot is still being framed or has been captured. Behind it, a short side agent
(`[unity] screenshot_tier`, Sonnet by default, effort low, `screenshot_max_turns` = 12 turns) finds the
subject, frames the shot and captures it. It only has the read-only file tools, a scene-file reader and a
screenshot-only Unity tool. It never edits project source files or saves a scene, and it can't move anything in your
scene. Captures use a temporary camera that is removed again, or render an existing camera as it is.
If it started Play Mode, the app attempts to stop it afterwards; exiting Play Mode is best effort.
Approval depends on the route: MCP uses an **MCP tool** card; live captures with framing use an
**eval** card showing the temporary-camera code; batch and plain live captures use a **Unity screenshot**
card with **Always allow `screenshot` in this project**. Plan only mode refuses screenshots, including
further captures and play calls if you switch modes during a request. Screenshots only write into
`<project>/Logs/harness/screenshots/` (Unity's default `.gitignore` already ignores `Logs/`), and the
gallery entry keeps your prompt as its caption, the route and the camera it used.

How each route captures:

| Route | Capture |
|---|---|
| MCP for Unity | Requires `manage_camera`: `action=screenshot` (Game view), a named camera or a temporary camera at a position and rotation (or aimed at an object) that the tool removes again. Uses the MCP tool approval card |
| Unity CLI, live Editor | the Pipeline `screenshot` command (the Game view as it is); with framing, an `eval` of a fixed snippet that renders a hidden temporary camera and destroys it (the eval card shows the code) |
| Unity CLI batch / unity.sh (Editor closed) | `unity.sh screenshot` → `HarnessCli.Screenshot` (harness scripts version 3): opens the scene without saving it, renders a temporary camera (or a named one) to a PNG, exits. Always with a graphics device, never `-nographics` |

**Batch limits.** With the Editor closed the agent can't look at the scene. It reads the saved `.unity`
file instead (cameras, lights and objects with their world positions) and picks an existing camera or a
position plus a look-at target from it. So only saved changes are in the picture. Lighting and time of
day aren't changed (the request's time of day is recorded, not applied). The default scene is the first
enabled scene in the build list. Text serialization (Unity's default) is needed to read the scene. Older
harness scripts (version 2) have no screenshot entry point: the entry fails with **Install harness editor
scripts** as the fix. With the Editor open but no live route, the shot runs on a copy of the project
when `clone_when_open` isn't `"never"` (unsaved changes not included); otherwise the entry fails with
the reason and the chip's actions (install the Pipeline package, close the Editor).

**Terminal** (⌘J). Shell tabs run your login zsh in the session folder. Agent commands stream
into their own read-only tabs.

**Artifacts.** Switch between All, Claude, OpenAI and ElevenLabs. The tabs are Artifacts (with
version history), Media, Files and Links, grouped by session. You can open each item (HTML
renders in a sandboxed frame), jump to its message, download it, reveal it in Finder, copy its
path, send it to the chat or a subagent, mark it sensitive or delete it. Copying to Downloads never
overwrites: a second copy becomes `name (2).ext`. **⌘K** searches titles, file names, links,
transcripts and the text of PDFs and Word, PowerPoint and Excel files. You can scope a search to
the current tab, all chats or selected chats, and filter it by kind, provider, model, source and date.
A subagent reads what you send only while it runs. Pick a finished one (or a Codex CLI run,
which takes no messages) and the app says so and offers to **Run a follow-up** (it asks the
orchestrator: it posts "Follow up on subagent … with item …" to that session and starts the main
agent) or to **Send to chat** (the session's composer) instead.

**ElevenLabs.** This page has:

- a quota bar
- text to speech, with voice previews, sliders and a character and credit estimate
- speech to text, with upload or record, speaker labels and a click-to-seek transcript
- sound effects and music, with variations
- voice changer
- voices: your own and the shared library, with favorites
- history of every generation

Sections your plan can't use are hidden. Voice design and cloning link to ElevenLabs' own
consent and verification flow.

The agent's `music` tool takes either a prompt with a length or a **composition plan**: sections
(`{"chunks": [{"text": "[Build] rising synths", "duration_ms": 25000, "positive_styles": [...],
"negative_styles": [...]}]}`, 3–120 s each, 10 minutes in total) whose lengths `music_v2_5` keeps exactly, plus an
optional `seed`. The trailer maker uses it to cut music to a beat sheet. The confirm card estimates music at about
1,500 credits per minute of summed section length. Rough budget for a 60 s trailer: about 1 minute of music (plus
an alternate or two), a few VO lines, and around 10 sound effects at about 40 credits per second.

**Tasks.** The Kanban task board you and the agent share; see [Task board](#task-board).

**Schedule.** Scheduled prompts (cron or presets); this page was called Tasks before the task
board arrived. Each run starts a new session with its own
model, effort, folder and mode. Schedules only fire while the app is running. Cron lines use
standard weekday numbers (0 and 7 are Sunday, `1-5` is Monday to Friday) and day names
(`mon-fri`); custom lines also accept `once:2026-12-01T09:00` and `every:30m`.

**Skills & MCP.** Enable skills globally, use one in chat, view or edit `SKILL.md`, and create
new skills (see [Built-in skills](#built-in-skills)). The editor (Monaco, loaded on first use)
checks the frontmatter as you type: YAML errors, a `name` that is lowercase letters, digits and
dashes and matches the skill's folder, and a `description` of at most 1024 characters. **⌘S**
saves, and closing or reloading with unsaved changes asks first. The skill's other files
(`references/`, `scripts/`, `templates/`) are listed beside it. Built-in skills open read-only;
**Customize** copies the skill with its files to your skills folder, where your copy takes
precedence and can be edited. Add or edit
MCP servers (stdio command or HTTP URL), test them, see their tools and set defaults. Env vars
and headers whose names look secret (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*_PAT`,
`*AUTH*` such as `Authorization`) are stored in the Keychain (service `GameDevWorkstation`, account
`mcp:<server>:<NAME>`, headers `mcp:<server>:header:<Name>`), not in SQLite. The page shows them as
`••••last4`; leave that as is when editing to keep the value, or type a new one. Removing a server
deletes its entries, and rows saved by older versions are moved to the Keychain at startup. With
`GDW_NO_KEYCHAIN=1` (development) they stay in SQLite and the log warns.

Built-in servers (`[mcp.presets.*]` in config; today `unity`, MCP for Unity) are added once at
startup, off by default for sessions, and carry a **Built-in** badge with a note on what they need.
If their command isn't installed the row says how to fix it. Edit one and **Reset to default**
puts it back; remove one and it isn't added again (Reset via `POST /api/mcp/servers/<name>/reset`
restores it). A server of yours that already has a preset's name is never touched.

The skills list has a filter field, and long descriptions show two lines with **More**. Each
section starts with an assistant box. Describe what you need ("a skill that turns meeting
notes into action items", "tools to query my Postgres database"), press **Find or create**
(skills) or **Find and add** (MCP), and a small agent (`[assistant]` in config: Haiku 5.5 at
high effort, 20 turns, $0.50 cap per request) does one of three things:

- installs an existing one from a trusted source. A URL you give, or an official or well-known
  repo. GitHub blob/tree links work. It fetches `SKILL.md` and the files it links to in the
  same folder, size-capped.
- searches the web for one (`web_search` / `web_fetch`) and installs the best match.
- writes a new skill with valid frontmatter. For MCP it never invents packages: it says when
  nothing trustworthy exists.

Its steps show live in the box, and you can cancel it there or under Background tasks. When
it finishes, the box shows a short summary with buttons to open the new skill or server. Rules
the backend enforces:

- It never replaces an existing skill or server unless your request names it.
- Adding an MCP server always shows an approval card in the box first, with the exact command
  or URL. It prefers `npx -y <package>` and `uvx <package>`.
- Installing a skill from a URL shows an approval card first, with the source URL, the first 200
  lines of its `SKILL.md` and the linked files it would save. Declining saves nothing. A skill the
  assistant writes itself gets the same card (it may have read web pages while writing it); its
  subject is `written by the assistant: <name>`, so only `skill_install:*` skips it.
- It never stores secrets. Env vars that look like keys or tokens are refused, and it tells you
  which variable to add yourself.
- Its usage shows in My usage under role `assistant` (feature `skill_assistant` /
  `mcp_assistant`), not under any session.

**My usage.**

- A status strip shows Online / Auth failed / Unreachable for each provider and profile. It
  checks at launch, every 15 minutes, and when you press Refresh.
- Each model gets a card: tokens over time, cost, latency p50/p95, error and rate-limit rates,
  cache hit rate, effort mix, context fill, main vs subagent share, top sessions and rate-limit
  headroom.
- An ElevenLabs card shows credits by day, feature and voice.
- A comparison table includes success rates from `delegation_stats`.
- Delegation savings compare actual cost with an estimate of the cost if the orchestrator had
  done everything at its own prices.
- Export to CSV.

**First run.** Until you've added an Anthropic key, picked a folder for a session and tried a
skill, the empty chat shows a short **Getting started** checklist (OpenAI and ElevenLabs keys are
optional steps) with buttons to each place. It disappears once done, or for good with its ×. A
message sent without a key gets a plain "add your key" note with a button to Settings → Accounts.

**Settings.** Accounts, models and effort, delegation budgets, modes and allowlist, data policy,
ElevenLabs defaults, Appearance and Storage. **Storage** shows the database (and its event log
and file snapshots), media, subagent transcripts and logs with their sizes, and **Compact database
now** (prunes old events and runs `VACUUM`). Every day, and at startup, the app deletes events
older than `event_retention_days` and gives free pages back (`PRAGMA incremental_vacuum`; new
databases use incremental auto-vacuum, older ones switch at the first Compact). The event log only
replays what a window missed during a short disconnect; a window that was away longer reloads.
Appearance sets a background image, GIF or video per theme,
with fit, dim, blur and panel opacity. Video pauses when the window is hidden or on battery
under 20%, and shows a still frame when Reduce motion is on.

## Task board

The **Tasks** page (Kanban icon in the sidebar footer) is a board you and the agent both work
on. The database starts with one board, **Game**, with the columns Backlog, To do, In progress,
Review and Done; Done is a *done column* (its tasks count as finished and searches leave them out
unless asked). Add, rename, reorder (Move left / right in a column's … menu) and delete columns,
mark any column as a done column, and add, rename, switch and delete boards from the board menu
next to the title. Deleting a column moves its tasks to another column of the board; deleting a
board deletes its tasks too and asks first, and the last board can't be deleted.

**Codes.** Every task gets a code from one global counter: `Task00001`, `Task00002`, … (five
digits, more after `Task99999`). A number is taken inside a database write transaction, so two
windows or the agent creating tasks at the same time never get the same one, and it is never
handed out again, even after the task is deleted for good. Everywhere a task is named (the
filter bar, `/task`, the agent tools, the REST API) the code works in any case, or as the bare
number: `Task00012`, `task12`, `#12`, `00012` and `12` are the same task.

**Cards** show the code, title, priority, labels, the due date (red once it's overdue and the
task isn't in a done column), subtask progress, comment count and assignees' initials ("Me" is
you, the robot is the agent). A small robot next to the code marks tasks the agent created or
changed. Drag cards between and within columns, or use **Add task** at the bottom of a column. The
filter bar narrows the board by text or code, assignee (or Unassigned), label, priority and due
date (overdue, today, within 7 days, no date).

**Task drawer.** Click a card to edit everything: title, board and column, priority, due date,
labels, assignees (any name; "me" and "agent" are special), the Markdown description, subtasks
with their own checklists (tick, rename with a double-click, reorder, remove), the sessions
linked to it (click one to open it), comments (the agent's are marked), and the history of the
last 30 changes. **Archive** moves a task to **Recently deleted** (header button), where it can be
restored to its column or deleted for good. Changes from the agent or another window appear at
once (`task.*` events on the live connection).

**`/task` in the composer** (with autocomplete for subcommands, codes and column names):

| Command | What it does |
|---|---|
| `/task new <title> #label !high @column` | Create a task; `#label` (repeatable), `!none\|low\|medium\|high\|urgent` and `@column` are optional (`@in-progress` for names with spaces) |
| `/task <code>` | Put the task into this conversation (a collapsed "Task attached" row with its fields, description, subtasks and last comments) and link the session to it |
| `/task move <code> <column>` | Move it to a column of its board |
| `/task done <code>` | Move it to its board's done column |
| `/task list [words]` | Open the Tasks page filtered by the words |
| `/task link <code>` | Link this session to the task |
| `/task` | Open the Tasks page |

**The agent** has the tools `task_boards`, `task_search`, `task_get`, `task_create`,
`task_update` (fields, moving between columns and boards with `position` top or bottom,
assignees replace / add / remove, and subtask and checklist ops `add rename toggle move remove
add_item rename_item toggle_item move_item remove_item`, applied all or nothing), `task_comment`,
`task_archive` and `task_restore`. Its results always name tasks by code. A task it creates is
linked to its session. One line in the system prompt tells it the board exists and to refer to
tasks by code, so "what's left on Task00012?" works. In Plan only mode the board is read-only for
the agent; subagents can be given the three read tools, never the others. A session can turn the
tools off with the setting `task_board = false`.

**REST** (next to the scheduled tasks, which keep `/api/tasks` and `/api/tasks/{id}`):

| Endpoint | |
|---|---|
| `GET /api/tasks/boards` | boards with columns and task counts, people, priorities |
| `POST /api/tasks/boards`, `PATCH/DELETE /api/tasks/boards/{id}` (`?force=true`) | boards |
| `POST /api/tasks/boards/{id}/columns`, `POST /api/tasks/boards/{id}/order`, `PATCH/DELETE /api/tasks/columns/{id}` (`?move_to=`) | columns |
| `GET /api/tasks/search?q=&assignee=&label=&priority=&due=&board=&column=&include_done=&archived=` | search |
| `GET /api/tasks/archived`, `GET /api/tasks/suggest?q=`, `GET /api/tasks/by-session/{id}` | Recently deleted, code autocomplete, a session's tasks |
| `POST /api/tasks/items`, `GET/PATCH/DELETE /api/tasks/items/{code}`, `GET /api/tasks/by-code/{code}` | tasks (`DELETE` only from Recently deleted) |
| `POST /api/tasks/items/{code}/subtasks` `{ops}`, `/comments`, `/done`, `/archive`, `/restore`, `/sessions`, `/attach`; `DELETE …/sessions/{id}` | the rest |

The tables (migration 4) are `task_boards`, `task_columns`, `board_tasks`, `task_counter`,
`task_subtasks`, `task_checklist`, `task_comments`, `task_activity` and `task_sessions`.

## Campaigns and workflows

Campaigns and workflows run on the built-in loop with an API key. Workflows aren't available
in Claude subscription sessions, including sessions from the new-session screen.

Two ways to run work in phases whose checks the app evaluates itself (an agent saying "done"
never counts):

- A **workflow** (a *chain*) runs in one session: its steps advance in place and its state lives
  in the database.
- A **campaign** spans several sessions. Its state is also a Markdown file in the project,
  `.gamedevworkstation/campaigns/<slug>.md` (request, design target, scope, constraints, phases, coverage,
  feature ledger, decision log, discoveries, review queue, active context, continuation state,
  completion), which you can read and edit; the app owns the Phases, Coverage, Feature ledger and
  Continuation sections and keeps your own sections where they are.

**Templates.** Both are built from workflow templates, TOML files in a skill's `chains/` folder
(the format is in `backend/gamedevworkstation/features/chains.py`). The Unity pack ships eight, offered in
Unity projects:

| Template | Runs as | Phases |
|---|---|---|
| `new-mechanic` New mechanic | chain, campaign | Spec → backlog story → code → compile → behaviour tests → play-verify → commit |
| `bugfix` Bug fix | chain, campaign | Reproduce with a failing test → fix → the repro test and the suite pass → commit |
| `juice-pass` Juice pass | chain, campaign | Baseline screenshots → game-feel pass → before/after play evidence → design critique → commit |
| `content-batch` Content batch | chain, campaign | Plan the items → produce them (Fleet-eligible: one unit per `Assets/Game/<Kind>/<Item>/`) → wire → verify |
| `perf-pass` Performance pass | chain, campaign | Baseline perf report → fix loop (no new anti-patterns) → compare |
| `release` Release | chain, campaign | Freeze → full tests → build → headless smoke → spec-audit critique → changelog and tag |
| `replace-system` Replace a system | chain, campaign | Build beside → parity verify → switch → remove the old system |
| `milestone` Milestone | campaign | One phase per story of the current milestone (from `BACKLOG.md`), then the milestone exit |

User skills can ship their own templates. An invalid file is left out and listed with its errors
(`GET /api/chains`). A phase's `done_when` conditions are `file_exists`, `command_passes` (a
script's `RESULT:` line, e.g. `asset_audit`), `metric_threshold` (`[VERIFY]`/`[PERF]` values),
`gate` (a quality-ladder level of the stories in scope, or a hook gate by name), `visual_verify`
(a fresh screenshot), `git_clean` and `manual` (you answer Pass or Fail on a card); every phase
needs at least one the app can check.

**Starting a workflow.** In a built-in loop session with an API key, type `/workflow <id> <what to do>` in the composer, or `/workflow <id>`
to attach it as a chip and type the request next; the skills button lists the folder's
**Workflows** first. Sending starts the chain in this session. The agent finishes each step with a
`---HANDOFF---` block (What / Decisions / Unresolved / Reversibility) and `chain_step_done`; the
app checks the step, and a failure costs one of its retries (3 by default). When none are left the
chain is **parked** and waits for you.

**Starting a campaign.** On the **Campaigns** page, **New campaign**: template, project folder, the
request (a request under about 20 words is better as a workflow), budget, autopilot, model, effort
(high or below) and mode. **Start** opens the planning session: the agent fills the design target
(end states, never "improve X"), scope (`BACKLOG.md` stories, claimed paths, out of scope) and
constraints, and calls `campaign_submit_plan`. A read-only validator maps your request to the
plan; gaps and "delta" targets go back to the agent (twice at most), then the **Approve plan** card
appears (Approve / Revise / Park, with notes). Each phase then runs in a new session in the
campaign's sidebar group, starting with a brief the app assembles from the campaign file. At
the start of every phase the app records a checkpoint ref
(`refs/gamedevworkstation/checkpoints/<slug>/p<N>`); it never resets your tree, and the page shows the
`git restore` command for you to run.

**Autopilot** continues a running campaign or workflow after each turn while nothing waits for you,
the turn didn't fail, spend is under the budget, there was progress (changed files, new evidence,
a log entry) and the agent didn't end on a question. It pauses after `max_auto_turns` turns in a
phase or `stall_turns` turns without progress, and moves to a new session before the context gets
too large (`on_cost`). **Breakers** park a run: retries used up, compile errors up by 5 in a
phase, a test that passed earlier in the campaign now failing, two failed drift checks (a cheap
check every two phases that the work still serves the request), the budget or session limit.

**On the page** each run shows its status, phase, spend, the current phase's checks and Next
action, with **Start**, **Approve plan**, **Revise plan…**, **Pause**, **Resume** (claims the run
for its session; only one session works on a campaign at a time), **Park**, **New session**
(continue the phase in a fresh session), **Abandon**, the session chain and the checkpoints. The footer has cost and time per story,
the first-pass gate rate, retries per phase, escalations and parks by reason. A session that runs
a campaign or workflow has a **Campaign** card in its side panel with the same essentials. When a
run is parked, waits for you, is paused by the app (for example, the next phase is ready in a new
session with autopilot off) or is done, a notice appears on whatever page you're on, with
**Open**.

**Fleet phases.** A phase marked `fleet = true` (Produce in Content batch) gets a Fleet section in
its brief: when the work splits by folder, the agent runs it as a wave (`run_wave` with the
campaign's id, then `wave_status`, `merge_wave`, `close_wave`). Each unit's discoveries go to the
campaign file's Discoveries (marked `fleet:<unit>`) and to `.gamedevworkstation/discoveries/<date>.jsonl`.
Without a git repository, or with `[fleet] enabled = false`, the brief says so and the phase runs
in the session.

**Blocking gates.** A template's `blocking_gates` make those hook gates block in its sessions even
where the gate is advisory: Performance pass and Release make `unity.antipatterns` (new
anti-patterns in changed scripts) block finishing a turn, with the usual fix attempts. Elsewhere it
stays advisory.

**Tasks.** Task codes in a campaign's or workflow's request (`Task00012`) link every session of the
run to those tasks on the task board.

**Harness.** Campaigns and workflows use the built-in loop with an API key (their tools, autopilot
and gates live there). Workflows aren't available in Claude subscription sessions: the Tools menu
hides them and `/workflow` explains why. New sessions from the new-session screen use the Claude
subscription. A session's harness can't change while a campaign or workflow runs.

**The agent's tools** (only in campaign or workflow sessions; the `campaign` skill is pinned
there): `campaign_status`, `campaign_log` (decision, discovery or note), `campaign_pause` (with an
optional question for the review queue), `campaign_submit_plan` and `campaign_phase_done`
(campaigns), `chain_step_done` (workflows).

**REST:** `GET /api/chains?folder=&kind=`, `GET/POST /api/campaigns`,
`GET/PATCH /api/campaigns/{id}`, and `POST /api/campaigns/{id}/{start|pause|resume|park|abandon|`
`approve_plan|revise_plan|rollover|check|review}`. Events: `campaign.updated`, `campaign.paused`,
`campaign.done`. The tables (migration 3) are `campaigns`, `campaign_sessions`, `gate_runs`,
`fleet_waves` and `fleet_units`.

## Sessions

**The list.** The sidebar shows **Pinned** sessions first, then your **groups**, then the rest
under **Sessions**. Groups have a name, a color and a count. They fold open and closed, and the app
remembers which are folded. The list button next to **+** (top of the sidebar) has:

- **New group**
- **Group by**: Groups (default), Folder (the session's working folder), Date (Today / Yesterday /
  Previous 7 days / Older) or None
- **Sort by**: Last activity (default), Created or Name
- **Archived** and **Trash**

The app remembers these choices in this browser profile (`localStorage`).

**Each row** shows the title and the time of the last activity, plus any of these:

- a spinner while the agent works
- a hand when an approval card is waiting for you
- a solid dot and bold title for a reply you haven't seen
- a warning triangle when the last turn failed

Hover a row, or move the keyboard focus to it, for its **…** button, which opens the same menu
as a right-click (Tab reaches it from the focused row).

**New session (+ or ⌘N)** opens the new-session screen; the session is made when you send its
first message, so no empty "New session" rows pile up. It joins the current session's group (or the
group whose **+** you pressed).

**The new-session screen** asks *What should we work on, <your first name and last initial>?* (the
Mac account's full name; never your Claude login or email). Below it, a card holds the editor and
the new session's settings:

- **Location**: **Chat only** (no folder: Claude Code works in a private scratch folder,
  `<data>/claude_code/<session>/work`, deleted with the session) or **Folder** (Claude Code reads,
  edits and runs commands in that project folder). The folder chip opens the folder picker; your
  recent session folders are the pills under the card, and a click picks one.
- **Model** (Claude models, with their tiers), **effort**, and **mode**: Plan only, Ask before
  edits, Accept edits or Auto ("Claude decides what's safe; risky actions are refused or asked").
  There is no bypass-permissions mode.
- **Tools** picks a skill for the first message; `/` commands work as in the chat (`/model`,
  `/effort` and `/mode` change the card; `/task new` makes a board card).
- **Send** (Enter) creates the session and sends the message.

Every new session from this screen runs **Claude Code on your Claude subscription** (harness `claude_code`, the
`[sessions].default_harness`); there's no harness choice. Sessions made before keep their harness,
shown read-only in the Environment card. If the `claude` CLI is missing or logged out, the screen
shows a slim notice (*Claude Code isn't logged in: run `claude auth login`*) with Copy and Retry.
The paperclip (or drop/paste onto the card) attaches files to the first message, as in any session.

**The session menu** has:

- **Open artifacts**
- **Rename**: inline. You can also double-click the row, press F2, or press Enter on a focused row.
- **Regenerate title**
- **Pin / Unpin**
- **Move to group ▸**: your groups, **New group…** or **Remove from group**
- **Duplicate**: copies the settings and every message
- **Archive / Unarchive**
- **Mark as unread / read**
- **Reveal folder in Finder**: only when the session has a folder
- **Export as Markdown**
- **Delete**: moves the session to Trash. The toast has **Undo**.

**Groups.** Make one with **New group**: from the list button, or from *Move to group ▸ New
group…*, which also moves the session there. Then type its name. A group's **…** button (or
right-click) has these actions:

- New session in group
- Rename (or double-click the name)
- Color
- Collapse / Expand
- Delete group: its sessions become ungrouped; none are deleted

**⌘N** in a grouped session puts the new session in the same group.

**Drag and drop:**

- Drag sessions onto a group to move them there. Drop them on **Sessions** to remove them from
  their group, or on **Pinned** to pin them.
- Drag a group's header to reorder the groups.
- Drag pinned sessions to reorder them.

**Selecting several.** ⌘-click adds or removes a session; ⇧-click selects a range. A bar appears
at the bottom with Pin, Move to group, Archive, Delete and Clear (Esc also clears). Right-clicking
a selected row opens the same bulk actions.

**Archived and Trash.** These views are at the bottom of the sidebar. Archived sessions leave the
main list but stay searchable. Sending a message to one brings it back. **Trash** rows offer
**Restore** and **Delete forever**, and there is **Empty trash**. Deleting a session first stops
its run, its background jobs and its approval cards. Deleting it for good also removes its events,
file snapshots, jobs, approval cards, indexed items and the files the app stored for them (unless
another session still uses a file), its subagent transcripts and its worktrees; usage records stay
for My usage. Sessions stay in Trash for 30 days
(`[sessions] trash_days`); the app empties older ones at startup and once a day.

**Search.** The search box matches titles as you type. A moment later, matches in message text
appear under **In messages**, with a snippet. Click one to open the session at that message;
Enter opens the first result. Message search uses an FTS5 index that triggers keep up to date.

**Fork.** Hover any message in the chat and press **Fork**. You get a new session with the
conversation up to and including that message, and it opens. A forked session starts with a
**Forked from …** link back to the original. Forks and duplicates don't copy a harness's resume
id (the Agent SDK session or Codex thread). The copy starts its own.

**Unread.** A session becomes unread when a reply arrives while you aren't looking at it: another
session is open, or the window is hidden. Scheduled task runs count too. Opening the session marks
it read.

**Auto-titles.** After the first reply, a session still named after your first message gets a
3–6 word title. It's written by `claude.fast` at low effort, through the normal provider adapter,
so effort checks and spend limits apply. Its usage shows in My usage with role `title`. It never
delays or fails a turn; without a key, or if the call fails, the title stays as it was. Renaming a
session yourself turns this off for that session. *Regenerate title* asks again at any time. Turn
it off with `[sessions] auto_title = false`.

**API.** Everything above is plain REST, and each change is published as an event
(`session.created` / `session.updated` / `session.deleted` / `groups.updated`), so other windows
stay in sync:

| Route | What |
|---|---|
| `GET /api/sessions?view=active\|archived\|trash\|all` | list (default: active) |
| `PATCH /api/sessions/{id}` | also `group_id`, `archived`, `sort_order` |
| `DELETE /api/sessions/{id}` / `?purge=1` | move to Trash / delete for good |
| `POST /api/sessions/{id}/restore`, `POST /api/trash/empty` | Trash |
| `POST /api/sessions/bulk` `{ids, action, group_id?}` | `pin unpin archive unarchive delete restore purge move read unread` |
| `POST /api/sessions/reorder` `{ids}` | order of pinned sessions |
| `POST /api/sessions/{id}/duplicate`, `/fork` `{message_id}` | copies |
| `POST /api/sessions/{id}/read`, `/unread`, `/title` | read state, regenerate title |
| `GET /api/sessions/search?q=` | title and message matches; snippets mark matches with `\x02`…`\x03` |
| `GET/POST /api/groups`, `PATCH/DELETE /api/groups/{id}`, `POST /api/groups/reorder` | groups |

## Claude Code sessions

Checked against claude 2.1.308 logged in with a claude.ai (Max) subscription; the redacted captures
are in `tests/fixtures/claude_stream/` and the test CLI replays them. A later Claude Code release can
change these details: see Troubleshooting.

**What it is.** A session on the **Claude Code (subscription)** harness runs your own `claude` CLI
(Claude Code, installed by you and never modified or bundled) inside GameDevWorkstation. You chat
in the normal chat; Claude Code's own loop and tools do the work in the session folder (a worktree
folder works too: the CLI runs there), and its replies, tool cards, approvals and usage show up like
any other session. Every new session from the new-session screen uses it (see
[the new-session screen](#sessions)); older sessions keep their harness. A chat-only session (no
folder) runs in a private scratch folder, `<data>/claude_code/<session>/work`: the CLI's working
directory and the folder scope of its approvals, removed when the session is deleted for good.
Older chat-only sessions keep `<data>/sessions/<session>` so Claude can find their transcripts
when resuming.

**The chat box.** A Claude Code session keeps the new-session screen's card after it starts: the
paperclip, *Chat only* or the folder (fixed once the session has started; click the folder to show it in
Finder), the model (Claude models by name), effort, permission mode (Plan only, Ask before edits,
Accept edits, Auto), Tools and Send. Changing a dropdown updates the session; the next message uses it.

**Session modes (folder sessions).** On the new-session screen, once a folder is chosen, **Modes**
offers two switches. They're set when the session starts.

- **Skipper mode.** After each turn, GameDevWorkstation asks Claude Code for a handoff (goal, what
  was done, current state, decisions, open problems, next step) and saves it as
  `<folder>/.gdw/sessions/<session id>/handoff-001.md`, `handoff-002.md` and so on. It then ends that
  Claude Code conversation and starts a fresh one with the handoff in its instructions, ready for your
  next message. Every prompt starts with a clean context; the chat stays one thread, and a note marks
  each handoff.
- **Central doc.** After each turn, Claude Code is asked for the updated version of one summary doc:
  goal, what's happened, current state, decisions, open questions, next steps. It's saved as
  `<folder>/.gdw/sessions/<session id>/central.md`. With Skipper mode on too, the central doc is the
  handoff, so each turn takes one extra step, not two.

Both extra steps are text-only (tools are refused during them), don't appear as chat messages, and
count toward your usage like any other turn. Add `.gdw/` to the project's `.gitignore` if you don't
want the docs committed.

**Attachments.** The paperclip works as in other sessions. Attached files go to Claude Code inside the
message itself, the way the API takes them: images (already converted and shrunk at upload) and PDFs
as base64, text files as text, audio as its transcript (when there is one), and other binary files
as a note. Each one comes after a `[Attached image: name]` line. Claude Code doesn't get the file's
path and doesn't need to read anything outside its folder. Up to about 20 MB of attachments (base64)
go in one message; the oldest beyond that are replaced by a note. Files marked sensitive follow your
data policy for Anthropic.

**Your login.** These sessions use the Claude account you logged in to with `claude auth login`.
GameDevWorkstation passes no API key and never uses `--bare`. Every CLI process (including status
probes) receives an env allowlist: `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `LANG`, `LC_*`, `TERM`,
`TMPDIR`, `TZ`, `SSH_AUTH_SOCK`, proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `ALL_PROXY`,
any case), `XDG_*`, and `__CF_USER_TEXT_ENCODING`; on Windows also the profile and system variables
`claude` needs to find your login and start (`USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `APPDATA`,
`LOCALAPPDATA`, `ProgramData`, `ProgramFiles*`, `SystemRoot`, `SystemDrive`, `windir`, `ComSpec`,
`PATHEXT`, `TEMP`, `TMP`, `USERNAME`, `USERDOMAIN`, `COMPUTERNAME`, `OS`, `PROCESSOR_ARCHITECTURE`,
`NUMBER_OF_PROCESSORS`); plus GDW's `MCP_TOOL_TIMEOUT`. All other variables,
including provider credentials, `GDW_KEY_*`, `GDW_TOKEN` and arbitrary secrets, are excluded.
**GameDevWorkstation never reads, copies or stores your tokens**: it doesn't open `~/.claude` or the
Keychain entry, and it never runs the login for you.

**Logging in.** Run `claude auth login` in a terminal (it opens your browser). Settings → Claude
Code shows the CLI it found, its version and what `claude auth status` says. On Windows the app looks
for `claude` on PATH, then `claude.exe` or `claude.cmd` in `%USERPROFILE%\.local\bin`,
`%USERPROFILE%\.claude\local`, `%APPDATA%\npm` and `%LOCALAPPDATA%\Programs\claude`. The Claude
desktop app's login is separate from the CLI's: log in once with `claude auth login` as well. An
Anthropic API key saved in GameDevWorkstation's Settings is for the built-in harness only and never
reaches `claude`. If a session isn't
logged in, its reply is a card: *Run `claude auth login` in a terminal, then retry*, with **Retry**.
Only the most recent login card offers Retry. If `claude auth status` reports an API key login,
the session warns, records usage with `billing='api'`, and checks the normal spend limits before
each turn; a reached limit refuses the turn. Subscription logins record `billing='subscription'`.

**How resume works.** Each GameDevWorkstation session keeps one `claude -p` process running
(stream-json in and out) with its own Claude Code conversation id. When the process ends (you quit
the app, it crashed, or you changed the model, effort, mode or Claude Code settings), the next
message starts it again with `--resume <id>`, so the conversation carries on. The session header
shows `claude --resume <id>` with a copy button: paste it in a terminal to continue the same
conversation in Claude Code itself. Sessions started this way don't appear in `claude --resume`'s
picker, only by id. If the saved conversation is gone (Claude Code deletes old transcripts, after 30
days by default), the session starts a new one with a short recap. `/clear` starts a new Claude Code
conversation too.

**GameDevWorkstation's tools.** Claude Code gets GameDevWorkstation's own tools as `mcp__gdw__*`
through a small MCP server inside the backend: the task board (`task_*`), `unity`, saved items
(`list_items`, `get_item`, `read_output`), `read_skill`, gates (`run_gate`), `view_image`,
ElevenLabs, and the MCP servers you turned on for the session in Skills & MCP (MCP for Unity, ...).
They run exactly as in the built-in loop: same approval cards, same Plan only refusals. Tools Claude
Code already has (files, shell, web) and tools that need the built-in loop or an API key
(subagents, waves, campaigns, `critique`, `web_search`) aren't offered. The server only answers on
127.0.0.1, checks the Host and Origin headers, and each claude process gets its own random token (in
a `0600` file in the session's data folder) that only works for that session and stops working when
the process ends (the token is revoked); the MCP config file is then removed. Purging a GDW session removes only its
`data_dir/claude_code/<session-id>/` folder. Your own Claude Code MCP servers and a folder's
`.mcp.json` are excluded by `--strict-mcp-config` unless you turn on Settings → Claude Code →
**Your MCP servers** (`[claude_code].load_user_mcp`); with Settings files **None** your own servers
aren't loaded either. Claude Code loads these tools on demand (its ToolSearch tool), so the first use
of a `mcp__gdw__*` tool in a conversation takes one extra step.

**Approvals and modes.** Every tool call passes GameDevWorkstation's checks first (a `PreToolUse`
hook, on by default: folder scope, sensitive files, git metadata, the before-write snapshot for the Changes card),
then the usual cards for the session's mode (edits in Ask, commands, and permission requests through
`--permission-prompt-tool mcp__gdw__approve`). Questions Claude Code asks you (AskUserQuestion) get a
card with its options, and your pick goes back as its answer. Ask runs Claude Code in `manual`, Accept
edits in `acceptEdits` and Plan only in `plan`; in Plan known file edits and Bash commands are
refused, except the plan file Claude Code writes in its own `~/.claude/plans/` folder (one `.md` file
directly in that folder) before it asks to leave Plan mode. That request (ExitPlanMode) shows
GameDevWorkstation's plan card with the plan text; approving it switches the session to Ask, and
**Keep planning** sends your feedback back. Unrecognized non-GDW tools still get an approval card in Plan mode; the harness cannot classify
their effects. Auto runs Claude Code in its own `auto` mode. Before Claude Code decides, GameDevWorkstation
checks folder scope, sensitive files, git metadata and Plan restrictions, and takes before-write snapshots.
It shows a permission card only when Claude Code asks, and deletes of folders or many files, and git commands that rewrite or discard history (force push, reset --hard, rebase, branch -D …), always ask, even in Auto. GameDevWorkstation never uses `bypassPermissions` or `dontAsk`.
Hook registration failure, timeout or cancellation ends the process with an error; there is no silent
fallback. Auto always requires the hook. In other modes, `pre_tool_hook=false` disables it.

**Settings isolation.** **Settings files** defaults to **None (your ~/.claude hooks, plugins and
settings files are ignored)**. This passes an empty `--setting-sources=`: no user, project or local
settings, so no custom `CLAUDE.md`, skills, agents, installed plugins or their hooks. Admin-managed
policies still apply; auth, model selection, built-in tools and permissions work normally.
`--safe-mode` isn't used: in Claude Code 2.1.308 it also drops the `--mcp-config` servers, so
GameDevWorkstation's tools and approval cards would be missing (and it still lists your installed
plugins). Selecting a subset of `user,project,local` instead passes `--setting-sources=<list>`.
Startup fails closed if the CLI reports hooks or plugins other than its own built-in ones (even with
explicit setting sources), if it doesn't confirm the PreToolUse hook (`hooks_applied`), or if an MCP
server other than `gdw` appears while **Your MCP servers** is off; missing fields are accepted. If
the session's model isn't in the list of models Claude Code offers your login, the chat says so. GDW explicitly
adds the session folder's `CLAUDE.md`, enabled GDW skills and context pack to the appended system
prompt, capped at 64 KB with a truncation note. CLI stderr and errors redact bearer tokens and API keys.

**Usage.** Each turn records the tokens Claude Code reports for that turn and the increase of its
running cost estimate (which counts the whole conversation, across `--resume`). The cost is Claude
Code's own list-price estimate: for subscription logins, My usage shows it as **Claude subscription
(estimated)**, outside daily and session spend limits. API key logins record API spend and use those
limits. A turn you stop mid-reply reports no tokens. Claude Code reports your plan's usage windows
after each request; when one is used up or close to it, the chat shows when it resets, and when
Claude Code retries a rate limit the chat shows it retrying. These sessions skip the automatic
title (which would call the API): they keep the title taken from your first message.

**Limits.** Stop sends Claude Code an interrupt, which ends the turn and keeps the process; if that
doesn't work, SIGINT (which ends the turn and the process), then the process is killed. Subagents,
delegation, fleet waves, campaigns and workflows need the built-in loop. GameDevWorkstation's
compaction and context meter don't apply (Claude Code compacts by itself). Changes to the system
prompt (mode notes, skills, `CLAUDE.md`) reach a resumed conversation only when it starts anew,
because Claude Code keeps the first one. Messages of Claude Code's own subagents go to the turn's log
in Background tasks, not the chat. Not checked on a live login: an API key login (`billing='api'`
path; only the subscription login was tried), the Opus, Sonnet and Fable model ids in a real turn
(they are in the model list Claude Code reports for a Max login; Haiku 5.5 was used), and `can_use_tool`
control requests (Claude Code sends them only with `--permission-prompt-tool stdio`, which GDW doesn't
use). Those paths are read defensively; see Troubleshooting if a session misbehaves after a Claude
Code update.

**Anthropic's policy.** Anthropic's legal and compliance page for Claude Code allows an end user to
sign in to the unmodified Claude Code binary with their own subscription, while products built for
other people should use API keys, and developers "may not collect, store, or intermediate Claude.ai
credentials or session tokens". Plan limits assume ordinary, individual use. GameDevWorkstation
keeps to that: it is a personal app on your own Mac, it launches only your installed `claude`, it
never touches your credentials, and you drive one turn at a time. Don't share these sessions with
other people or use them for automated bulk work, and re-read that page
(code.claude.com/docs/en/legal-and-compliance) before using it any other way.

## Prompt improver

A request in a Unity session can be too vague to build ("make jumping better"). The prompt improver
looks at your project first, and only when a choice would materially change the work does it ask. It is
on by default and works in built-in and Claude Code sessions. The original message is stored unchanged;
the answers and a task summary are added to the request the model sees for that turn only.

**What it researches** (bounded, read-only, no Editor launch): Unity version, installed packages and the
*active* render pipeline, input handler (old, new or both), scenes in Build Settings, likely candidate
scenes/prefabs/scripts, git state, project docs (GDD, TASTE, BACKLOG), the attached task, any running
campaign and recent console errors. Anything it can't find is recorded as `unknown`, never guessed.
Facts that rarely change are cached and refreshed when the underlying files change.

**What it skips** (the message goes through untouched):

| Case | Reason code |
|---|---|
| Message starts with `*` (the `*` is removed before the model sees it; the transcript keeps it) | `star_prefix` |
| Starts with `/` (including `/task`, `/workflow`, `/skill`) | `slash_prefix` |
| Starts with `#` | `hash_prefix` |
| Scheduled, campaign, fleet and subagent messages, loaded skills, tool results, recaps, handoffs | `scheduled`, `campaign`, `fleet`, `subagent`, ... |
| Chat-only session or a folder that is not a Unity project | `chat_only`, `not_unity` |
| Harnesses other than built-in and Claude Code, or a switch turned off | `unsupported_harness`, `harness_disabled` |
| Turned off in Settings, or an empty message | `disabled`, `empty` |

**Questions.** At most 3 per message, one approval card each, 2-4 options with a recommended one, plus
a free-text box and **Skip (assume)**. A skipped optional question becomes an explicit assumption on the
card; skipping a critical one pauses the turn. Topics: `target` (which scene/prefab), `platform_input`,
`acceptance`, `feel` (jump height, apex time, coyote time, hit-stop), `assets`, `performance`,
`multiplayer` (who owns the state) and `bug_replay` (recorded input sequence, scene, seed, checkpoint).
Options come from your own project facts; it never assumes permission to buy or download assets.

**Task card.** Every run saves an indexed draft with the goal, scope, acceptance criteria (each with a
verification type and a target where numeric), a quality ladder level (L1-L4 or manual), effort and
budget recommendations, your answers, assumptions, risks and a routing suggestion (skills, MCP or CLI,
harness). It is a recommendation only: it never spends money or switches harness. **Save to Tasks** on the
card writes it to the Backlog. A Backlog task is created automatically only when you answered at least
one question; for an explicitly attached task a proposal comment is added and its text is never
overwritten. In Plan only mode, or with the task-board tools off, only the draft is kept.

**Settings** (`[prompt_improver]`, Settings > Prompt improver, changes apply to the next unsent turn):

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | master switch |
| `builtin_enabled`, `claude_code_enabled` | `true`, `true` | per harness |
| `max_questions` | `3` | 1-3 |
| `model` | `claude.fast` | alias; Claude Code accepts only a model your login lists, no silent fallback |
| `effort` | `low` | `none`, `low`, `medium` or `high` (above high is refused) |
| `max_calls` | `2` | 1-2: one evaluation plus at most one synthesis |
| `max_input_tokens`, `max_output_tokens` | `4096`, `2048` | per call |
| `timeout_s` | `30` | per call |
| `budget_usd` | `0.03` | per-prompt cap, 0-1 |
| `breaker_failures`, `breaker_pause_s` | `2`, `600` | after this many failures in a row (per session, or per model), the improver pauses for this long and shows one notice; a success resets it |

**Claude Code sessions.** The improver runs in a separate, tool-less, text-only helper conversation on
your own Claude login, so no API key is needed. It counts against your subscription limits like any other
Claude Code usage, and its token use is recorded under the `prompt_improver` feature (the CLI's own
accounting can be coarser than the built-in loop's).

**Cost limits.** At most 2 model calls per message, bounded input and output tokens, a wall-clock
timeout, and the budget cap above; each call passes the effort gate first. If the improver fails or runs
over budget you see an "unavailable" notice and your original message is sent unchanged.

**Running the evaluation.** A 48-prompt corpus (24 vague, 24 clear, plus a separate list of bypass cases)
lives in `tests/fixtures/prompt_improver/prompts.json`.

```bash
uv run --frozen python scripts/eval_prompt_improver.py --fake --out /tmp/pi-eval.json   # free, no network
uv run --frozen python scripts/eval_prompt_improver.py --live --yes --out pi-live.json   # real model calls, costs money
```

It reports the vague ask-rate, clear false-ask rate, bypass accuracy, mean and p95 added input/output
tokens, calls and cards per prompt. `--fake` uses a scripted FakeProvider with a small cue heuristic
(missing target, number or acceptance cues), so its results test orchestration and the regression gates in
`tests/test_pi_eval.py`, not model intelligence. A real run only happens after you approve its cost.

One real run has been measured (2026-11-19, `claude.fast` = Claude Haiku 5.5, effort low, template
`pi-eval-2`, this 48-prompt corpus only; the decision rules were tuned on the same corpus, so treat these
as optimistic):

| Metric | Measured |
|---|---|
| Vague ask-rate | 0.83 (20 of 24; 2 more were parse errors since fixed) |
| Clear false-ask rate | 0.04 (1 of 24) |
| Bypass accuracy | 15 of 15 |
| Calls / cards per prompt, max | 2 / 3 |
| Added tokens per prompt, mean / p95 | 3,647 / 5,059 (about half of the output is hidden thinking) |
| Mean clear overhead | 3,159, above the 2,500 fake-model gate |

## Keyboard shortcuts

**⌘/** shows this list in the app. The Session menu in the macOS menu bar has the session
shortcuts too.

| Keys | Action |
|---|---|
| ⌘N | New session (joins the current session's group) |
| ⌘⇧[ / ⌘⇧] | Previous / next session in sidebar order |
| F2 | Rename the current session |
| ⌘⇧P | Pin or unpin the current session |
| ⌘⌫ | Move the current session to Trash, with Undo. Inside a text field it still deletes text. |
| ⌘-click / ⇧-click | Select several sessions; Esc clears the selection |
| ↑ ↓ / Space / Enter / ⇧F10 | On a focused session row: move, open, rename, open its menu |
| ⌘K | Search artifacts, media, files and links |
| ⌘J | Terminal |
| ⌘, | Settings |

## How delegation works

The `delegation` skill ([`skills/delegation/SKILL.md`](../skills/delegation/SKILL.md), exactly as
specified) is on for the main agent by default. It gives the orchestrator a routing table and
these tools:

- `spawn_subagent(name, provider, tier, effort, instructions, tools, worktree, run_in_background, job_type)`
- `get_subagent_result`, `message_subagent`, `stop_subagent`, `merge_worktree`, `discard_worktree`
- `request_effort_approval` — shows you an approval card and returns a one-unit token
- `get_delegation_stats` and `record_unit_outcome` — the table it learns from

Rules the backend enforces regardless of the skill:

- **Effort.** `xhigh` and `max` are rejected before any API call unless they carry a token
  minted when you press Approve. The token works for one subagent unit (or one session), and
  only up to the level you approved.
- **Depth.** Subagents are one level deep, with a max-turn limit and a spend cap. They get only
  the tools they were granted (read-only by default).
- **Parallel code edits.** Code units that run in parallel always get their own git worktree on
  branch `gdw/<unit>`. The orchestrator merges them back and reports any conflicts, or
  discards failed and abandoned ones (`discard_worktree` refuses unmerged work unless
  `force=true`, and always asks you). Deleting a session removes its worktrees: clean ones with
  their branch; unmerged work is committed to its `gdw/<unit>` branch, which is kept. At
  startup, worktrees whose session is gone are removed, except ones with uncommitted changes,
  which are only listed in `backend.log`.
- **Codex CLI units** (`codex.cli`) run `codex exec --json --sandbox workspace-write` in their
  worktree. Launching one asks first unless `codex_cli:*` is allowlisted. They aren't launched in
  Plan only mode; one that was approved before the session switched to Plan runs `--sandbox read-only`.
- **Budgets.** Spend limits pause every route (API subagents, Codex CLI units, ElevenLabs,
  web search), and new units are refused once a job has spent `job_budget_usd`.
- **Web research.** `web_search` (Claude's basic server-side search on `claude.fast`, cited) and
  `web_fetch` (public pages only; local, private and other non-global addresses, including
  Tailscale/CGNAT `100.64.0.0/10`, are refused at every redirect, and each request connects to the
  address that was checked) can be granted to any subagent, Codex
  included. Cited and fetched URLs show up under Links.
- **Git metadata.** Agent file tools (`write_file`, `edit_file`, `delete_file`, and the Agent SDK
  harness's Write/Edit) refuse anything inside a `.git` folder or a worktree's `.git` file; reading
  it is fine. Every git command the app runs itself (worktree add, commit, merge, the Changes card's
  diff, cleanup) passes `-c core.hooksPath=/dev/null -c core.fsmonitor=false
  -c safe.bareRepository=explicit` (diffs also `--no-ext-diff --no-textconv`), so a repository's hooks
  or config never run a program behind your back.
- **MCP tools and modes.** Local MCP tools follow the session mode, judged by their MCP annotations
  (missing ones count as MCP's defaults: not read-only, destructive, open-world). `readOnlyHint` tools
  always run. Plan runs nothing else. Ask asks before every other tool. Accept edits also runs tools
  that declare `destructiveHint: false` and `openWorldHint: false`, and asks for the rest. The card
  shows the arguments and what the annotations say. `mcp:<server>__<tool>` rules skip the card
  (except in Plan). Shared servers keep their own rules on top (Shared tools on, every job asks).
- **Harnesses.** The Agent SDK harness checks every tool call in a `PreToolUse` hook (folder scope,
  data policy, Plan mode, git metadata, the before-write snapshot, approval cards), so Accept edits
  and the CLI's own auto-allow rules can't skip them; `can_use_tool` repeats the checks. It loads no
  settings files (`setting_sources=[]`, `strict_mcp_config`): a folder's `.claude/settings.json` could
  carry allow rules, hooks or env. The folder's `CLAUDE.md` (and `.claude/CLAUDE.md`) is passed as the
  system prompt instead. The Codex CLI harness asks once per turn in Ask and Accept edits unless
  `codex_cli:<folder>` is allowlisted; Plan runs it read-only without asking. The Agent SDK's
  `WebFetch` only reaches http(s) hosts that resolve to public addresses.
- **Untrusted content.** Results of `web_fetch`, `web_search`, MCP tools and subagents, and the
  text and titles `get_item` / `list_items` return, reach the model inside
  `<untrusted-XXXXXXXX source="…">` blocks whose tag has a fresh random suffix each time (so the
  content can't close its own block; look-alike tags inside are defanged too), and the system
  prompts say that content is data, never instructions. Remote images in chat Markdown show as a
  *Remote image: host · Load* chip and load only when you click it (through the backend; the window
  itself loads no remote images). In browser mode the app page carries a CSP with the same image and
  media rules.
- **Data policy.** Files you mark sensitive are replaced with a note in every request to a
  provider that isn't allowed, and `read_file` / `get_item` refuse them for that provider.
- **Stats.** Every finished unit writes a `delegation_stats` row (job type, route, effort,
  tokens, cost, wall time, success, escalation steps, whether approval was requested).

## Built-in skills

Every built-in skill is available in every session. Only `delegation` is on by default; the
others turn on when you invoke them.

| Skill | What it does |
|---|---|
| `delegation` | Cost-aware routing across Claude, Codex and ElevenLabs (on by default) |
| `graphify` | Turns a folder, repo or docs into a knowledge graph you can query |
| `grilling` | A relentless interview to sharpen a plan or design, a round of questions at a time |
| `claude-handoff` | Writes a handoff summary and starts a fresh background agent with it |
| `game-designer` | Game design partner, with references, templates and a calculator script |
| `cost-effective-claude-delegation` | Does a task at the lowest total cost, step by step |
| `high-performance-claude-delegation` | Runs independent units in parallel on Opus at high effort, then an Opus reviewer |
| `unity-router` (featured) | Unity game pack entry point: picks which Unity skills to load for a task and uses the route the harness reports (MCP, Unity CLI live or batch); see [`skills/unity-router`](../skills/unity-router/SKILL.md) |
| `compile-fix-loop`, `play-verify`, `headless-ops`, `scene-prefab-safety`, `gdd-to-backlog`, `project-memory`, `architecture-patterns`, `asset-pipeline`, `perf-pass`, `game-feel-pass`, `build-ship`, `vcs-hygiene` | The rest of the Unity 6 game-creation pack: compile/fix, Play Mode checks, headless builds and tests, safe scene/prefab edits, GDD to backlog, project memory, architecture templates, asset pipeline, performance, game feel, shipping and git hygiene (with scripts, templates and references) |
| `unity-mcp-orchestrator` | MCP for Unity tool reference and workflows, used by the Unity pack |
| `trailer-maker` | Game trailers from real gameplay: brief, beat sheet, shot list captured in Play Mode with the Unity Recorder, an ffmpeg edit from a JSON edit list, ElevenLabs music/VO/SFX cut to the beat sheet, three reviewers, and Steam/YouTube/vertical exports; see [`skills/trailer-maker`](../skills/trailer-maker/SKILL.md) |
| `replay` | Record and replay instrumented Unity sessions (same-environment, Input System only), verify frame-by-frame checkpoint hashes, and export silent gameplay GIF/MP4; see [`skills/replay`](../skills/replay/SKILL.md) |

**Unity pack setup.** The Unity skills drive the editor through the MCP for Unity server, and
GameDevWorkstation sets that up for you: the built-in `unity` server (`uvx --offline --from
mcpforunityserver==10.3.0 mcp-for-unity`, `uvx` looked up on your login shell's PATH, then
`/opt/homebrew/bin`) is on the Skills & MCP page from the first start, and invoking any Unity
skill (or ticking one in the Connectors card) turns it on for that session, with a short notice.
`[skills.mcp_on_invoke]` in config says which skills turn on which servers; servers from other
machines are never turned on this way. What you still need:

- `uv` installed (`brew install uv`); the page says so if `uvx` is missing. `--offline` means
  the `mcpforunityserver` package must already be in uv's cache: run
  `uvx --from mcpforunityserver==10.3.0 mcp-for-unity` once while online (then Ctrl-C), or edit
  the server and drop `--offline`.
- the `com.coplaydev.unity-mcp` package (MCP for Unity 10.3) in your Unity project;
- the Unity editor open on that project (Window > MCP for Unity shows the bridge).

If the server can't start or Unity isn't open, the turn still runs: the Connectors card shows the
error on the server's dot, and the MCP tools fail with their usual errors.
Its tools appear as `mcp__unity__<tool>`; the skills name them by bare name (`read_console`,
`manage_editor`, ...), and the tool-mapping note tells the model how they correspond.
With the editor closed, `headless-ops` and `build-ship` fall back to batchmode and work without it.

### Unity: MCP or CLI

The harness can drive Unity two ways, and you choose with the **Unity backend**:

| Backend | Editor open | Editor closed |
|---|---|---|
| `mcp` | MCP for Unity (the `unity` server above) | `headless-ops` `unity.sh` batchmode (the behaviour before the CLI backend) |
| `cli` | the official Unity CLI against the open Editor (`unity recompile`, `unity command …`); needs the `com.unity.pipeline` package in the project | `unity run` (compile), `unity test`, `unity build` in batch mode; `unity.sh` when the Unity CLI isn't installed |
| `auto` (default) | `auto_live_order` (MCP first, then the Unity CLI live route) | the Unity CLI if found, else `unity.sh` |

**Where you set it.** Settings → Unity sets the default for every project (`[unity] backend`) and
shows the Unity CLI that was found (path and version) and the installed editors.
The Quality card has **Unity backend** for the session ("Project default" or Auto / MCP / CLI)
and **Set as project default**; the chip at the bottom of the composer (`Unity · MCP`,
`Unity · CLI live`, `Unity · CLI batch`, `Unity · Batch (unity.sh)`, `Unity · Editor open — no
bridge`, `Unity · Safe Mode`, `Unity · busy: …`) shows the route the next compile takes and has the
same switch. A session's choice wins over the project's, which wins over the default.

**The Unity CLI.** Unity Hub installs it (`/Applications/Unity Hub.app/Contents/Resources/unity`
and `~/.unity/bin/unity`), or `curl -fsSL https://unity.com/install.sh | bash`. The app uses
`[unity] cli_path`, else `unity` on your login shell's PATH, else those two places, and only a
program that answers like the Unity CLI (`--version`, `commands --format json` listing
`recompile`). Versions older than `min_cli_version` (1.0.0-beta.11) are reported and not used. The
app never updates it by itself (run `unity self-update`; `POST /api/unity/actions/update_cli` does
it behind a card).
Batch jobs run the Editor version in `ProjectSettings/ProjectVersion.txt`; when that version isn't
installed the check is skipped with "Unity <version> isn't installed", never run with another one.

**Live Editor (`cli_live`).** The Unity CLI talks to a running Editor through the
`com.unity.pipeline` package (Unity 6+). Compile is `unity recompile` (errors as JSON, a few hundred
ms, no domain reload on a clean run); tests are the Editor's `run_tests` command (named `test run`
in older Pipeline versions; the app reads the Editor's command list), run detached and waited for.
The agent's `unity` tool also offers `eval` (C# in the Editor; always shown to you first, and
`[unity] eval = "off"` turns it off), named Pipeline commands, `screenshot` and a `play` loop
(`set_autotick`, then `editor_play`).

**Editor open, no live route.** Batch mode can never open a project an Editor holds, so nothing runs
in batch then. In `auto`, MCP is used when it's connected. Otherwise the gates report *skipped* with
the reason, and the chip offers these actions, in this order (install Pipeline, use MCP once, run on
a copy, close Unity):
- **Install Pipeline package**: `unity pipeline install --package-version 1.0.0` (pinned), behind a
  card; it changes `Packages/manifest.json` (a tracked file). Unity loads it the next time its
  window gets focus ("Switch to the Unity window once").
- **Use MCP for this check** (when MCP for Unity is in the project): one compile over MCP, the
  setting unchanged.
- **Run on a copy**: the compile or tests run on a copy of the project instead (see
  [Run on a copy](#run-on-a-copy-while-the-editor-is-open) below). With
  `clone_when_open = "always"` this happens without the chip action.
- **Close Unity**: `unity close`, behind a card that says Unity exits **without saving**. Never
  automatic, never forced.

**Safe Mode.** An Editor that booted with compile errors loads neither MCP for Unity nor the
Pipeline package. The app notices (`unity pipeline list`), takes the `error CS` lines for this
project from `Logs/Editor.log` (or the global Editor log when it names this project), and the compile
gate fails with them; it never passes. Tests are skipped until it compiles.

**Approvals.** `status`, `commands` and `log` never ask. Compile and tests run without a card when
the Unity gates are on for the project (their consent now also lists the Unity CLI checks
`compile` and `test:editmode`; consent given before this version still covers the same gates) or
after **Always allow** on a card; they also run in Plan only mode (they write only `Library/`,
`Logs/` and `Temp/`). Builds, exec, import, Pipeline commands, screenshots and play always ask
(with the exact command line), with **Always allow `<op>` in this project**, and never run in Plan
only mode. Installing the Pipeline package, opening or closing Unity and updating the CLI always
ask.

**Jobs and logs.** One Unity job runs per project at a time (a second one waits). Each is a
background job (kind `unity`) whose output streams to the Terminal drawer like an agent command;
**Cancel** on the chip (or Stop) ends the Unity CLI's process group and any batch-mode Unity it
left for that project (never a GUI Editor). Logs and test results go to
`<project>/Logs/harness/` (Unity's default `.gitignore` ignores `Logs/`). Timeouts: `[unity]`
`live_timeout_s` 120, `live_test_timeout_s` 900, `batch_timeout_s` 900, `test_timeout_s` 1800,
`build_timeout_s` 3600; the CLI's own `--timeout` fires first, the app's watchdog 30 s later.

**Evidence.** Compile and test results from the `unity` tool become quality-ladder evidence (L1,
L2 from the NUnit XML or the live run's results) stamped with when the run *started*, so an edit
made during a long compile isn't covered by it. `unity test … --output X` or `unity recompile
--format json` typed into `run_command` are re-checked from the XML or the JSON envelope.

**MCP stays off in CLI mode.** With the `cli` backend, invoking a Unity skill doesn't turn on the
`unity` MCP server (`[unity] mcp_server`).

**Harness editor scripts.** Asset import, menu items with the Editor closed, a batch screenshot
(version 3), a forced clean recompile, a development build and `Harness.*` exec methods need `HarnessCli` (the `headless-ops`
editor scripts) in the project. When they're missing, the `unity` tool returns a "needs harness"
result instead of failing, and the chip offers **Install harness editor scripts** behind an approval
card.
- It copies 3 files (`HarnessCli.cs`, `HarnessArgs.cs`, `Harness.Headless.Editor.asmdef`) into
  `Assets/Harness/Headless/Editor/`, with fixed `.meta` GUIDs so every machine gets the same ones.
- It adds `Assets/Harness/Headless/` and `Assets/Harness/Headless.meta` (plus `Assets/Harness.meta` when
  it created `Assets/Harness/`) to `.git/info/exclude` (your local, untracked ignore list), so no tracked
  file changes and nothing shows up in `git status`. Other skills' code under `Assets/Harness/` stays
  tracked as usual. Set
  `harness_git_exclude = false` if you want to commit the scripts instead.
- It never overwrites a file you edited. An older install (`// harness-version: N` in the header) is
  upgraded only after you agree on a card.
- Removing the scripts is manual: delete `Assets/Harness/Headless` and its `.meta`, and the lines
  under the GameDevWorkstation header in `.git/info/exclude`.
- `[unity] harness_scripts = "ask"` (default) offers the install; `"never"` stops offering it, and
  those ops then report what's missing.

**Menu items in batch.** `HarnessCli.MenuItem` runs one menu item with the Editor closed: it passes
`-menu "Path/To/Item"`, calls `EditorApplication.ExecuteMenuItem`, runs `AssetDatabase.SaveAssets()`
and exits one tick later (the same deferred exit as the other entry points). So the `menu` op now works
in batch too, and needs the harness scripts. `-buildOutput` is accepted as an alias of `-out`.

### Run on a copy while the Editor is open

When Unity holds the project and no live route is available in `cli` or `auto` mode, compile and tests can
run on a copy of the project instead of waiting for you to close Unity. The copy lives at
`~/Library/Caches/GameDevWorkstation/unity-clones/<hash>/`. The first time it's made with `cp -cR`
(an APFS clone, so it costs almost no disk and keeps `Library/`, which makes the first import fast);
later runs only `rsync` `Assets/`, `Packages/` and `ProjectSettings/` over it. Your project is never
written to.

Results from a copy are labelled **"on a copy of the files on disk (unsaved Editor changes not
included)"**: the copy sees what is saved, not what is open and unsaved in the Editor, so save first
when it matters.

`[unity] clone_when_open`: `"ask"` (default) offers **Run on a copy** in the chip, `"never"` removes the action
(and refuses it), `"always"` runs compile, tests and gates on the copy automatically while Unity is open.
Builds and exec never run on a copy. Set it in Settings → Unity. The copies are
a cache; deleting the folder only means the next run makes the copy again.

**What the agent already knows.** At session start the project context pack includes one line,
`Unity: backend=… route=… (…)`, with the backend, the route the next job takes and why, so
the agent doesn't need to work it out first.

**Skill index.** The `unity-mcp-orchestrator` skill is hidden from the index when the backend is
`cli`, or when the backend is `auto` and the route checked at session start is `cli_live`, `cli_batch`
or `raw_batch`. This is decided once at session start; **Refresh context** updates it. The skill can
still be pinned or invoked by name.

**Not yet:** a warm `unity shell` process for live calls.

**Trailers (`trailer-maker`).** What it needs beyond the Unity pack:

- `ffmpeg` and `ffprobe` (`brew install ffmpeg`). The skill finds them on PATH, then in `/opt/homebrew/bin`
  (or `TRAILER_FFMPEG`); `trailer_edl.py doctor` lists what is missing. Text cards and captions are rendered as images
  in Unity (with your game's font), so the slim Homebrew formula is enough; `ffmpeg-full` adds `drawtext`/libass if
  you want them. ffmpeg is GPL software that GameDevWorkstation runs as a separate program and does not ship.
- the `com.unity.recorder` package (5.x) and the skill's `Harness.Trailer` editor scripts in your project (the skill
  installs both). Capture needs the Editor open (MCP) or the GUI editor started from the command line: the Recorder
  doesn't run in batchmode. With the URP 2D Renderer it records the Game view.
- Project Settings → Audio → Default Speaker Mode: Stereo. FMOD or Wwise audio isn't captured by the Recorder; record
  it separately or rebuild it in the edit.

Work lives at your project root in `Trailer/<slug>/` (outside `Assets/`): the plans (brief, beat sheet, shot list,
edit list) are meant for git; captures, renders and exports are not (the skill gives the `.gitignore` lines). Every
script ends with `RESULT: OK|FAIL`; files a command announces with `TRAILER_OUTPUT: <path>` (or `ARTIFACT: <path>`
from any script) inside the session folder are indexed as items when they are images, video or audio, so the cut
plays inline in Artifacts. The skill ships a `trailer` workflow template (brief → beat sheet → shot list → capture →
rough cut → music, VO and SFX → trailer review → exports) for the chains engine. The review uses three reviewer
subagents; the minimum score must reach the brief's pass score (7 by default), two rounds at most, then you decide.

**Record and replay (`replay`).** Record instrumented Unity sessions,
replay them with frame-by-frame checkpoint verification, and export gameplay GIF or MP4.
The guarantee is same-environment repeatability, checked against the state you register
with the package's providers. It is not cross-machine determinism. What it needs beyond the
Unity pack:

- The `com.gdw.replay` package (installed by `unity op=replay_install`, behind setup consent;
  it also adds missing test and Input System entries to `Packages/manifest.json` and keeps
  existing pins).
- Input System 1.20.1 (the only input path; gameplay that reads the legacy Input Manager is
  not supported: the Editor refuses to record or replay and names the files and calls). Gameplay RNG
  should route through `GdwRandom.Stream("name")`.
- `ffmpeg` and `ffprobe` for GIF/MP4 export (`brew install ffmpeg`). The skill's
  `replay_media.py doctor` checks readiness.
- Recording is live-Editor only (MCP or CLI live). Replay, verify and render run in a batch
  Editor.
- The PNG-per-frame capture path is the default (`auto` = png). The Unity Recorder is
  used only when `backend:recorder` is requested and `com.unity.recorder` is already
  installed (never automatic). MP4 is silent.
- Replay never refuses on an environment mismatch. The report has `environment: matched` or
  `differs` plus the differing fields (Unity version, OS, CPU, project id, scene GUID,
  package versions, package lock). Statuses are `pass`, `diverged`, `incompatible`, `error`
  and `cancelled`.

Work lives in `<project>/Logs/harness/replay/<run_id>/`: the `.gdwreplay` archive,
`request.json`, `report.json`, and optional `capture/frames/` and `exports/`. After a
successful export, that export's own intermediate frame PNGs are deleted. Nothing else is
deleted automatically. `replay_status` and an export result warn when
`Logs/harness/replay/` is over `[unity.replay] warn_total_mb` (2048 MiB by default).

The `unity` tool ops are `replay_install`, `record`, `replay`, `replay_verify`,
`replay_render`, `replay_stop` and `replay_status`. `replay_install` needs setup consent.
`record`, `replay`, `replay_render`, `replay_stop` and a `replay_verify` with `capture` need
change permission and don't run in Plan only mode. A `replay_verify` without `capture` follows
test consent. `replay_status` only reads. The same ops are on REST under
`/api/sessions/{sid}/replays`: `POST` to `record`, `replay`, `verify` and `render` (each answers
202 with `job_id`, `run_id` and `status_url`), `POST /{run_id}/stop`, and `GET /{run_id}` for
the status and report. Limits live in `[unity.replay]` (`max_seconds`, `max_trace_mb`,
`max_archive_mb`, `capture_max_seconds`, `gif_max_seconds`, `warn_total_mb`).

**Invoking a skill.** Any of these does the same thing:

- the **Sparkles** button in the composer: the featured skills come first, then all others;
- `/skill <name>` in the composer, with autocomplete (`/skill <name> <message>` sends at once);
- **Use in chat** on a skill's row on the Skills & MCP page, which opens the current session
  (or a new one).

The skill shows as a chip on your draft; remove it with its ×. When you send, the skill is
turned on for the session, so follow-up turns keep it, and it appears in the Connectors card.
The message starts with `Use the <name> skill.` and carries `invoked_skill` in its metadata.
The API takes the same thing: `POST /api/sessions/{id}/messages` with `{"text", "skill"}`.

**Skills written for Claude Code.** Most skills were written for Claude Code, whose tools
differ. When any of them is on, the system prompt gets one short note that maps Claude Code's
tools to GameDevWorkstation's: `Agent`/`Task` to `spawn_subagent` (opus is `claude.deep`, sonnet is
`claude.standard`, haiku is `claude.fast`), `Bash` to `run_command`, `Read`/`Glob`/`Grep` to
`read_file`/`list_dir`/`search`, and so on. The `read_skill` tool reads a skill's
own files (`references/`, `templates/`, `scripts/`). Skills written for GameDevWorkstation say
`runtime: gamedevworkstation` in their frontmatter and get no note; `delegation` is native too.

## CI failure triage

`gdw triage` reads a failed CI run's logs, puts each failure in a category and names the file and
line to look at. The categories are compile error, test failure, flaky test, infra/runner,
dependency, timeout and unknown.

```bash
gdw triage 1234567890 --repo owner/name      # a GitHub Actions run (uses your `gh` login)
gdw triage build.log Editor.log results.xml  # local logs, merged into one report
gdw triage logs/ --json                      # a folder of *.log / *.txt / *.xml, as JSON
```

**What it reads:** GitHub Actions logs (`gh run view --log-failed` or raw), pytest, vitest and jest,
tsc, cargo, uv and pip, npm, dotnet, Unity `Editor.log` compile errors and Unity Test Framework
NUnit XML from EditMode and PlayMode runs. JUnit XML works too.

**How it classifies:** rules come first (`backend/gamedevworkstation/features/triage_rules.py`),
and when a failure has a higher-precedence cause, that cause wins. For example, a test killed by a
runner shutdown is reported as infra, not as a test failure. A suggested fix appears only for
clear cases such as CS0103 or CS0246, a missing Python module, an npm lockfile out of sync, a full
disk or a job timeout.

**The model fallback:** steps that fail without matching any rule are reported as `unknown`.
`--llm` sends those steps (at most 5 per report) to `claude.fast` at low effort through the
provider layer. Effort goes through the same gate as every other model call, and the log text is
wrapped as untrusted data. Each report ends with a line saying how many failing steps the rules
classified.

**Options:**
- `--summary` appends the report to `$GITHUB_STEP_SUMMARY`.
- `--comment N` posts it on pull request N, and updates that comment when the run is retried.
- In the app, `POST /api/triage` takes `text`, `path` or `run_id`. It saves the report as an item
  (`file` / `ci_triage`).

**As a GitHub Action:** `.github/workflows/triage.yml` runs after the CI workflow fails. It writes
a job summary and comments on the pull request. It uses rules only, so it needs no model key. It
runs from the default branch and never checks out or runs pull-request code. Its permissions are
`actions: read`, `contents: read` and `pull-requests: write`. Runs from fork pull requests get the
job summary but no comment. Another repository can use the composite action:

```yaml
- uses: ArshiaJahan/GDH/.github/actions/triage@main
  with:
    run-id: ${{ github.event.workflow_run.id }}
    comment-pr: ${{ github.event.workflow_run.pull_requests[0].number }}
```

**Accuracy:** `tests/test_triage_fixtures.py` checks the rules against 26 labelled failed logs in
`tests/fixtures/ci_logs/`. They break down as:
- 2 real failures from this repository's CI
- 9 made by running the real tools on small failing examples
- 15 written by hand where a tool couldn't be run here: Unity, runner and network failures, uv,
  npm, and a flaky rerun

The fixtures were written by different agents from the rules, and the rules author never saw them.

| Run (2026-11-18) | Category | File and line | Classified by rules |
| --- | --- | --- | --- |
| First run, fixtures unseen | 24/26 | 18/20 | 96% |
| After fixing the two rule gaps it found | 26/26 | 19/20 | 100% |

The first run's misses were:
- a Unity test retried and then passing, which should be flaky
- an assertion whose message only mentions "timeout"

The remaining miss is a uv resolution failure, which names no file.

## Eval Forge

Eval Forge turns real merged changes into tasks for coding agents, checks that each task's grader can tell a
correct solution from a flawed one, runs agents on the tasks, and says why each failure happened.

```bash
gdw eval forge <commit> --out evals/suite                  # a commit with tests becomes a task
gdw eval forge --pr 123 --github owner/name --rewrite      # a merged PR; a model restates the text first
gdw eval validate --suite evals/suite --markdown           # the reference must pass, flawed solutions must fail
gdw eval grade evals/suite/<task> --patch my.diff          # grade one candidate change
gdw eval run --agents claude_code,codex,builtin --trials 3 # pass@k, cost, wall time, tool calls, blame
gdw eval export --suite evals/suite --out harbor/          # Harbor tasks (the Terminal-Bench 2.0 format)
gdw eval list --suite evals/suite                          # check every task loads
```

**A task** is a folder (`gdw.eval.task/1`):

| File | What it holds |
|---|---|
| `task.toml` | the source commit and its parent (the start state), the grader, time and cost limits, what the leak filter removed |
| `prompt.md` | what the agent is told |
| `solution.patch` | the reference: the commit's source change, tests excluded |
| `grader/files/` | the commit's tests. They're laid over the agent's work at grading time, so the agent never sees them and can't edit them into passing |
| `validation.json` | the last `gdw eval validate` result |

**The prompt** is the PR or commit text after a leak filter. The filter drops code blocks, diff lines and
trailers. It also replaces the names and new files that only the solution introduces, and the hidden tests'
names and paths. Names the hidden tests call are the task's interface, not its solution: the forge lists their
declarations, without bodies, under "Interface the tests use", so a task can be passed without guessing names.
`--rewrite` has a model restate the text first (effort gate, usage recorded), and the filter runs again on the
rewrite.

**Graders** (all optional, all must pass):

- the test command and named shell checks
- differential: one command per input, run in the reference tree and in the candidate's; stdout must match
- Unity: text asserts on scenes and prefabs, plus a batch replay of a recorded run through the Unity CLI that
  must verify every frame hash
- rubric: a model judges the diff against `rubric.md` (effort gate)

Task commands run without credential environment variables, and `python` is the grader's own interpreter. Each
step marks a failure that looks like the machine's (command not found, timeout, failed setup, no Unity) as an
environment failure.

**Grader validation** runs the reference and a set of flawed solutions made from it:

- the start state, unchanged
- the reference with one code hunk left out
- one-line mutants on added code: flipped comparisons, off-by-one constants, swapped booleans, a dropped
  return value, `and`/`or` and `+`/`-` swaps
- test tampering: the hidden tests deleted, or rewritten to pass

Flawed solutions are only made from code files, because a README or CI hunk isn't something a task's tests are
meant to catch. A flawed solution that passes "survives", and the report lists every survivor. Some survivors
are equivalent mutants that behave the same as the reference (`v < 0` and `v <= 0` both return 0 at zero), so a
survivor is a reason to look, not proof of a weak grader.

**Runs**: every trial gets a fresh throwaway worktree at the start commit and only the prompt.

- `claude_code` is your `claude` CLI on your subscription (no API keys reach it), with Bash and file tools in the
  trial worktree and `--max-budget-usd` from the task. Its cost is the CLI's API-equivalent estimate.
- `codex` is `codex exec` in its workspace-write sandbox.
- `builtin` is GameDevWorkstation's subagent loop with file tools and no shell, so it can't run tests itself.
  Spend caps and the effort gate apply.

Each trial's record, raw log and diff are written to `<out>/<task>/<agent>/`, and `results.json` has the
summary: pass@1, pass@k (unbiased estimator), mean cost, wall time and tool calls.

**Failure attribution** blames each failed trial on one of three things, with a reason that names its evidence:

- **environment**: the agent couldn't run (CLI missing, login, rate limit), a grading step failed for the
  machine, or the CI-triage rules put the failing output in infra, dependency or timeout
- **grader**: the task was never validated, its reference failed validation, or only the model rubric failed
- **agent**: everything else. Tampering with the hidden tests is noted in the reason

**Export** writes Harbor tasks. Harbor is Terminal-Bench's successor, and Terminal-Bench 2.0 tasks use its format.
The export follows docs.harborframework.com: `instruction.md`, `task.toml` (schema 1.4), `environment/Dockerfile`
with the start state in `/app`, `solution/solve.sh` and `tests/test.sh`. The test script lays the hidden tests
over `/app`, runs the command and checks, and writes 1 or 0 to `/logs/verifier/reward.txt`. Differential, Unity
and rubric graders need GameDevWorkstation, so they're left out of an export and listed under
`graders_not_exported`. `--docker-setup` adds a `RUN` line to the image only, for dependencies the task's
own command expects (for the GDH tasks: `pip install -e . pytest-asyncio respx`). A Unity task's command
runs the Unity CLI, so its image needs Unity and a licence.

**The seed suite** (`evals/suite/`) has 11 tasks forged from GameDevWorkstation's own history and 2 Unity tasks
on the bundled Coin Dash sample, graded with the Unity CLI's EditMode tests and a scene assert. GDH tasks run
with `PYTHONPATH=backend` so the tests import the candidate's code, not the installed app.

A task names every new file its hidden tests use, and the declarations they call, grouped by file. Forge refuses a commit whose description is only a title (pass `--text`): a one-line spec can't say what the tests check. Both rules came from the first agent run on 2026-11-20, which found one task whose test imported a module the prompt never named and one whose 71 tests sat behind a one-line commit title. The second task was dropped from the suite.

Grader validation of the seed suite, run on 2026-11-20 (macOS, Apple M4; the Unity tasks with Unity 6000.3.21f1 through the Unity CLI): every reference passes, and 111 of 168 generated flawed solutions fail (66%; the Unity tasks 15/15). No candidate failed for the environment. Each task's survivors are listed in its `validation.json`. Most are real gaps in the original commit's tests, such as an untested `>=` boundary, a UI handler or a logging flag, so this is a measure of those tests as much as of Eval Forge.

| Task | Kind | Reference | Flawed solutions caught |
|---|---|---|---|
| `automatic-updates-from-github-releases-04bcf2d` | code | pass | 7/15 (47%) |
| `claude-code-sessions-paperclip-attachments-a720afe` | code | pass | 10/13 (77%) |
| `claude-code-sessions-verified-against-the-live-c-153be82` | code | pass | 8/15 (53%) |
| `fix-claude-code-login-detection-on-windows-ba5862a` | code | pass | 9/12 (75%) |
| `fix-what-the-unity-demo-run-turned-up-9157a0f` | code | pass | 11/15 (73%) |
| `new-session-screen-claude-style-composer-claude-a0b6e5f` | code | pass | 11/15 (73%) |
| `read-and-write-text-as-utf-8-on-windows-6347020` | code | pass | 7/11 (64%) |
| `replay-live-recordings-verify-and-render-writes-b4264b2` | code | pass | 10/15 (67%) |
| `replay-make-live-recording-work-end-to-end-7ece383` | code | pass | 5/14 (36%) |
| `skipper-mode-and-central-doc-for-folder-sessions-2447f98` | code | pass | 9/15 (60%) |
| `tune-the-prompt-improver-against-a-real-model-18689d1` | code | pass | 9/13 (69%) |
| `unity-dash-with-cooldown-c1e0f9b` | unity | pass | 8/8 (100%) |
| `unity-streak-bonus-and-coin-field-9606c5a` | unity | pass | 7/7 (100%) |
| **All 13** | | **13/13 pass** | **111/168 (66%)** |

**First agent run** (2026-11-20, UTC 22:35 to 00:22 the next day; macOS, Apple M4). The agent was `claude_code_glm`:
Claude Code 2.1.308 in print mode on Claude Opus 5.5 (`claude-opus-5-5`, read from the CLI's own init event), told that it
may hand easy, high-token side work to GLM-5.3-Flash through `arkcli +chat`. It ran with k=3 on the 13-task suite and
used the account's own `~/.claude` settings, so it measures that Claude Code setup, not a clean install.

| Agent | Tasks | pass@1 | pass@3 | Mean cost | Mean wall | Mean tool calls | Mean helper calls | Failures: agent / env / grader |
|---|---|---|---|---|---|---|---|---|
| claude_code_glm | 13 | 28% | 31% | $1.204 | 388s | 28 | 0.0 | 28 / 0 / 0 |

Passed 11 of 39 trials: both Unity tasks 3/3, UTF-8 3/3 and the live-recording task 2/3. The other nine GDH tasks
were 0/3, so 5 of the 33 GDH trials passed. Costs are the CLI's API-equivalent `total_cost_usd`. All 48 trials in the
run cost $62.65 and took 5.5 hours of agent time, including the six re-runs and the dropped task. Claude never called
the GLM helpers: 0 helper calls in every trial.

What the run showed about the suite, not the agent:

- Three tasks hid things their tests need: one test imported a new module the prompt never named, one needed
  `@functools.cache` on a function whose declaration was listed without it, and one task was a one-line title in
  front of 71 tests. Forge now names the files, keeps decorators and refuses title-only tasks. The two fixable tasks
  were re-forged and re-run (those six trials are in the table). The third was dropped.
- The new-session re-run used the prompt from before the decorator fix, so its 0/3 still includes that gap.
- Tests taken from a real commit check that commit's design, not only the behaviour the task asks for. The
  automatic-updates tests read `Updater.feed` and a `"github"` key in `status()`. A live-recording test greps the
  source for `EditorApplication.EnterPlaymode()`, where `isPlaying = true` does the same job. Other failures were
  real misses: paperclip attachments dropped the `[Attached …]` label blocks the prompt asks for in 3/3 trials.
- A per-failure fairness audit by GLM Flash agreed with a hand check on only one of three sampled cases, so it isn't
  published. Read these scores as a floor for this kind of task, not a measure of the model.

Raw evidence is in `evals/runs/2026-11-20-claude-code-glm/` and `-refix/`: every trial's JSON (grade, blame, cost,
tool calls) and the agent's diff. The stream logs stay local because they're large and carry the machine's setup.

## Agent Review Desk

The Review desk page (sidebar: **Review desk**) is for reviewing what an agent did in an Eval Forge run, the way
you'd review a teammate's pull request. Pick a runs folder (default `evals/runs`) and a run, then a trial. Three panels
sit side by side:

- **Trajectory**: the agent's steps from its CLI log: messages, tool calls with their input and output, errors in red,
  and the final turn count and cost. It reads Claude Code `stream-json` and Codex `--json` logs. Paths are shown
  relative to the agent's working folder.
- **Diff**: the agent's change.
- **Tests**: the task prompt the agent saw and each grading step's result and output.

Below them is the review form:

| Field | What it records |
|---|---|
| Verdict | Accept or reject, as you would a PR |
| Correctness, Maintainability, Test quality | 1-5, each with anchors for 1, 3 and 5 shown under the buttons |
| Failure mode | One of: no failure, missed requirement, wrong behaviour, incomplete, broke existing code, tests weakened, ignored instructions, overreach, environment, grader overreach, other |
| Tags | Any other failure modes that also apply |
| Notes | Free text |

**Compare** opens a second trial of the same task next to the first, so you can choose "Prefer A", "Prefer B" or
"Tie" with a reason. **Ask the model** has a model propose a review from the prompt, the test results, the steps and
the diff, through the effort gate and recorded in usage. The proposal fills the form, marked with its source, and is
saved as that model's review. Saving the form always records a human review under your name.

Everything is stored next to the run's evidence, in two append-only files: `reviews.jsonl` and `preferences.jsonl`.
Nothing changes a trial's own files. `gdw eval run` now also saves the exact prompt each trial saw
(`trial-N.prompt.md`); older runs fall back to the suite's `prompt.md`.

```bash
gdw review export evals/runs/<run> [--out data.jsonl]   # the labelled dataset
gdw review prereview evals/runs/<run> --model <model>  # a model review for every trial without one
gdw review agreement evals/runs/<run>                  # how often it matches the human reviews
```

**The dataset** (`dataset.jsonl`, also from **Export dataset**) has one JSON object per line:

- `"type": "review"`: the latest human review per trial and reviewer, with the task prompt, the diff, whether the
  hidden tests passed, the verdict, scores, failure mode, tags and notes. Model reviews are never exported as labels.
- `"type": "preference"`: both trials' diffs and test results, the winner and the reason, plus `chosen` and
  `rejected` diffs when it isn't a tie (the usual shape for preference training).

**Agreement** pairs the latest human and the latest model review of each trial and reports:
- verdict agreement and Cohen's kappa
- the mean absolute score difference per dimension, and how often the scores are within 1
- failure-mode agreement
- the confusion counts

The page header shows the verdict agreement and kappa once any trial has both reviews. No agreement number is published
here yet: it needs human reviews of a real run first.

## ComfyPlug (ComfyUI generation)

ComfyPlug drives your own ComfyUI like an API. It ships inside the backend (`gamedevworkstation/comfyplug/`, with its
workflow templates) and is the agent's `comfyplug` tool:

| Action | What it makes | Notes |
|---|---|---|
| `check` | nothing | Is ComfyUI answering at the configured address; are comfy-cli and ffmpeg found |
| `image` | a PNG (Qwen Image 2.1) | `aspect`: `1:1 (Square)`, `9:16 (Portrait Widescreen)`, `16:9 (Widescreen)`, `21:9 (Ultrawide)`; `transparent` for an alpha PNG |
| `edit` | a PNG | `image` (an item id or a path) plus an instruction as `prompt`; keeps the input's size, capped near 1 MP |
| `model` | a GLB (Qwen reference image, then TRELLIS.2) | Run `ref_only` first and look at the reference; then rerun with `from_image` set to it |
| `sound` | a WAV (Stable Audio 3 medium) | `seconds`; `variants` N for N takes with seeds seed..seed+N-1; `trim` false keeps the raw clip |
| `workflow` | whatever the workflow outputs: images, video, audio, 3D | Any workflow JSON comfy-cli can run (a path in the session folder, or a bundled template name); `slots` sets node inputs as `{"<node id>.<input>": value}`, `exts` picks the outputs to keep |

`out` sets where the file goes in the session folder (for `workflow`, a folder). Without it, outputs go to the app's
media folder under `comfyplug/`. Every output becomes an item with its prompt and seed, and images come back to the
model so it can check them before using them. Prompts are used as written, so name no brands, franchises, films or shows;
describe the style instead.

ComfyUI runs one prompt at a time, so ComfyPlug runs one job at a time. Each job shows in Jobs and is
recorded in My usage at $0 (it runs on your own GPU). Stopping a turn stops the wait, but a job ComfyUI has
already started finishes on the server.

**Settings** (`[comfyplug]`): `enabled` (default on), `url` (empty means `$COMFY_URL`, else `http://127.0.0.1:8188`;
another machine is `http://<ip>:8188`), `cli_path` (empty means `$COMFY_CLI`, PATH or `~/.local/bin`) and
`timeout_s` (the longest a `workflow` job waits). It needs comfy-cli (`pip install comfy-cli`), plus ffmpeg for sound.
The models are the ones the templates name (Qwen Image 2.1, TRELLIS.2, Stable Audio 3 medium), installed in that ComfyUI.

**From a terminal**, `gdw comfyplug` is ComfyPlug's own CLI, pointed at your `[comfyplug]` settings unless `COMFY_URL`
or `COMFY_CLI` is set. It also has `batch` (a JSON list of jobs that skips outputs that already exist) and the sound
tools `loop`, `normalize` and `measure` (these need numpy). The full command list is in
`backend/gamedevworkstation/comfyplug/README.md`, and `REMOTE_MAC.md` there covers a ComfyUI on another machine.

```bash
gdw comfyplug check
gdw comfyplug image --prompt "a brass gear on a dark table" --out art/gear.png --aspect "1:1 (Square)"
gdw comfyplug workflow my_video_workflow.json --out-dir clips --slot 6.text='"a red fox running"' --ext .mp4
```

## Building the app

```bash
make app        # → dist/GameDevWorkstation.app and dist/GameDevWorkstation.dmg (ad-hoc signed)
make app-test   # builds, launches, checks health + providers + one claude.fast message, quits
```

`make app` (same as `./scripts/build_mac.sh`) does three things:

1. builds the UI
2. freezes the backend with PyInstaller (arm64, onedir)
3. runs `tauri build --target aarch64-apple-darwin`

The frozen backend ships inside the app at `Contents/Resources/backend/`. At launch the app
picks a random free port and a random token, starts the backend, and shows a loading screen
until `/health` answers. Quitting sends the backend SIGTERM. Commands, Codex CLI runs, terminal
tabs and MCP stdio servers run in their own process groups, so the backend keeps a list of them
and ends each group itself (SIGTERM, 1.5 s, then SIGKILL), well inside the 12 s after which the
shell kills whatever is left in the backend's own group. If the app crashes, the backend notices
its parent is gone and shuts down the same way; if that hangs, it ends the children and exits
after 10 s.

The app is signed ad-hoc (`codesign --force --deep --sign -`), so it opens on this Mac
without notarization. The first launch may still need a right-click → Open.

`make app-test` needs a working Anthropic key for the message step. It prints a pass/fail line
per check and a final `RESULT:`. The quit check records every process the backend started (its
process tree plus the groups those processes lead) before quitting and fails if any survive.

## Versions & updates

**One version number.** [`VERSION`](../VERSION) holds it (semver). `scripts/version.py` copies it into
`pyproject.toml`, `uv.lock`, `backend/gamedevworkstation/__init__.py`, `frontend/package.json` and its lock
file, `src-tauri/tauri.conf.json`, `Cargo.toml` and `Cargo.lock`:

```bash
make version                                  # show it
uv run python scripts/version.py bump minor   # or patch / major / set 1.2.3 / check
```

The running version, its git commit and its build time are in **Settings → About & updates**,
in `/health` and in `/api/state`. App builds stamp them into `backend/gamedevworkstation/_build_info.json`.

**See changes live.** `make live` opens the real desktop window from this checkout. The Vite dev
server hot-reloads the UI, so UI edits appear in the window as you save. The shell starts the
backend with `uv run gamedevworkstation` from the repo, so backend edits apply after you restart
`make live`. It needs Rust, and the first run compiles the shell, which takes a few minutes. In
a browser, `make backend` + `make ui` still work too.

**Ship a version: `make release`.** After you approve a change, the developer agent (or you)
runs:

```bash
make release                         # 0.1.0 -> 0.1.1
make release BUMP=minor              # or BUMP=major, or VERSION=1.0.0
make release NOTES="Faster startup"  # or NOTES_FILE=notes.md; default: commits since the last tag
```

It refuses to run with uncommitted changes. Then it:

1. bumps the version and commits `Release vX.Y.Z`
2. builds the app into `build/release-X.Y.Z/`, never over the app you're running
3. checks the signature and version
4. copies it to the updates folder
5. writes `release.json`, and writes `latest.json` last
6. tags `vX.Y.Z` and prunes old versions

If the build fails, the release commit stays untagged. Fix the build and run
`make release VERSION=X.Y.Z` again.

**The updates folder** is `~/GameDevWorkstationUpdates`. Change it with `[updates] dir` in `config.toml`.

```
~/GameDevWorkstationUpdates/
  latest.json                 # newest release; written atomically, after the app is fully copied
  0.1.1/GameDevWorkstation.app
  0.1.1/release.json          # {version, built_at, git_commit, notes}
  .previous/GameDevWorkstation-0.1.0.app   # the version you replaced, for rollback
  installed.json              # every app bundle that has run: {installs: {path: {version, at}}}
```

`keep = 3` versions stay. Pruning never removes the newest version, or the version of any app
bundle listed in `installed.json` that still exists (plus `/Applications/GameDevWorkstation.app`). Each app
records its own path when it starts, so a test build launched from `dist/` can't hide the version
in `/Applications`; entries whose bundle was deleted are ignored. Writes are atomic and use a
short lock file, so two apps starting at once can't corrupt it. The old single-record format is
read and converted on the next write.

**How the app finds out.** Every 30 seconds (`check_interval_s`) the backend stats
`latest.json`, and it only reads the file when it changed, so idle cost is close to zero. When
there's a newer version you get:

- a macOS notification (once per version)
- a toast
- a one-line **Update vX.Y.Z ready · Install** banner above the sidebar footer. When the running
  copy can't install updates (running from source), it reads **Update vX.Y.Z available · What's
  new** and the dialog shows the notes and why there's nothing to install
  (`install_supported` in the update state)

The banner also comes back after a reload or relaunch. **Settings → About & updates** has
**Check now**, the release history with notes and a button to reveal the folder in Finder.

**Install & restart.** Click the banner and then **Install & restart**:

1. The backend checks the new bundle: version, identifier and `codesign --verify --deep --strict`.
2. It copies the bundle next to the running app.
3. It starts a small helper outside the app's process group, then answers the UI, which shows
   "Restarting…".
4. The helper asks GameDevWorkstation to quit. If it's still running after 30 s, it stops it.
5. The helper moves the current app to `~/GameDevWorkstationUpdates/.previous/` and puts the new one in
   its place. Then it clears quarantine attributes and opens it.

If the new version is missing or doesn't start, the helper puts the old app back and reopens
it. The log is `~/Library/Logs/GameDevWorkstation/update.log`.

**Roll back to previous** (same page) swaps in the kept version the same way. Rolling back
again goes forward. Install only works in the built app; when you run from source, the page
says so.

**First install.** An app built before this feature can't update itself. Install once by
hand, then updates arrive in-app:

```bash
make release
make install APP=~/GameDevWorkstationUpdates/<version>/GameDevWorkstation.app   # quit GameDevWorkstation first
```

`make install` with no `APP` installs `dist/GameDevWorkstation.app` from `make app`.

<!-- rename:keep-start -->
## Upgrading from Workspace 0.4

GameDevWorkstation is the app that was called Workspace up to 0.4. It has a new name and bundle
id (`dev.local.gamedevworkstation`), so it installs next to `Workspace.app` instead of replacing
it, and the in-app updater of 0.4 can't offer it. Install it once by hand, with Workspace quit:

```bash
make app && make install      # dist/GameDevWorkstation.app -> /Applications
```

On its first start it brings everything over. Nothing of the old app is changed or deleted, so
Workspace 0.4 keeps working with its own data:

- **Data.** `~/Library/Application Support/Workspace/` is copied to
  `~/Library/Application Support/GameDevWorkstation/` (settings, database, media, transcripts),
  unless the new folder already holds a database. Paths into the old folder are updated in the
  copy. Logs now go to `~/Library/Logs/GameDevWorkstation/`.
- **API keys and MCP secrets.** Each is read from Keychain service `Workspace` the first time
  it's needed and copied to service `GameDevWorkstation`. macOS may ask once per key whether
  GameDevWorkstation may use it: choose **Always Allow**. A key you delete in the new app stays
  deleted there.
- **Projects.** A project's `.workspace/` folder is renamed to `.gamedevworkstation/` the first
  time you use the project (the log says so). Hook trust carries over. If the folder is tracked in
  git, commit the rename.
- **Updates folder.** If `~/GameDevWorkstationUpdates` doesn't exist yet, the releases in
  `~/WorkspaceUpdates` are copied there in the background. New releases go to the new folder.
- **Subagent worktrees.** Worktrees still open in 0.4 aren't moved (a copied git worktree
  breaks): they stay in the old data folder, and their `workspace/<unit>` branches stay in your
  repositories. New units use `gdw/<unit>`. Merge or discard pending units in Workspace 0.4
  before switching, or merge those branches by hand.
- **For development.** Environment variables `WORKSPACE_*` are now `GDW_*` (for example
  `GDW_FAKE_PROVIDERS`, `GDW_KEY_<PROVIDER>_<PROFILE>`, `GDW_HOME`), the Python package is
  `gamedevworkstation`, and the dev command is `uv run gamedevworkstation` (or `uv run gdw`).
  Skills marked `runtime: workspace` still count as native.

When you are happy with GameDevWorkstation, remove `/Applications/Workspace.app` yourself. The
old data folder, `~/WorkspaceUpdates` and the Keychain entries of service `Workspace` stay until
you delete them.
<!-- rename:keep-end -->

## Testing

```bash
make test         # backend tests + UI typecheck; no network
make test-live    # real API smoke tests, skipped per provider when its key is missing
```

The unit tests use recorded fixtures for adapter translation (tool calls, media, usage, effort
parameters). They also cover:

- above-high effort rejected without a token
- auth states, including that models of a failed provider never show as online
- the item index: tabs, provider filter, session groups and scoped search
- the delegation test: three independent units in parallel, routed per the table, separate
  worktrees for code units, stats written
- MCP with a real stdio server
- session management (`tests/test_sessions_mgmt.py`):
  - migrating an old database keeps its data and backfills the search index
  - groups, bulk actions, Trash (restore, purge, auto-purge by age), archive views
  - duplicate and fork (resume ids not copied), unread state, title and message search
  - auto-titles: `claude.fast` at low effort through the adapter, usage recorded, a failing
    provider never fails the turn
- the Skills & MCP assistant: creating a skill, refusing to overwrite one, approval before
  adding an MCP server (declining adds nothing), the effort gate, installing from a URL
- scheduled tasks (Schedule) and Settings
- the task board (`tests/test_task_board.py`): codes handed out in order and never reused,
  also from two connections at once; code parsing; the tools, with subtask ops all or nothing,
  Plan only mode and subagents; search filters including due dates; events; the REST API
- the Codex CLI harness against a fake `codex` binary, and the Agent SDK harness with a
  stubbed `query`
- updates: version order, `latest.json` detection (announced once, half-written files ignored),
  install refused from source, and the swap helper against a fake signed bundle. The swap test
  covers install, a failed launch that restores the old app, and rollback. `version.py`
  bumping every file is tested too.
- the prompt improver (`tests/test_pi_eval.py`): the corpus schema (24/24 split, unique ids, topics from
  the question bank), the regression gates (vague ask-rate at least 0.80, clear false-asks at most 0.10, at
  most 2 calls and 3 cards per prompt, mean clear overhead at most 2,500 estimated tokens) and every
  bypass reason code. These run on a scripted fake model, so they test orchestration only; the one
  measured real-model run is in "Prompt improver" above.
- CI failure triage:
  - `tests/test_triage_rules.py`: each rule and log format, precedence, NUnit limits, slow-regex
    inputs, and the Markdown escaping, so a log can't add mentions or links to a PR comment.
  - `tests/test_triage_fixtures.py`: accuracy against the labelled logs.
  - `tests/test_ci_triage.py`: the CLI, the route, and the model fallback with a fake provider,
    including the effort gate.
  - `tests/test_triage_workflow.py`: the workflow's trigger and permissions, and that it never
    checks out pull-request code.
  - record/replay (`tests/test_replay_*.py`): golden archive parsing, checkpoint comparison with
    deterministic vectors, ffmpeg argv/ranges, request validation, permissions, route/job fakes,
    install modified-file refusal, media/gallery deduplication, L3 stale/forged/unscoped evidence
    rejection. None of it launches Unity.

## Where things live

| What | Where |
|---|---|
| Config | `~/Library/Application Support/GameDevWorkstation/config.toml` |
| Database (SQLite + FTS5 for items and message text), media, subagent transcripts, worktrees | `~/Library/Application Support/GameDevWorkstation/` |
| Logs | `~/Library/Logs/GameDevWorkstation/` (`backend.log`, `backend-stdout.log` + 3 previous, `update.log` for installs) |
| App versions (`make release`) | `~/GameDevWorkstationUpdates/` |
| API keys | macOS Keychain, service `GameDevWorkstation` |
| Running backend's port/token (owner-only, removed on quit) | `~/Library/Application Support/GameDevWorkstation/runtime.json` |

The data and log folders are owner-only (0700) and the database, config, `runtime.json` and logs
0600; the backend sets this at startup. The app passes the backend its token in the environment
(`GDW_TOKEN`), not on the command line.

## Notes and differences from the original spec

- **No Codex API models anymore.** OpenAI has retired its `*-codex` API models
  (`gpt-5.3-codex`, the last one, shuts down 2027-04-01), and Codex now runs on the GPT-6 family.
  The `codex.*` tiers therefore map to GPT-6.1 Sol (`gpt-6.1-sol`, fast, standard and CLI),
  GPT-6.2 Sol (`gpt-6.2-sol`, deep), and GPT-6.1 Terra (`gpt-6.1-terra`, computer);
  GPT-6 Astra and GPT-6 Luna are in the catalog too. Change them in Settings → Models, which lists the OpenAI tiers with their models' real names.
- **No thinking.** The "lowest / no-thinking" effort level maps per model: Haiku 5.5 →
  `thinking: disabled`, Sonnet 5.5 → `between_tools`, Opus 5.5 → `low` (it can't turn thinking
  off), GPT-6.1 Sol / GPT-6.2 Sol → `low` (they reject `none`), Terra/Luna → `none`.
- **Codex CLI sandbox flag.** The CLI dropped `--full-auto`, so GameDevWorkstation uses
  `--sandbox workspace-write` (or `read-only` in Plan mode).
- **ElevenLabs defaults** are `eleven_v4` for speech and `scribe_v2` for transcription
  (`scribe_v1` is deprecated). Sound effects use `eleven_text_to_sound_v3` and music uses
  `music_v2_5`.
- **"Sidecar".** The PyInstaller onedir output is a folder, not a single file, so it is bundled
  as an app resource and started by the shell. It behaves like a Tauri sidecar.
- **Not yet run against live APIs.** Live calls and the Codex CLI resume path haven't been
  exercised. Everything was built in a sandbox without API keys, against recorded fixtures and
  each provider's current docs. `make test-live` and `make app-test` are the first runs against
  real APIs.

## Troubleshooting

- **"GameDevWorkstation's engine stopped"** — the backend exited. The screen shows its exit code, the end
  of `~/Library/Logs/GameDevWorkstation/backend-stdout.log` and **Restart**. The app notices at once (at
  startup and while running) instead of waiting or showing "Reconnecting…". That log starts fresh
  at every launch; the previous three are `backend-stdout.log.1` to `.3` (5 MB each at most).
- **A CLI tool isn't found from the app** — GUI apps don't inherit your shell's PATH. The
  backend reads PATH from `zsh -lic` at startup and adds `/opt/homebrew/bin`. Make sure the tool
  is on your login shell's PATH.
- **Microphone** — macOS asks the first time you press Record. To change it later, go to System
  Settings → Privacy & Security → Microphone.
- **Codex CLI harness shows "not installed"** — run `npm i -g @openai/codex`, then restart the app.
- **Claude Code (subscription) shows "not installed" or "Not logged in"** — Settings → Claude Code
  shows which `claude` it found (set **CLI path** if it's somewhere else) and the result of
  `claude auth status`. Log in with `claude auth login` in a terminal, then press **Retry** on the
  card. If a session stops working after a Claude Code update, the turn's log in Background tasks
  and the error card show the CLI's redacted message. Hook initialization failure ends the process
  with an error, without silently falling back. It was checked against Claude Code 2.1.308; after an
  update, compare the CLI's output with the captures in `tests/fixtures/claude_stream/`.
- **Trailer: "ffmpeg not found"** (exit code 3) — `brew install ffmpeg`, or set `TRAILER_FFMPEG` to the ffmpeg
  binary. `python3 skills/trailer-maker/scripts/trailer_edl.py doctor` shows what it found.
- **Trailer: the Recorder never starts** — the Editor was in batchmode (use the GUI editor), the project has compile
  errors, the Game view is hidden, or `com.unity.recorder` isn't installed. With the URP 2D Renderer only the Game
  view can be recorded (the template does that). No audio in takes: set Default Speaker Mode to Stereo; FMOD/Wwise
  audio isn't captured.
