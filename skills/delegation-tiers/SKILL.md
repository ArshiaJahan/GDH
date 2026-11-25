---
name: delegation-tiers
description: Which subagent tier and effort to pick for each kind of unit (codex.fast first for routine work, codex.standard only for coding, Sonnet at medium for complex work, Opus only for big tasks and only after the user approves). Load it whenever you spawn a subagent. Where it differs from the delegation skill's routing table, this skill wins.
index-hint: "Which subagent tier and effort to use per unit; load it whenever you spawn a subagent."
---

# Delegation tiers

The delegation skill decides **whether** and **how** to split a job. This skill decides **who** does each unit.
Where the two disagree on a tier or effort, follow this one.

Pick the first row that fits the unit, use the effort shown, and escalate only along the row's escalation path
after a real failure (a failed check, an empty or wrong result), never "just in case".

## The tiers

| Tier | Model | Use it for |
|---|---|---|
| `codex.fast` | GPT-6.1 Sol, low effort | **The default workhorse.** Routine, well-defined units with a clear output. Most units should land here. |
| `codex.standard` | GPT-6.1 Sol, medium effort | **Coding only**: writing or changing code that has to compile and pass tests. Nothing else. |
| `codex.computer` | GPT-6.1 Terra | Computer use and visual work: reading screenshots, checking a UI or a render against a description, driving a browser. |
| `codex.deep` | GPT-6.2 Sol | Complex coding after a plan exists: multi-file features, non-obvious bugs, refactors that touch interfaces. |
| `codex.cli` | GPT-6.1 Sol in the Codex CLI | Coding that needs a real shell and repo: multi-step changes with test runs, in its own worktree. |
| `claude.standard` | Sonnet 5.5, **medium** effort | **Start here for complex work**: planning, design, judgment calls, reviews, anything ambiguous. |
| `claude.deep` | Opus 5.5 | **Only for a big task** Sonnet has failed at or clearly can't hold, and **only after the user approves** (see below). |
| `claude.fast` | Haiku 5.5 | Fallback for routine units when no OpenAI key is set up. |

Generating images, textures, sprites, 3D models or sound is **not** a subagent's job: use the local models through
the `comfyplug` tool (ComfyUI on the user's own GPU, free). Speech, voices and music use the ElevenLabs tools.

## What codex.fast excels at (effort `low`; `medium` only when a first attempt shows the unit is harder)

- **Extracting and reshaping data**: pull fields from logs, docs, HTML or JSON into a schema; convert between CSV, JSON,
  YAML and TOML; normalize names, dates and units; classify or tag items in batches of 20–50.
- **Reading and summarizing**: summarize files, docs, pages, transcripts or long tool output into short bullets with
  locations; compare two documents and list the differences; pull the decisions and open questions out of notes.
- **Mapping a codebase (read-only)**: "where is X defined / used", list the files a change will touch, outline a
  module's public API, find dead code or TODOs, trace a call path with file:line references.
- **Logs and failures**: triage a CI or build log into its first real error, the failing test, file and line; group
  repeated warnings; spot the line where behaviour changed between two logs.
- **Small, mechanical edits with an exact spec**: renames, import fixes, formatting and lint fixes, adding type hints,
  updating config values, version strings or copyright lines, boilerplate from a given pattern. (Anything that needs
  design or new logic is codex.standard.)
- **Writing to a template**: commit messages, changelog and release-note drafts from a diff, docstrings for given
  functions, README sections from a given outline, issue or PR descriptions.
- **Test scaffolding and data**: fixtures, sample inputs, table-driven test cases from a spec, mock JSON responses.
- **Checking against a list**: does this output, file or diff meet each item of this checklist? Return pass/fail per
  item with the evidence.
- **Quick lookups with web tools**: one specific fact from docs (an API signature, a flag, a version), with the source.
- **Game-dev chores**: fill ScriptableObject or table rows from a design doc, rename or reorganize asset paths from a
  mapping, extract tuning numbers from assets into a table, write localization string files from a source list.

Brief it tightly: the exact input (paths or IDs), the exact output shape, one example if the format matters, and the
check that proves it worked. Escalation: codex.fast `medium` → codex.standard (code) or claude.standard `low` (text).

## codex.standard: coding only (effort `medium`)

Implement a well-specified feature or fix with its tests; write new tests for existing behaviour; fix a reproducible
bug with a clear error; port or refactor one module with a defined interface. Always give it the spec, the files,
the acceptance tests and the test command, and its own worktree when units run in parallel.
Escalation: codex.standard `high` → codex.deep `high` → claude.standard `medium` for diagnosis.

Do **not** use codex.standard for summaries, research, reviews, planning or data work: those are codex.fast (routine)
or claude.standard (judgment).

## Complex work: start with Sonnet at medium

For planning a feature, designing a system or UI, choosing between approaches, reviewing a diff for correctness or
security, debugging something with no clear repro, or any unit whose brief you can't make exact: spawn
`claude.standard` with effort `medium`. Raise to `high` only after a medium attempt falls short. When a Sonnet plan
exists, hand the coding slices to codex.standard / codex.deep / codex.cli.

## Opus (claude.deep): only for a big task, and only with the user's OK

Use Opus only when the task is genuinely big (a large refactor or migration plan, a cross-cutting architecture
decision, a long multi-step investigation) **and** Sonnet at medium or high has already failed or clearly can't hold
it. Before spawning a `claude.deep` subagent, tell the user in one or two sentences why Sonnet isn't enough and what
the Opus unit will do; the app also shows an approval card for every Opus subagent, and you proceed only if the
user approves. If they decline, continue with Sonnet (smaller slices, more context in the brief).

## Quick routing table

| Unit | Tier | Effort | Escalate to |
|---|---|---|---|
| Extract / reformat / classify / tag | codex.fast | low | codex.fast medium → claude.standard low |
| Summarize docs, pages, logs | codex.fast | low | claude.standard low |
| Map or search a codebase (read-only) | codex.fast | low | claude.standard low |
| Triage a CI or build log | codex.fast | low | codex.cli medium (to fix it) |
| Mechanical edit with an exact spec | codex.fast | low | codex.standard medium |
| Commit message, changelog, docstrings, README section | codex.fast | low | claude.standard low |
| Test fixtures and data | codex.fast | low | codex.standard medium |
| Check output against a checklist | codex.fast | low | claude.standard medium |
| One-fact web lookup | codex.fast | low | claude.standard low |
| Screenshot / UI / render check, browser driving | codex.computer | low | codex.computer medium |
| Implement a specified feature or fix with tests | codex.standard | medium | codex.deep high → claude.standard medium |
| Multi-step change needing a real shell and test runs | codex.cli | medium | codex.cli high → codex.deep high |
| Complex multi-file coding after a plan exists | codex.deep | high | claude.standard medium (diagnose), then Opus with approval |
| Research with judgment, conflicting sources | claude.standard | medium | claude.standard high |
| Plan or design (feature, system, UI) | claude.standard | medium | claude.standard high → Opus with approval |
| Code or security review of a diff | claude.standard | medium | claude.standard high |
| Big refactor / migration plan, architecture decision | claude.standard | high | Opus with approval |
| Images, textures, sprites, 3D, sound effects | `comfyplug` tool (local models) | — | — |
| Speech, voices, music | ElevenLabs tools | — | — |
