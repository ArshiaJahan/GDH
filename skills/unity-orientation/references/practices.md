# Why the orientation works this way

Sources, checked 2026-11-25:
- Claude Code memory docs (code.claude.com/docs/en/memory)
- AGENTS.md spec (agents.md)
- Anthropic: effective harnesses for long-running agents (2025-11-26)
- Anthropic: effective context engineering for AI agents
- Aider repo map docs (aider.chat/docs/repomap.html)
- Nygard ADRs, via Martin Fowler's bliki
- Futurice project-handover checklist
- Unity manual: default project directories

## Order and why
1. **Cache check first.** Most sessions open an unchanged project. A fingerprint (git HEAD, working-tree changes, doc hashes, manifest, build settings) keeps the scan, and the reading, from being redone.
2. **Rules files.** CLAUDE.md and AGENTS.md are the project's instructions to agents and override other docs. Claude Code loads CLAUDE.md on its own, so don't read it twice. Keep these files short: the docs say long files reduce adherence.
3. **Handoff or progress doc, plus git log.** Anthropic's long-running harness starts every session this way: read the progress file and recent commits, pick the highest-priority unfinished item, and check that the project still works before changing it.
4. **Unity facts from a few small files.**
   - `ProjectSettings/ProjectVersion.txt`: editor version.
   - `Packages/manifest.json`: render pipeline, Input System, test framework, Addressables, MCP for Unity.
   - `EditorBuildSettings.asset`: the scenes in the build.
   - `*.asmdef` names: code layout and test assemblies.
   - Skip `Library/`, `Temp/`, `Logs/` and `UserSettings/`: they are generated and local.
5. **To-dos from structured sources.**
   - BACKLOG statuses (doing before todo, active milestone first).
   - Handoff "Next steps" bullets.
   - Unchecked `- [ ]` items.
   - TODO/FIXME counts in code are context only: they are not offered as tasks.
6. **Lazy-load everything else.** Load just in time with targeted lookups, the way Aider's repo map keeps a ranked symbol map under a token budget instead of whole files. When graphify has a graph, its query, path and explain answer structure questions for far fewer tokens than reading files.
7. **Ask, don't assume.** The user picks the to-do. Agents that start on the wrong item waste more than the question costs.

## Handoff contents (what the next session needs)
- **Current state:** what works, what's half done, what's broken.
- **Next steps:** checkboxes in priority order.
- **Decisions and why:** ADR-lite: context, decision, consequences.
- **Gotchas:** things that cost time.
- **How to run and test:** exact commands for editor open and editor closed.
- **Open questions** for the user.

A Unity handover is real only when the project opens and builds on another machine: required packages, LFS assets, no `Library/` dependence.

## What the cache holds (`<project>/.gdw/orientation.json`, git-ignored)
- The fingerprint, Unity facts, folder counts, doc paths, headings and hashes.
- The parsed to-dos with their sources, and the newest session-log entry.
- Never scene or prefab contents, and nothing from `Library/`.
