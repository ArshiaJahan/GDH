# GameDevWorkstation: the full guide

> The complete manual for GameDevWorkstation. For the overview,
> see the [README](../README.md).

A personal agent workstation for your Mac. Claude is the main agent: it plans jobs and hands
units of work to Claude and OpenAI (Codex) subagents in parallel, picking the model tier and
thinking effort per unit to keep things fast and cheap. ElevenLabs handles speech,
transcription, sound and music. Everything runs locally; the backend listens on 127.0.0.1 only.

## Contents

- [Prerequisites](#prerequisites)
- [Setup and development](#setup-and-development)
- [Adding API keys](#adding-api-keys)
- [Configuration](#configuration)
- [Pages and panels](#pages-and-panels) (and [Gallery](#gallery))
- [Task board](#task-board)
- [Campaigns and workflows](#campaigns-and-workflows)
- [Sessions](#sessions)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [How delegation works](#how-delegation-works)
- [Built-in skills](#built-in-skills) (and [Unity: MCP or CLI](#unity-mcp-or-cli))
- [Building the app](#building-the-app)
- [Versions & updates](#versions--updates)
- [Upgrading from Workspace 0.4](#upgrading-from-workspace-04) <!-- rename:keep -->
- [Testing](#testing)
- [Where things live](#where-things-live)
- [Notes and differences from the original spec](#notes-and-differences-from-the-original-spec)
- [Troubleshooting](#troubleshooting)

## Prerequisites

| Tool | Why | Install |
|---|---|---|
| macOS 13+ on Apple Silicon | target platform (built for an M4 Air) | |
| Xcode Command Line Tools | compiler, `codesign`, `git` | `xcode-select --install` |
| Rust (stable) | builds the desktop shell (Tauri v2) | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Node 20+ | builds the UI | `brew install node` |
| uv | Python 3.11+ backend | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Codex CLI (optional) | `codex.cli` subagents and the Codex CLI harness | `npm i -g @openai/codex` |
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
- `[tiers]` what `claude.fast / standard / deep` and `codex.fast / standard / cli` mean. Defaults:

  | Tier | Model | Shown as |
  | --- | --- | --- |
  | `claude.fast` | `claude-haiku-5-5` | Haiku 5.5 · claude.fast |
  | `claude.standard` | `claude-sonnet-5-5` | Sonnet 5.5 · claude.standard |
  | `claude.deep` | `claude-opus-5-5` | Opus 5.5 · claude.deep |
  | `codex.fast` | `gpt-6.1-terra` | GPT-6.1 Terra · codex.fast |
  | `codex.standard` | `gpt-6.1-sol` | GPT-6.1 Sol · codex.standard |
  | `codex.cli` | `gpt-6.1-sol` (passed to `codex exec`) | GPT-6.1 Sol · codex.cli |

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
  (sessions in Trash are deleted for good after this many days, default 30) and
  `event_retention_days` (how long the event log keeps events, default 7; see Settings → Storage).
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
`/skill`, `/task` (see [Task board](#task-board)) and `/workflow` (see
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

**Side panel**, per session, in this order. Until you show or hide it yourself, it's open in
windows at least 1200 px wide and closed in narrower ones:

1. **Environment** — where it runs (Local), folder, model and effort, account profile per provider,
   mode, harness. The harness picker is locked while the session runs a campaign or workflow
   (they need the built-in loop).
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
6. **Gallery** — the images, videos and audio this session generated, plus Unity screenshots on
   request (see [Gallery](#gallery)).
7. **Changes** — changed files (git diff in a repo, including subagent worktrees; snapshots
   otherwise), +/− counts, side-by-side diff and per-file revert. Files over 5 MB aren't
   snapshotted: they're listed as "too large to snapshot", without diff or revert. Each subagent worktree has
   **Discard worktree** (removes it and its `gdw/<unit>` branch; asks again, saying what
   would be lost, when it holds work that isn't merged).
8. **Background tasks** — subagents, commands, Codex CLI runs and ElevenLabs jobs with a log
   tail and cancel.

### Gallery

The **Gallery** card sits in the side panel under **Outputs**. It shows what the session *generated*
(media items from the agent, its tools and commands that announce `ARTIFACT:` / `TRAILER_OUTPUT:` lines;
your own attachments are left out) as a strip from left to right, newest first. The mouse wheel
scrolls it sideways. Click an image or a video to open it larger, with its prompt, how it was captured
and **Open in Finder**. Videos and audio show a play badge.

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

**Starting a workflow.** In the composer type `/workflow <id> <what to do>`, or `/workflow <id>`
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

**Harness.** Campaigns and workflows use the built-in loop (their tools, autopilot and gates live
there): a workflow can't start in a session on another harness, and the harness picker is locked
while one runs.

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

**New session (+ or ⌘N)** reuses an untitled session without messages in the same group instead
of adding another empty "New session".

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
| `grill-me` | A relentless interview to sharpen a plan or design (uses `grilling`) |
| `claude-handoff` | Writes a handoff summary and starts a fresh background agent with it |
| `game-designer` | Game design partner, with references, templates and a calculator script |
| `cost-effective-claude-delegation` | Does a task at the lowest total cost, step by step |
| `high-performance-claude-delegation` | Runs independent units in parallel on Opus at high effort, then an Opus reviewer |
| `unity-router` (featured) | Unity game pack entry point: picks which Unity skills to load for a task and uses the route the harness reports (MCP, Unity CLI live or batch); see [`skills/unity-router`](../skills/unity-router/SKILL.md) |
| `compile-fix-loop`, `play-verify`, `headless-ops`, `scene-prefab-safety`, `gdd-to-backlog`, `project-memory`, `architecture-patterns`, `asset-pipeline`, `perf-pass`, `game-feel-pass`, `build-ship`, `vcs-hygiene` | The rest of the Unity 6 game-creation pack: compile/fix, Play Mode checks, headless builds and tests, safe scene/prefab edits, GDD to backlog, project memory, architecture templates, asset pipeline, performance, game feel, shipping and git hygiene (with scripts, templates and references) |
| `unity-mcp-orchestrator` | MCP for Unity tool reference and workflows, used by the Unity pack |
| `trailer-maker` | Game trailers from real gameplay: brief, beat sheet, shot list captured in Play Mode with the Unity Recorder, an ffmpeg edit from a JSON edit list, ElevenLabs music/VO/SFX cut to the beat sheet, three reviewers, and Steam/YouTube/vertical exports; see [`skills/trailer-maker`](../skills/trailer-maker/SKILL.md) |

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
  The `codex.*` tiers therefore map to GPT-6.1 Terra (`gpt-6.1-terra`, fast) and GPT-6.1 Sol
  (`gpt-6.1-sol`, standard and CLI); GPT-6 Astra and GPT-6 Luna are in the catalog too. Change
  them in Settings → Models, which lists the OpenAI tiers with their models' real names.
- **No thinking.** The "lowest / no-thinking" effort level maps per model: Haiku 5.5 →
  `thinking: disabled`, Sonnet 5.5 → `between_tools`, Opus 5.5 → `low` (it can't turn thinking
  off), GPT-6.1 Sol → `low` (it rejects `none`), Terra/Luna → `none`.
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
- **Trailer: "ffmpeg not found"** (exit code 3) — `brew install ffmpeg`, or set `TRAILER_FFMPEG` to the ffmpeg
  binary. `python3 skills/trailer-maker/scripts/trailer_edl.py doctor` shows what it found.
- **Trailer: the Recorder never starts** — the Editor was in batchmode (use the GUI editor), the project has compile
  errors, the Game view is hidden, or `com.unity.recorder` isn't installed. With the URP 2D Renderer only the Game
  view can be recorded (the template does that). No audio in takes: set Default Speaker Mode to Stereo; FMOD/Wwise
  audio isn't captured.
