---
name: unity-practices
description: Unity 6 best practices by topic - C# coding and review, readable code, enemy systems (waves, health, spawners), object pooling, textures, performance, tunable parameters (magic numbers to ScriptableObjects), debug scenes and cheats for recurring bugs. Use when writing or reviewing Unity gameplay code or fixing a repeated issue.
index-hint: "Unity best practices: C# review, readable code, enemies (waves, health, spawners), object pooling, textures, performance, magic numbers to ScriptableObjects, debug scenes for recurring bugs."
requires: unity-project
argument-hint: "[topic] [task]"
---

# unity-practices

Load only what the task needs. `<skill>` = this skill's folder. Unity 6 (6000.x), C#, no third-party packages.

## 1. Pick topics (read at most 2 references)
| Task mentions | Read |
|---|---|
| structure, components, events, async, null checks, lifecycle | `references/coding.md` |
| enemies, AI, spawners, waves, health/damage, state machine | `references/enemies.md` |
| bullets, VFX, spawn/despawn often, GC spikes from Instantiate | `references/pooling.md` |
| textures, sprites, import settings, atlases, memory | `references/textures.md` |
| fps, stutter, GC, draw calls, profiling | `references/performance.md` |
| naming, review, refactor, comments, "make it readable" | `references/readable-code.md` |
| tuning, balance knobs, designers, config, magic numbers | `references/tuning.md` |
| debug scene, cheats, overlay, gizmos, "keeps happening" | `references/debug-tools.md` |

If the project already uses `Harness.Arch` / `Harness.Perf` (architecture-patterns, perf-pass skills), extend those instead of adding parallel systems.

## 2. Repeated work: run, don't regenerate
- Known issue first: `python3 <skill>/scripts/issue_cache.py find "<error text or symptom>" --project <root>`. A hit gives the fix that worked last time; apply it. After a new fix: `issue_cache.py add "<symptom>" --fix "<what fixed it>" --files <paths> --project <root>`.
- Code review / lint: `python3 <skill>/scripts/cs_lint.py <root>/Assets [--only RULE,...]` (one line per finding, `RESULT:` last line). Fix findings, rerun until `RESULT: OK`.
- Textures: `python3 <skill>/scripts/texture_audit.py <root>/Assets --profile mobile|desktop|pixel`.
- New code from templates: `python3 <skill>/scripts/scaffold.py list`, then `scaffold.py <kit> --out <root>/Assets/<Folder> --namespace <Ns>`. Kits: `pooling`, `enemies`, `tuning`, `debug-kit`. Read a template only if you must change it.
- Checklists are in each reference; tick them instead of re-deriving rules.

## 3. Verify
Console has 0 errors after recompiling (compile-fix-loop skill), `cs_lint.py` prints `RESULT: OK` for the touched files, and the change is checked in Play Mode or tests (play-verify / headless-ops). In GameDevWorkstation, call `unload_skill("unity-practices")` when the session moves on to other work.
