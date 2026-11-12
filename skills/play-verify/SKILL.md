---
name: play-verify
description: Verifies a Unity 6 (6000.3) game in Play Mode against acceptance criteria from BACKLOG.md (gdd-to-backlog). Enters Play Mode through MCP for Unity, drives input with a scripted autoplay, captures Game-view screenshots and [VERIFY] log lines, marks every criterion PASS/FAIL with evidence and writes a VERIFY report; has a headless PlayMode-test path. Use when asked to "play test it", "verify the feature works", check acceptance criteria, take Play Mode screenshots, or before marking a story done.
---

# play-verify

Prove a feature works by running it: every acceptance criterion gets PASS or FAIL with evidence (log line, screenshot path, test name), and the run must log 0 errors/exceptions.

Pinned: Unity 6000.3.21f1, MCP for Unity 10.3.0, Input System 1.20.x, Test Framework 1.6.0, URP 17.3 (2D).
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. `mcp__UnityMCP__manage_editor`). For tool parameters see unity-mcp-orchestrator; this skill gives only the call sequence. `<skills>` = the folder holding these skills.

## When to use / not to use
- Use for criteria whose Test column is `play-verify` or `PlayMode`, for smoke runs after a feature lands, and for screenshots a human or the next agent must see.
- Not for compile errors (compile-fix-loop first), pure logic (EditMode tests), performance budgets (perf-pass owns profiling; check_criteria.py still evaluates `metric:` rows against its `[PERF] kind=summary` keys, e.g. `frame_ms_p95`, `gc_alloc_avg`), or builds (build-ship).

## Inputs
- `BACKLOG.md` and the IDs in scope (`M1-S02`, `M1-S02-AC2`). Rows look like `| M1-S02-AC2 | Given/When/Then | play-verify | log:"[Combat] hit target=Enemy"; screenshot:M1-S02-hit shows the white hit flash |`.
- Scene path, how to reach the state (input script or debug method), run length. Ask if a criterion is not observable.

## One-time setup in the game project
1. Copy `<skills>/play-verify/templates/Harness.Verify/` to `Assets/Harness/Verify/` (Runtime, InputSystem, Tests/PlayMode, each with an asmdef). Delete `InputSystem/` if the project has no Input System package. Run compile-fix-loop.
2. Make every criterion observable. `log:"text"` → the game must `Debug.Log` that text. `metric:key op value` → emit `[VERIFY] key=value` via `VerifyProbe.Set/Log/Register`, or with no code change via a watch `key=GameObjectPath:Component.member`. Game asmdefs that call VerifyProbe add a reference to `Harness.Verify`.
3. Built-in probe keys: `t frame scene fps fps.min log.errors log.exceptions log.warnings`, and from ScriptedInput `script.steps script.step script.done script.failed shot`.

## Procedure (MCP path, editor open)
1. **Precheck.** `set_active_instance` for this project. Read `mcpforunity://editor/state`; require `advice.ready_for_tools` and not playing. Run compile-fix-loop's Verify (0 compile errors): Unity refuses Play Mode with compile errors. `execute_code` is in the `scripting_ext` group and `run_tests` in `testing`: if hidden, `manage_tools(action="activate", group=...)`.
2. **Plan.** For each criterion in scope write one line in the run plan: signal → how it will be produced (log text, probe key, screenshot checkpoint, test name). Run id: `<YYYYMMDD-HHMM>-<scope>`; run folder `Logs/harness/verify/<run-id>/` (Logs/ is git-ignored).
3. **Scene.** `manage_scene(action="get_active")`; if it is not the target, `manage_scene(action="load", path="Assets/Scenes/X.unity")`. Do not save scenes you did not change (scene-prefab-safety).
4. **Clear and play.** `read_console(action="clear")`, then `manage_editor(action="play")`. Poll `mcpforunity://editor/state` until `editor.play_mode.is_playing == true` and `advice.ready_for_tools == true` (cap 60 s; a dropped connection is the domain reload: wait 5 s, poll again). Still not playing → read errors and go back to compile-fix-loop.
5. **Arm the probe.** `execute_code` (body, C# 6 safe: no `$""`, no `out var`; write `UnityEngine.Object` in full):
   `Harness.Verify.VerifyProbe.Watch("player.hp=Player:Health.current"); Harness.Verify.VerifyProbe.Instance.interval = 1f; Harness.Verify.VerifyProbe.Mark("run-<run-id>"); return "armed";`
6. **Warm up.** Wait for a state, not a clock: `ScriptedInput` `until KEY OP VALUE TIMEOUT`, or poll `execute_code("return Harness.Verify.VerifyProbe.DumpAll();")` until the needed keys exist. A bare `sleep 2` in the shell is the fallback.
7. **Drive input** (pick one; details in references/driving-input.md):
   - Call game code: `execute_code` → `GameObject.Find("Player").SendMessage("DebugAttack"); return 1;` or a static debug method.
   - Scripted input: `execute_code` → `Harness.Verify.ScriptedInput.Run("hold right 1; tap Space; wait 0.5; until enemy.count == 0 10; shot Logs/harness/verify/<run-id>/shots/after.png; probe"); return 1;`. Key commands need the Input System add-on (virtual keyboard).
   Poll `execute_code("return Harness.Verify.ScriptedInput.Done + \" \" + Harness.Verify.ScriptedInput.Failed;")` every 1–2 s until `True False`. `True True` = the script failed: the `[VERIFY] script.failed=1 reason=...` line says why.
8. **Screenshots at checkpoints.** For each `screenshot:` signal: `manage_camera(action="screenshot", capture_source="game_view", include_image=true, max_resolution=512, screenshot_file_name="<AC-id>-<name>", output_folder="Logs/harness/verify/<run-id>/shots")`. Omit `camera` so Screen Space-Overlay UI is included. Look at the returned image and write one sentence: what is visible vs what the criterion says. See references/report-template.md for the inspection checklist.
9. **Collect logs (still playing).** `execute_code("return Harness.Verify.VerifyProbe.DumpAll();")`. Then `read_console(action="get", types=["error","warning","log"], format="json", include_stacktrace=true, page_size="200", cursor="0")`, following `nextCursor` until null; save all pages merged into one JSON list at `Logs/harness/verify/<run-id>/console.json`. ⚠ version-sensitive: 10.3 returns oldest-first and `count` keeps the oldest N; always page.
10. **Stop.** `manage_editor(action="stop")`; poll until `is_playing == false`. Time scale, capture framerate and virtual devices reset when Play Mode ends.
11. **Evaluate.** `python3 <skills>/play-verify/scripts/check_criteria.py BACKLOG.md Logs/harness/verify/<run-id>/console.json --only <IDs> --type play-verify,PlayMode [--results <xml>] [--evidence <ID>=PASS:<shot path — observation>]...`. Exit 0 = all PASS; 1 = FAIL; 4 = screenshot/observe rows still need your `--evidence` verdict. Give `--evidence ...=FAIL:...` when the image does not match; never PASS an image you did not look at.
12. **Report.** Write `Logs/harness/verify/<run-id>/VERIFY.md` from references/report-template.md: the script's table, screenshot paths, console summary, input script used, and next actions for each FAIL. Return the table and the report path.

## Unity CLI live path (GameDevWorkstation, route `cli_live`)
With the official Unity CLI and com.unity.pipeline instead of MCP for Unity: `unity` tool `op=play action=start` (sends
`set_autotick` first so an unfocused Editor keeps ticking, then `editor_play`), confirm frames advance with
`op=command name=editor_status`, `op=screenshot`, read values with `op=eval` (shown to the user first), then
`op=play action=stop`. Evaluate and report as in steps 11-12.

## Headless path (no editor, CI, or long deterministic runs)
- Copy `PlayVerifyTests.GameScene_MeetsAcceptanceCriteria` per scene/criterion set; set `ScenePath`, `WarmupSeconds`, `InputScript`, and turn criteria into `Assert`s on `VerifyProbe.GetFloat(...)`. Name tests after the AC (`M1_S02_AC2_HitLogged`) so `test:` signals match.
- Run with headless-ops: `<skills>/headless-ops/scripts/unity.sh test playmode --category PlayVerify --results Logs/harness/verify/<run-id>/playmode.xml` (PlayMode never gets `-nographics` there; never `-quit` with `-runTests`). With the editor open instead: `run_tests(mode="PlayMode", category_names=["PlayVerify"], init_timeout=120000)` then `get_test_job(job_id, wait_timeout=60, include_failed_tests=true)`.
- Evaluate with `check_criteria.py BACKLOG.md <unity log> --results <xml>`. gdd-to-backlog `headless` rows (CLI/build/player smoke): `--type headless --exit-code <rc> --root <project>` on the log of that run. The Test Framework fails a test on any unexpected `Debug.LogError`/exception, so a green test also proves the 0-errors gate for its run.
- Screenshots in batchmode: ScriptedInput `shot`/`render FILE [W H]` renders `Camera.main` to a PNG (no Screen Space-Overlay UI). This works in a PlayMode run without `-nographics`; under `-nographics` it logs `[VERIFY] shot.skipped=nographics` and `fps` is meaningless. UI screenshot criteria stay on the MCP path.
- Values persist between tests of one run: the template calls `VerifyProbe.ResetAll()` before loading the scene; keep that in every copy.

## Rules
- The harness reads the `--only` IDs from the `check_criteria.py` command and indexes screenshots from `output_folder`, so keep the documented names.
- Evidence or it did not happen: each PASS cites a log line, a `[VERIFY]` value, a screenshot path with an observation, or a passing test name. No PASS from reading code.
- 0 errors/exceptions during the run is a criterion of its own (the `CONSOLE` row). Warnings are listed, not failed.
- Never weaken a criterion to make it pass; if it is untestable, report it and propose a rewrite for gdd-to-backlog.
- Do not leave test objects or probe components saved in scenes; runtime-only arming (step 5) needs no scene change.
- Keep inline images at `max_resolution` 512 or less; save every screenshot to the run folder, not `Assets/` (avoids imports and .meta churn).
- ⚠ version-sensitive: Enter Play Mode Options (Project Settings > Editor) with domain reload disabled keep static fields, static events and singletons from the previous run. Reset statics in `[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]` (the templates do), and suspect stale statics when the second run behaves differently from the first.
- [UNVERIFIED] An unfocused editor may throttle Play Mode; if `frame` in `[VERIFY]` lines barely advances, ask the user to focus Unity or use the headless path with `Time.captureFramerate`.
- [UNVERIFIED] `manage_camera` `output_folder` outside `Assets/` (e.g. `Logs/...`) — the schema allows project-relative folders; if it is rejected, use `Assets/Screenshots/<run-id>` and move the files out afterwards.

## Failure handling
- Play Mode will not start: compile errors → compile-fix-loop; Play Mode Options or a script throwing in `Awake` → read_console errors, report.
- A criterion FAILS: record actual vs expected, stop play, report; fixing is a separate task (then re-run this skill fully).
- Script times out (`until` never met): capture a screenshot and `DumpAll()` before stopping; they are the evidence.
- MCP drops repeatedly: stop after 3 reconnect attempts and use the headless path.

## References
- references/driving-input.md: read when choosing how to drive the game (method calls, virtual keyboard, InputTestFixture, autoplay bots, determinism).
- references/report-template.md: read when writing VERIFY.md or judging screenshots.

## Verify
- `check_criteria.py ... --only <IDs>` exits 0 and prints `RESULT: OK`, with every in-scope criterion PASS and the `CONSOLE` row PASS (`0 errors`).
- Each PASS row's evidence names a log line, `[VERIFY]` value, screenshot path under `Logs/harness/verify/<run-id>/shots/` that exists on disk, or a test that is `Passed` in the results XML.
- `read_console(action="get", types=["error"], format="json", page_size="200")` taken before stopping returned 0 entries (headless: the PlayMode results XML has `failed="0"`).
- `Logs/harness/verify/<run-id>/VERIFY.md` exists and its table matches the script output.
