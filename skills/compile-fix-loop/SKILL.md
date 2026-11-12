---
name: compile-fix-loop
description: Recompiles a Unity 6 (6000.3) project, reads C# compiler errors from the editor console via MCP for Unity (or from a batchmode log when no editor is open), fixes root causes one at a time and repeats until the console is clean, stopping after N failed attempts (default 5) with a report. Use when scripts do not compile, the console is red, "error CS…", "fix compile errors", after code/asmdef/package changes, or before Play Mode, tests and builds.
---

# compile-fix-loop

Get a Unity project from "red console" to "0 compile errors" with small, root-cause-first fixes, and stop honestly when it does not converge.

Pinned: Unity 6000.3.21f1 (Roslyn, C# 9), MCP for Unity 10.3.0, Input System 1.20.x, Cinemachine 3.1.x, URP 17.3.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. `mcp__UnityMCP__read_console`). For tool parameters see unity-mcp-orchestrator; this skill gives only the call sequence.

## When to use / not to use
- Use after any edit to `.cs`, `.asmdef`/`.asmref`, `Packages/manifest.json`, scripting defines; when `read_console` shows errors; as the gate before play-verify, `run_tests` or builds.
- Not for runtime exceptions in Play Mode (use play-verify), failing tests (fix the code under test), or shader/import errors (asset-pipeline). Batchmode mechanics (wrappers, timeouts, exit codes) belong to headless-ops.

## Inputs
- Project root (folder with `ProjectSettings/ProjectVersion.txt`).
- `max_attempts` (default 5; the user may say "attempts=8"). An attempt = one fix + one recompile.
- Optional scope (assembly or folder the task owns) and the task that caused the errors.

## Procedure
1. **Choose the path.** Read `mcpforunity://instances`. If an editor has this project open, `set_active_instance(<Name@hash>)` and use the MCP path. If none has it open, use the headless path (step 9). Never run batchmode on a project an editor has open.
2. **Precheck (MCP).** Read `mcpforunity://editor/state`. If `editor.play_mode.is_playing` is true, `manage_editor(action="stop")`. If tools are hidden, `manage_tools(action="activate", group="scripting_ext")` (only needed for `execute_code`).
3. **Start a log.** Create `Logs/harness/compile-fix/attempts.md` (Logs/ is git-ignored) with the start time and `max_attempts`.
4. **Recompile.** `read_console(action="clear")` (compile errors are re-added by Unity; this only drops stale runtime noise), then `refresh_unity(mode="force", scope="all", compile="request", wait_for_ready=true)`. Edits made with `create_script`/`script_apply_edits` already trigger compilation: skip refresh and go to step 5. Files edited on disk (shell, file tools, git) always need the refresh.
5. **Wait for ready.** Poll `mcpforunity://editor/state` every 1–2 s (cap 180 s) until `compilation.is_compiling == false`, `compilation.is_domain_reload_pending == false` and `advice.ready_for_tools == true`. A lost connection during this wait is the domain reload: wait 5 s and poll again. If the only blocking reason is `stale_status`, the editor is unfocused and throttled; keep polling (do not treat it as compiling).
6. **Read errors.** `read_console(action="get", types=["error","warning"], format="json", include_stacktrace=true, page_size="200", cursor="0")`; follow `nextCursor` until null. ⚠ version-sensitive: in 10.3 entries come oldest-first and `count` keeps the *oldest* N, so page instead of using `count`. Save the raw JSON to `Logs/harness/compile-fix/console-<n>.json` and run:
   `python3 <skills>/compile-fix-loop/scripts/parse_unity_log.py Logs/harness/compile-fix/console-<n>.json`
   It prints deduplicated errors, root causes in fix order and `RESULT: OK|FAIL`; exit 0 clean, 1 compile errors, 3 only runtime errors (not this skill's job: report them, do not loop on them).
7. **Fix one root cause.** Take root cause #1. Open the file at the reported line, read enough context, and look the code up in references/common-errors.md if it is unfamiliar. Make one logical change (it may touch several files only when it is one rename/one missing reference). Before recompiling, optionally run `validate_script(uri="Assets/...cs", level="standard")` on edited files as a cheap syntax check; it is not a Unity compile.
8. **Record and repeat.** Append to attempts.md: `#n | root cause | change (file:line) | errors before → after`. Go to step 4. Apply the stop conditions below after every recompile.
9. **Headless path (no editor open).** Compile with headless-ops: `<skills>/headless-ops/scripts/unity.sh compile --project <root> --log Logs/harness/compile-fix/compile-<n>.log` (last line `RESULT: OK|FAIL`), then `python3 <skills>/compile-fix-loop/scripts/parse_unity_log.py Logs/harness/compile-fix/compile-<n>.log`. Then steps 7–8, recompiling with the same command. Each run imports changed assets first, so a cold project can take minutes; keep headless-ops' timeout.
10. **Finish.** On success write the final summary line to attempts.md and report (format below). If the task continues (play-verify, tests, build), hand over only after the Verify section passes.

## Fix order and rules
- Fix in the order the parser prints: project/asmdef/package problems → syntax errors (first per file) → missing types/namespaces (one symbol fixes many lines) → duplicate definitions → obsolete-as-error APIs → remaining first-error-per-file. Recompile after each; cascades usually disappear.
- One logical change per iteration. Never batch unrelated guesses.
- Never suppress: no `#pragma warning disable` for errors, no `-ignorecompilererrors`, no `[Obsolete]` games, no `#if false`, no deleting/commenting out code, tests or asmdefs to make errors vanish, no `-nowarn` or `csc.rsp` edits to hide diagnostics.
- Never edit generated or cached files: `Library/` (incl. `Library/PackageCache`), `Temp/`, `obj/`, `*.csproj`, `*.sln`, `Packages/packages-lock.json`. A bug inside a package means: pin another version or report.
- Stay in scope: if errors are in files the task did not touch and existed before, report them instead of rewriting other systems.
- Prefer the 6000.3 API the error points to (e.g. `FindFirstObjectByType`, `linearVelocity`, `Unity.Cinemachine`) over reflection hacks or `dynamic`.
- Missing type in an asmdef project: add the assembly reference to the right `.asmdef` (by name, e.g. `"Unity.InputSystem"`), not a `using` alone; never create reference cycles.
- `-accept-apiupdate` (headless) or the editor's API Updater rewrites scripts in place: only with the user's consent and a clean git tree, then review the diff. ⚠ version-sensitive: the updater does not run in batchmode without `-accept-apiupdate`.
- Warnings never block the loop; list new CS0618 (obsolete) warnings in the report as follow-ups.

## Stop conditions
Stop and report (do not keep trying) when any is true:
- Clean: Verify passes → success.
- `max_attempts` recompiles done and errors remain.
- No progress twice in a row: the same root-cause signature (`code + file + symbol`) survives two different fixes, or new root causes appear in files you edited after two consecutive fixes (revert the last change first). A higher raw count right after fixing a syntax or missing-type error is normal: those errors hide method-body errors and dependent assemblies (e.g. `Assembly-CSharp-Editor`) until they are fixed.
- The fix needs something outside code: a package install/upgrade, an editor/module install, licence, a missing asset, a decision about game design or API choice.
- The only remaining errors are runtime (parser exit 3) or are in files outside your scope that pre-date the task.

## Report format
```
compile-fix-loop: SUCCESS|STOPPED after <n>/<max> attempts (<MCP|headless>)
Remaining errors: <count> (<count> root causes)
  1. Assets/X.cs(12,5) CS0246 'CinemachineVirtualCamera' (+7 related)  suspected: Cinemachine 3 rename
Tried:
  #1 added "Unity.InputSystem" to Game.asmdef → 14 → 3 errors
  #2 renamed rb.velocity → rb.linearVelocity in PlayerMotor.cs:41 → 3 → 3 (no progress)
Suspected cause: <one or two sentences>
Next step for a human: <exact action, e.g. "install com.unity.cinemachine 3.1.7" or "choose API">
Evidence: Logs/harness/compile-fix/console-<n>.json, attempts.md
```

## References
- references/common-errors.md: read when an error code or message is unfamiliar, an API looks "missing" in 6000.3, or a package/asmdef is involved.

## Verify
Pass only when all of these are observed in the final iteration:
- MCP path: `mcpforunity://editor/state` shows `compilation.is_compiling == false`, `compilation.is_domain_reload_pending == false`, `advice.ready_for_tools == true`; then `read_console(action="get", types=["error"], format="json", page_size="200")` returns 0 entries whose message matches `error CS\d+` (and 0 asmdef/package errors), and `parse_unity_log.py` on that dump exits 0 or 3 and prints `compile errors: 0`.
- Headless path: `unity.sh compile` exits 0 with `RESULT: OK`, and `parse_unity_log.py <log>` exits 0 with `RESULT: OK` (no `error CS` line in the log).
- attempts.md lists every attempt, and the report above was given.
