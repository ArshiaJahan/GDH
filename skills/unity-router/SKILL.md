---
name: unity-router
description: Picks which Unity game-creation skills to load for a task (at most 3, in order) and whether to use MCP for Unity (editor open) or batchmode (editor closed, CI); holds the idea -> playable build pipeline for Unity 6 (6000.3) 2D roguelikes. Use when starting any Unity task or session, when unsure which skill applies, when a pipeline stage or milestone ends, or for "make a game" or "what next".
---

# unity-router

Choose the smallest skill set for the task, choose MCP or batchmode, and keep the idea -> build pipeline moving.

Pinned: Unity 6000.3 LTS (tested 6000.3.21f1, macOS), URP 17.3 2D Renderer, MCP for Unity 10.3.0 (CoplayDev), batchmode via `/Applications/Unity/Hub/Editor/<ver>/Unity.app/Contents/MacOS/Unity`.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. mcp__UnityMCP__read_console). For tool parameters see unity-mcp-orchestrator.

## When to use
- Start of every Unity task or session, and whenever the task changes stage (design -> plan -> build -> verify -> ship).
- Not needed inside a skill that already says which skill to call next.

## Procedure
1. Read `PROJECT.md` at the project root if it exists (current milestone, conventions, commands). If it does not exist and the task touches a project, include project-memory.
2. Pick the execution mode (next section).
3. Match the task to the first fitting row of the routing table. If several rows fit, take the earliest pipeline stage first.
4. Load the listed skills in order, at most 3 at once (Context budget below). Load unity-mcp-orchestrator only when you need tool parameters or a tool call fails.
5. State the route (Verify step 1), then work.
6. When the stage is done (its skill's Verify passed), drop that skill and route again for the next stage.

## Execution mode: MCP or batchmode
In GameDevWorkstation the harness decides this for you (the user's **Unity backend**: auto | mcp | cli) and tells you the
route: the project context has a line like `Unity: backend=cli route=cli_batch (Editor closed; Unity CLI 1.0.0-beta.13)`,
checked at session start. Call the `unity` tool with `op="status"` only when it says `route=unknown` or after the editor
opens or closes (routes: `mcp`, `cli_live` = official Unity CLI against the
open Editor, `cli_batch` = Unity CLI batch run, `raw_batch` = headless-ops unity.sh, or `unavailable` with the reason).
Then use the `unity` tool for compile / test / build / exec / eval / screenshot / play on every route, and the MCP for
Unity tools only when the route is `mcp` (with the `cli` backend they are off). Never switch the backend yourself; if
the route is `unavailable`, tell the user the reason (the chip under the composer offers the fixes). Outside GameDevWorkstation:
Decide once per session and again after the editor opens or closes.
1. Read the resource `mcpforunity://instances`. If the target project is listed: `set_active_instance(instance="<Name>@<hash>")`, read `mcpforunity://editor/state`, wait for `ready_for_tools == true`. Mode = MCP.
2. Not listed: check for an editor that has the project open:
   `pgrep -fil "Unity.app/Contents/MacOS/Unity.*-projectpath .*/<ProjectFolderName>( |$)"` (case-insensitive, so `-projectPath` and the Hub's `-projectpath` both match [UNVERIFIED: exact Hub spelling]; matching on the folder name also covers `/tmp` vs `/private/tmp`).
   - Running, but MCP not listed: do not start batchmode (Unity refuses a project that is open). Ask the user to start the MCP bridge in the editor (Window > MCP for Unity) or to close the editor.
   - Not running (also when only a stale `Temp/UnityLockfile` remains): Mode = batchmode through headless-ops.
3. CI, SSH, or no display: Mode = batchmode, always.
4. Needs the running game in an editor (play-verify, screenshots, live profiling, game-feel tuning) but Mode = batchmode: ask the user before opening the editor. Otherwise turn the check into a PlayMode test, or mark it for the next MCP session.

| Need | MCP (editor open) | Unity CLI live (editor open, com.unity.pipeline) | Batchmode (editor closed) |
|---|---|---|---|
| Compile check | compile-fix-loop with `read_console` | `unity` tool `op=compile` (`unity recompile`) | compile-fix-loop with `unity` tool `op=compile` / headless-ops compile run |
| EditMode/PlayMode tests | `run_tests` + `get_test_job` | `unity` tool `op=test` (Pipeline run_tests job) | `unity` tool `op=test` / headless-ops `-runTests` (never with `-quit`) |
| Look at the running game | play-verify | `unity` tool `op=play`, `op=screenshot`, `op=eval` | not possible; PlayMode test or later |
| Scene/prefab edits | scene-prefab-safety via MCP tools | `unity` tool `op=command` (Pipeline scene/GameObject commands; `op=commands` lists them) | scene-prefab-safety via `-executeMethod` entry point |
| Player build | build-ship via `manage_build` | close the editor first | build-ship via `unity` tool `op=build` / headless-ops |

## Routing table
Signals are words or situations in the task. Load in order, at most 3. "Skip" lists skills that look related but are not needed now.

| # | Task signals | Load (in order) | Skip |
|---|---|---|---|
| 1 | game idea, "make a game", no GDD, pitch, design a mechanic, balance, tuning numbers | game-designer | all Unity skills until a GDD or spec exists |
| 2 | GDD or spec ready, plan, milestones, backlog, tickets, scope, "what first" | gdd-to-backlog, project-memory | implementation skills |
| 3 | new or unfamiliar project, first session, "where are we", handoff, record a decision, conventions | project-memory | everything else until PROJECT.md is current |
| 4 | git setup, .gitignore, LFS, merge conflict in .unity/.prefab/.meta, commit/branch hygiene | vcs-hygiene | scene-prefab-safety (unless repairing YAML by hand) |
| 5 | implement a system: player, enemy, combat, data (ScriptableObjects), events, input, save, scene loading, procgen, UI flow | architecture-patterns, compile-fix-loop | perf-pass, game-feel-pass, build-ship |
| 6 | compile errors, red console, "doesn't build", after any script edit | compile-fix-loop (+ headless-ops if batchmode) | play-verify until clean |
| 7 | "does it work", check a story, acceptance criteria, Play Mode, screenshot, runtime exception | play-verify (+ compile-fix-loop if not clean) | headless-ops when MCP is available |
| 8 | run tests, CI, batchmode, editor closed, `-executeMethod`, import from CLI, nightly | headless-ops | play-verify |
| 9 | edit scenes or prefabs, wire references, missing script/reference, GUID, .meta, move/rename assets | scene-prefab-safety (+ unity-mcp-orchestrator for parameters) | asset-pipeline unless import settings change |
| 10 | import sprites/audio, pixel-art settings, atlas, placeholder art, Addressables, import presets | asset-pipeline (+ scene-prefab-safety if prefabs get rewired) | perf-pass unless memory or draw calls are the problem |
| 11 | low FPS, stutter, GC spikes, draw calls, batches, physics cost, memory, load time | perf-pass, play-verify | game-feel-pass |
| 12 | feels flat, juice, hit-stop, screen shake, flash, particles, feedback, impact | game-feel-pass, play-verify | perf-pass unless the frame budget is at risk |
| 13 | build, release, version, changelog, ship, itch, smoke test the player | build-ship, headless-ops | play-verify unless the smoke test needs the editor |
| 14 | MCP call fails, tool missing, wrong instance, parameter shape, tool groups | unity-mcp-orchestrator | everything else until the call works |
| 15 | critique, taste, aesthetic review, TASTE.md, L4 review | design-critique | implementation skills until the review identifies changes |
| 16 | failure analysis, postmortem, exhausted gate, parked campaign, "that broke" | postmortem | implementation skills until the cause and prevention rule are recorded |
| 17 | trailer, teaser, announce/launch/festival video, Steam trailer, gameplay capture, b-roll, social clip, vertical cut, press-kit GIF | trailer-maker (+ unity-mcp-orchestrator on demand) | game-feel-pass, play-verify (unless a shot needs a scripted-input fix) |

## Workflows and gates
Chains are workflow templates run by the harness in one session; they are a harness feature, not additional skills. Campaigns span multiple sessions and keep their durable brief, design target and continuation state in `.gamedevworkstation/campaigns/<slug>.md` at the project root. Use the matching template:

| Template | Workflow |
|---|---|
| `new-mechanic` | Spec → Backlog → Build → Verify → Commit |
| `bugfix` | Repro with a test failing for the right reason → Fix → Verify (repro passes; play evidence if visual) → Commit |
| `juice-pass` | Baseline screenshots → game-feel-pass → Verify before/after → Critique → Commit |
| `content-batch` | Plan items → Produce → Wire → Verify (compile, behaviour tests, content lint) |
| `perf-pass` | Baseline → Fix loop → Compare with perf_report; anti-pattern audit blocks regressions |
| `release` | Freeze completed milestone → Full tests → Build → Headless smoke → Spec-audit critique against milestone exit → Changelog/tag |
| `replace-system` | Build beside → Parity verify with screenshots and metrics → Switch → Remove old in a separate phase (ask before deletion) |
| `milestone` (campaign only) | One phase per current-milestone story in BACKLOG order → Milestone exit |
| `trailer` | Brief → Beat sheet → Shot list → Capture → Rough cut → Music/VO → Trailer review → Exports |

The quality ladder requires fresh, observed evidence for the story after its latest relevant change:
- **L1 compile:** 0 compile errors.
- **L2 behaviour tests:** passing EditMode/PlayMode tests for the story's criteria.
- **L3 play evidence:** play-verify `check_criteria.py ... --only <IDs>` passes, including CONSOLE. If `*.cs`, `*.unity` or `*.prefab` changed, completion needs fresh screenshots for the story's AC IDs in that run's `shots/`, newer than the last relevant change.
- **L4 critique (opt-in):** design-critique for `Critique: yes`, milestone exit when required, juice-pass and release; a behavioural failure still blocks completion.

The harness enforces these; don't fight a gate, fix the cause. Read `TASTE.md` at the project root for aesthetic and feel targets, and `POSTMORTEMS.md` at the project root for recorded failures and prevention rules.

## Default pipeline: idea -> playable build
Run the stages in order. Each stage ends when its skill's Verify passes.
1. gdd-to-backlog: GDD -> BACKLOG.md (M0..M4), lint OK. (No GDD: game-designer first.)
2. project-memory: PROJECT.md created or refreshed, pointer to the current milestone, `--check` OK.
3. vcs-hygiene: .gitignore, LFS, UnityYAMLMerge driver, first commit.
4. architecture-patterns: skeleton for M0 (folders, asmdefs, Boot -> Title -> Game, input, save stubs).
5. Per-milestone loop, for each story of the current milestone in BACKLOG.md order:
   1. Load the story's `Owner skill` and implement.
   2. compile-fix-loop until the console has 0 errors (or its attempt limit, then stop and report).
   3. Verify each criterion by its test type: EditMode/PlayMode -> `run_tests` (MCP) or headless-ops (batchmode); play-verify -> play-verify; headless -> headless-ops/build-ship; manual -> ask the user and record the answer.
   4. Mark the story `done` in BACKLOG.md. At milestone exit: project-memory (pointer, verification result), commit (vcs-hygiene rules), next milestone.
6. As needed inside milestones (usually M3/M4): asset-pipeline, game-feel-pass, perf-pass.
7. build-ship: release builds per target, smoke test, version, changelog.

Stop and ask the user when: the GDD lacks a decision a story needs, compile-fix-loop hits its attempt limit, a manual criterion is due, or a step would delete or overwrite user content.

## Context budget
- At most 3 task skills loaded at once (this router not counted). Prefer 1-2.
- Load a skill's references only when its "read when" hint matches the current step.
- Drop a skill (stop following it, do not reread it) when its stage is done. Re-route instead of stacking.
- unity-mcp-orchestrator counts toward the 3 and is loaded on demand only (parameters, failures).
- Pass state between stages through files, not memory: BACKLOG.md (what), PROJECT.md (how and why), test results and logs (proof).

## Rules
- **layer, don't replace:** route system, prefab or scene replacement to the `replace-system` workflow; build beside the old version, verify parity with play-verify, then remove the old in a separate step with user approval.
- **Design target, not delta:** define the observable finished state and verify the whole agreed target; "improve X" or "refactor Y" alone is not a completion criterion.
- Never run batchmode on a project that an editor has open. Never run two batchmode Unity processes on the same project.
- Prefer MCP when the editor is open; it is faster and shows the running game.
- Do not skip compile-fix-loop after script changes, even for "small" edits.
- A story is done only when every criterion's signal was observed. "Should work" is not a signal.
- ⚠ version-sensitive: tool names and groups are from MCP for Unity 10.3.0. If a tool is missing, check tool groups (`manage_tools`) before assuming it does not exist (route 14).

## Verify
1. Before working, state the route in one line:
   `ROUTE: <skill1>, <skill2> | mode: MCP <instance> | batchmode | reason: <task signal -> table row #>`.
   Pass: at most 3 skills, each from the routing table row you cite, mode decided by the Execution mode rules.
2. Check that each named skill exists: `python3 <skill-dir>/scripts/check_skills.py <skill1> <skill2>` (or `--all` for the full set; `--list` shows where each was found). Pass: exit code 0 and `RESULT: OK`. If your client lists available skills instead of a filesystem, confirm every named skill appears in that list. A MISSING skill: say so, fall back to unity-mcp-orchestrator plus the skill's scope from the routing table, and tell the user.
3. MCP mode only: `mcpforunity://editor/state` shows `ready_for_tools: true` for the instance you set. Batchmode only: the `pgrep` command above prints nothing.
