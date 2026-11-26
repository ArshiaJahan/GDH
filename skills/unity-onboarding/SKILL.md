---
name: unity-onboarding
description: Onboards a session onto a Unity project before any work - one cheap scan (cached, so repeats only re-read what changed) of the project's rules, handoff and central docs, Unity facts, tools (graphify graph, MCP for Unity, tests, CI), git state and prefabs (fills GameDevWorkstation's Prefabs tab, one category per folder, and flags variants with a missing base), then lists the open to-dos and asks the user which one to do. Use at the start of a session or handoff, "where are we", "get up to speed", "onboard", "orient yourself", or when picking up a project you haven't seen.
index-hint: "Onboard / orient yourself in a Unity project (start or handoff): map docs, tools, git, prefabs and open to-dos cheaply, then ask which to do. 'where are we', 'get up to speed'."
argument-hint: "[project folder]"
---

# unity-onboarding

Get ready to work with the fewest tokens: one script for the map, targeted reads for the rest, and the user picks the work. `<skill>` = this skill's folder.

## 1. Scan (one call)
`python3 <skill>/scripts/onboard.py <project or parent folder>`
- `CACHED`: nothing changed since the last onboarding. Use the printed map and don't re-read the docs; go to step 3.
- Fresh scan with `**CHANGED**` docs: re-read only those docs.
- Several Unity projects found: ask which one, then rerun on it.
- `## Prefabs`: fills the Prefabs tab's categories, one per folder (a user's own are kept). A variant with a missing base is a blocker. Don't open prefabs or render thumbnails here.
- `RESULT: FAIL`: no Unity project. Ask where it is, or offer unity-router to make one.

## 2. Read, in this order, and stop as soon as you know enough
1. Rules: AGENTS.md / CLAUDE.md, unless already in your context. They win over everything below.
2. The central handoff doc (HandOffDocs/README.md, HANDOFF.md, claude-progress.txt): current state, next steps, gotchas. For a session log, read only the newest entry (the script prints it).
3. PROJECT.md: conventions, commands, current milestone. If it's missing or stale, note it as a to-do for project-memory.
4. BACKLOG.md: only the active milestone's section (`grep -n "^## M" BACKLOG.md`, then read that range). Never the whole file.
5. Everything else (design docs, TASTE.md, POSTMORTEMS.md, docs/): headings only, and only when the user's choice needs them.

Targeted lookups, not tours:
- With a fresh graphify graph, answer "where is X / what uses Y" with graphify query, path or explain.
- Otherwise use `rg -n` on symbols and file names. Don't open scenes, prefabs or whole Assets folders during onboarding.

Details and the reasons behind them: `references/practices.md`. Read it only if you're unsure.

## 3. Check readiness (cheap, no builds)
- In GameDevWorkstation, the context pack's `Unity:` line gives the route (MCP, CLI or batchmode). Don't compile or enter Play Mode unless the to-do needs it.
- Note blockers from the map: uncommitted changes, an editor lockfile, a missing PROJECT.md, stale graphify output, conflicting docs.

## 4. Report and ask
Write five lines at most: the project, its state, what changed since last time, and blockers. Then:
- **To-dos found:** list them numbered (in-progress stories first, then the active milestone, then handoff next steps, then TODO.md) with their sources. Ask the user which one to do, as a multiple-choice question when your client has one, else a numbered list in your reply, and end the turn.
- **None found:** say so and ask what to do. Offer concrete starts: grilling (to pin down the goal), game-designer (no design yet), gdd-to-backlog (a design exists but no backlog), project-memory (no PROJECT.md).
- **Unclear goal or docs that contradict each other:** offer grilling before any work.

Don't start a to-do until the user picks one. Then load its owner skill (BACKLOG `Owner skill:`) or route with unity-router.

## Leaving the project
Before ending a session that changed things, update the handoff doc in the format of `references/handoff-template.md` (or the project's own format). Keep it short: state, next steps as `- [ ]` items, decisions, gotchas. The next onboarding then costs one script call.
