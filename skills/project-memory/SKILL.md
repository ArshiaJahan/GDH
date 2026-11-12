---
name: project-memory
description: Maintains PROJECT.md at a Unity 6 (6000.3) project root - ADR-lite decisions, conventions, folder layout, build/test commands, gotchas, current-milestone pointer - plus a generated facts block (Unity version, render pipeline, packages, asmdefs, build scenes) with a drift check. Use when PROJECT.md is missing or stale (first session in a project, handoff), after a decision, package, folder or milestone change, or when asked to record or check conventions.
---

# project-memory

Keep one short, true PROJECT.md that any agent can read first to work in the project without rediscovering it.

Pinned: Unity 6000.3 LTS (ProjectVersion.txt), URP 17.3 2D Renderer, MCP for Unity 10.3. Script: `scripts/project_snapshot.py` (Python 3.9+ stdlib, read-only on Unity files; works with the editor open or closed).
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. mcp__UnityMCP__manage_packages). For tool parameters see unity-mcp-orchestrator.

## When to use
- First task in a project: read PROJECT.md; if it is missing, create it.
- After any of: an architecture decision, a package added/removed/upgraded, a folder or asmdef added/moved, a build/test command changed, a new gotcha found, a milestone completed or started.
- Before handing off to another agent or ending a session.

Not for: the backlog itself (gdd-to-backlog owns BACKLOG.md), design content (GDD), changelogs for players (build-ship), or tool parameters (unity-mcp-orchestrator).

## Inputs
- Unity project root (the folder with `ProjectSettings/ProjectVersion.txt`).
- `BACKLOG.md` (from gdd-to-backlog) for the milestone pointer, if it exists.
- The decision, change or gotcha to record.

## File layout of PROJECT.md
Template: `references/PROJECT.template.md`. Sections in order:
1. `## Current milestone` - `Current milestone: M<n> <title> (BACKLOG.md#m<n>)`, next story, blockers, last verification result.
2. `## Build and test` - exact commands for MCP (editor open) and batchmode (editor closed): compile, EditMode, PlayMode, milestone test filter, player build, memory and backlog checks.
3. `## Conventions` - root namespace, asmdef names, code style, data asset naming, scene flow, input, test naming/categories, log tags, commit format.
4. `## Folder layout` - annotations only; the raw tree lives in the snapshot.
5. `## Architecture decisions` - ADR-lite entries, newest last.
6. `## Known gotchas` - one line each: symptom -> cause -> fix.
7. `## Snapshot` - generated block between `<!-- project-snapshot:begin ... -->` and `<!-- project-snapshot:end -->`: Unity version, product, input handling, render pipeline asset per quality level, renderer data (2D or Universal), packages (manifest -> lock), asmdefs with kind, scenes in build, Assets tree depth 2 (generated folders like Screenshots, _Recovery, TextMesh Pro, Samples hidden).

## Procedure
1. Find the project root. Run `python3 <skill-dir>/scripts/project_snapshot.py --project <root> --check`.
   - `not found`: create it with `--init` (copies the template and fills the snapshot), then fill Conventions, Build and test, and Folder layout from what you see in the project (asmdef names, namespaces in existing scripts, scenes, `Tools/` scripts). Mark unknowns `<TBD>`; do not guess.
   - `RESULT: DRIFT n`: read each `DRIFT` line, update the prose sections it affects (for example a new package may need an ADR or a gotcha), then run `--update`.
   - `RESULT: OK`: continue.
2. Read PROJECT.md fully before the task. Follow its Conventions over any skill default.
3. When you make a decision, add an ADR entry at the end of `## Architecture decisions`:
   ```
   ### ADR-00N <decision title> (YYYY-MM-DD, accepted)
   - Context: <forces, constraints, options considered in one line>
   - Decision: <what we do>
   - Consequences: <what gets easier/harder, follow-up work>
   ```
   Record a decision when it is hard to reverse or another agent would otherwise choose differently: render pipeline, input approach, save format, scene loading, data model (ScriptableObjects), procgen algorithm, package adoption or removal, folder/asmdef structure, build targets, VCS setup. To change a decision, add a new ADR and mark the old one `superseded by ADR-00M`. Never delete ADRs.
4. When packages change (`manage_packages add_package/remove_package`, or manifest edits): let Unity resolve, run `--update`, and add an ADR if the package is a new dependency. Keep only the decision in prose; versions live in the snapshot.
5. When folders or asmdefs change: run `--update`; update `## Folder layout` annotations and `## Conventions` if the rule changed.
6. When a gotcha costs more than one retry: add one line to `## Known gotchas` (symptom -> cause -> fix). Remove gotchas that no longer apply.
7. When a milestone completes or starts: update `## Current milestone` (pointer, next story, last verification result with counts and date). The pointer must match a `## M<n>` heading in BACKLOG.md.
8. Update `Last updated:` with date and author. Run `--check` again (see Verify).

## Rules
- Under ~200 hand-written lines (the generated block is not counted; it grows with packages and asmdefs). If it grows, shorten ADR context, move long rationale to `docs/adr/ADR-00N.md` and link it, delete obsolete gotchas. The check warns above `--max-lines` (default 200).
- Never store secrets: no passwords, tokens, API keys, private keys, signing identities, license serials. Write where they live ("Keychain item `notary-profile`", "env var `ASC_KEY_ID`"). The check fails on secret-like lines.
- Never hand-edit the snapshot block. Change the project, then `--update`.
- Facts over intentions: record what the project does now. Plans belong in BACKLOG.md.
- Version numbers appear only in the snapshot or in ADRs. The check warns when prose elsewhere mentions a package or Unity version that differs from the project.
- One fact, one place: do not copy the backlog, the GDD or tool docs into PROJECT.md; link them.
- ⚠ version-sensitive: Unity 6 stores the URP asset per quality level (`QualitySettings`), and GraphicsSettings may show `none`; the snapshot lists both. Build Profiles (Unity 6) can override the scene list; if the project uses them, note the active profile under Build and test. The snapshot reads only `EditorBuildSettings`.
- The snapshot reads `Packages/packages-lock.json`. After a manifest edit, Unity must resolve before the lock is current (the check warns when manifest and lock disagree).

## Failure handling
- `RESULT: FAIL not a Unity project`: wrong `--project`; point it at the folder that has `ProjectSettings/`.
- `--update` says no markers: paste the default output of the script under `## Snapshot` once, then use `--update`.
- `FAIL possible secret`: remove the value from PROJECT.md now. If the file is committed, tell the user that the secret is in git history and must be rotated. Do not rewrite history yourself.
- Drift you cannot explain (for example a package you did not add): do not "fix" it by `--update` silently. Report it to the user, then update.

## Verify
1. Run `python3 <skill-dir>/scripts/project_snapshot.py --project <root> --check`.
   Pass: exit code 0, last line `RESULT: OK`, and no `DRIFT` or `FAIL` lines. Each remaining `WARN` line is either fixed or explained in your report (for example "BACKLOG.md not written yet").
2. The same output has no `WARN ... hand-written lines` line (prose stays within ~200 lines).
3. If BACKLOG.md exists: `grep -n "^## M<n>" <root>/BACKLOG.md` for the milestone in the pointer. Pass: one match.
