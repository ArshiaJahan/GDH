---
name: headless-ops
description: Runs a Unity 6 (6000.3) project with no editor open via batchmode - compile check, EditMode/PlayMode tests with NUnit summary, asset (re)import, player builds (Build Profile or target) and -executeMethod jobs - through one wrapper (unity.sh) with watchdog, project-open check and a RESULT line. Use when the editor is closed or in CI - "run tests from the command line", batchmode, headless, -executeMethod, reimport from the CLI, a raw CLI player build. Release flow (version, changelog, smoke test) is build-ship.
---

# headless-ops

Drive Unity 6000.3 in batchmode safely: one command per job, always a timeout, always a log, one machine-readable result line.

Pinned: Unity 6000.3.21f1 (macOS Apple Silicon), Test Framework 1.6.0, URP 17.3, MCP for Unity 10.3.0 (editor-open path).
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. `mcp__UnityMCP__run_tests`). For tool parameters see unity-mcp-orchestrator.

In GameDevWorkstation, prefer the `unity` tool (`op=compile|test|build|exec|import|menu|screenshot`): it picks the route from the user's Unity
backend (official Unity CLI `unity run/test/build`, or this skill's `unity.sh`), streams the job to the Terminal drawer,
asks for approval and records ladder evidence. `unity.sh` stays the path for CI, manual runs and HarnessCli entry points.
When an op needs HarnessCli and the project has none, the tool answers `needs_harness`: use `op=install_harness`
(the user approves; it installs step 2's files with fixed .meta GUIDs and keeps them out of git) instead of copying by hand.
With the Editor open and no live route, compile and tests can run on an APFS copy of the project (`[unity] clone_when_open`);
the result says "on a copy of the files on disk (unsaved Editor changes not included)".

## When to use / not to use
- Use when no editor has the project open: compile gate for compile-fix-loop, test runs for play-verify/gdd-to-backlog
  criteria, imports after files were added on disk, player builds for build-ship, any `-executeMethod` job.
- Not when an editor has the project open: batchmode cannot open it. Use MCP instead (`refresh_unity` + `read_console`,
  `run_tests` + `get_test_job`, `manage_build`), or ask the user to close the editor.
- Not for fixing compile errors (compile-fix-loop), judging gameplay (play-verify), release steps (build-ship).

## Inputs
- Project root (folder with `ProjectSettings/ProjectVersion.txt`). `<skills>` = the folder holding this skill.
- For `import`, `build`, `menu`, `screenshot`, `compile --force`: the HarnessCli templates installed in the project (step 2;
  `screenshot` needs `// harness-version: 3`).

## Procedure
1. **Pick the path.** Read `mcpforunity://instances`. If an instance shows this project, use MCP (table below) and stop here.
   Otherwise continue. `unity.sh` double-checks: it refuses (exit 4) when a Unity process has `-projectPath <root>` or holds
   `Temp/UnityLockfile`; a stale lockfile with no holder is fine.
2. **Install entry points once** (needed by `import`, `build`, `menu`, `screenshot`, `compile --force`):
   copy `<skills>/headless-ops/templates/Editor/` to `<root>/Assets/Harness/Headless/Editor/` (HarnessCli.cs, HarnessArgs.cs,
   Harness.Headless.Editor.asmdef: Editor-only, not auto-referenced, namespace `Harness.Headless`). Then run `compile`.
3. **Run the job** from the project root (or pass `--project <root>`):
   ```
   S=<skills>/headless-ops/scripts
   $S/unity.sh compile [--force]                         # open + compile; --force = clean recompile
   $S/unity.sh test editmode|playmode [--filter X] [--category Y] [--assembly Z] [--results F.xml] [--allow-empty]
   $S/unity.sh import [Assets/path ...] [--force]        # no paths = AssetDatabase.Refresh
   $S/unity.sh build <macos|windows|webgl|android|ios|linux|Assets/…/Profile.asset> [--out DIR] [--dev] [--clean] [--scenes "a;b"]
   $S/unity.sh menu "Tools/Rebuild Atlas"                # a menu item, then AssetDatabase.SaveAssets
   $S/unity.sh screenshot --out Logs/harness/screenshots/a.png [--scene Assets/S.unity] [--camera "Main Camera"] \
       [--cam-pos x,y,z] [--cam-rot x,y,z] [--fov 50] [--width 1920 --height 1080]   # one PNG, scene never saved
   $S/unity.sh exec <Ns.Class.Method> [-yourArg value ...] [--no-quit]
   ```
   Common flags (anywhere): `--project DIR`, `--timeout SEC` (defaults: compile/menu/screenshot 900, test/import/exec 1800, build 3600),
   `--log FILE` (default `<root>/Logs/harness/<cmd>-<ts>.log`, copied to `Logs/harness/last.log`), `--accept-apiupdate`,
   `--graphics` (drop `-nographics`; PlayMode tests and `screenshot` never get it), `UNITY_PATH=<binary>` to override the editor.
4. **Read the result.** The last line is `RESULT: OK <summary>` or `RESULT: FAIL <reason>`. Above it the script prints the
   deduplicated `file(line,col): error CS…` lines, `[HARNESS]` progress lines, abort reasons, and for tests the summary from
   `scripts/test_summary.py` (`tests: total= passed= failed= …` plus `FAILED <name> :: <message>` / `at <file:line>`).
5. **Act on the exit code** (table below). On compile errors hand the log to compile-fix-loop
   (`parse_unity_log.py <log>`); on test failures fix the code under test; on 4 switch to the MCP path.

### What each command runs
| Command | Unity arguments (always `-batchmode -projectPath <root> -logFile <log>`, `-nographics` unless noted) |
|---|---|
| compile | `-executeMethod Harness.Headless.HarnessCli.Compile [-forceRecompile]` when HarnessCli exists, else `-quit` |
| test | `-runTests -testPlatform EditMode\|PlayMode -testResults <xml> [-testFilter] [-testCategory] [-assemblyNames]`, **never `-quit`**; checks `com.unity.test-framework` in `Packages/manifest.json` first (else `-runTests` hangs) |
| import | `-executeMethod …HarnessCli.ImportAssets [-importPaths "a;b"] [-forceReimport]` (StartAssetEditing/StopAssetEditing, checks each path has a GUID and loads, counts logged errors) |
| build | target: `-buildTarget <osxuniversal\|win64\|webgl\|android\|ios\|linux64> -executeMethod …HarnessCli.Build -out <dir>`; profile: `-activeBuildProfile P -buildProfile P …`; writes `build-report.json` next to the player |
| exec | `-quit -executeMethod <M> <your args>`; no `-quit` for `Harness.Headless.HarnessCli.*` or with `--no-quit` |
| menu | `-executeMethod …HarnessCli.MenuItem -menu "Path/To/Item"`: ExecuteMenuItem, then SaveAssets, then a deferred exit (no `-quit`); fails when the item isn't found |
| screenshot | **no `-nographics`** (rendering needs a GPU), no `-quit`: `-executeMethod …HarnessCli.Screenshot -out <png> [-scene P] [-camera N] [-camPos x,y,z] [-camRot x,y,z] [-camFov f] [-width W -height H] [-timeOfDay text]`. Opens the scene (default: first enabled build scene) with `OpenScene(Single)` and never saves it; renders a temporary HideAndDontSave camera (settings copied from `-camera` or `Camera.main`), or the named camera as it is when no position/rotation is given, to a RenderTexture → `ReadPixels` → `EncodeToPNG`. Prints `[HARNESS] SHOT OK <png> WxH scene=… pos=… rot=… fov=…` and `ARTIFACT: <png>` |

### Exit codes
`0` ok · `1` failure (compile errors, Unity abort/crash, build/import/exec failed, no results XML, no tests ran) ·
`2` tests failed · `3` setup/usage (no editor for the version, missing test framework or HarnessCli, bad args) ·
`4` project open in another Unity · `124` watchdog killed Unity.

### build-report.json (HarnessCli.Build)
`result` (Succeeded|Failed|Cancelled|Unknown), `platform`, `outputPath`, `profile`, `development`, `totalSize`,
`totalErrors`, `totalWarnings`, `totalSeconds`, `startedUtc`, `endedUtc`, `productName`, `version` (bundleVersion),
`unityVersion`, `scenes[]`, `errorMessages[]`. `-out` may be a folder (player named `<productName>.app/.exe/.x86_64`;
WebGL/iOS use the folder itself) or a full player path. Default `-out` is `<root>/Builds/<platform>`.

### Editor open: MCP equivalents
| Job | Calls |
|---|---|
| compile | `refresh_unity(mode="force", compile="request", wait_for_ready=true)`, then `read_console(types=["error"])` (compile-fix-loop) |
| tests | `run_tests(mode="EditMode"\|"PlayMode", category_names=[…], assembly_names=[…], init_timeout=120000 for PlayMode)` → `get_test_job(job_id, wait_timeout=60, include_failed_tests=true)` until done |
| import | `refresh_unity(mode="force", scope="assets")` or `manage_asset(action="import", path="Assets/…")` |
| build | `manage_build(action="build", target="osx", output_path=…, development="true")` or `profile="Assets/…asset"` → poll `manage_build(action="status", job_id=…)` |
| exec | `execute_code` (group scripting_ext); HarnessCli methods log but never exit inside an interactive editor |

## Rules
- Never combine `-quit` with `-runTests`. Never pass `-version` to Unity as an argument of your own (Unity prints its version and exits).
- Always a timeout and a `-logFile`; never run two Unity processes on one project. For parallel jobs make an APFS clone
  (`cp -cR <root> <copy>`, includes `Library/`) and run there.
- Kill only the Unity processes you started (the watchdog does this; it sends TERM, then KILL after 10 s).
- `-accept-apiupdate` rewrites scripts in place: only with the user's consent and a clean git tree, then review `git diff`.
- Own `-executeMethod` code: synchronous methods use `-quit` and throw on failure (exit 1). Methods that need an exit code
  or async work (builds are synchronous, recompiles are not) call `Harness.Headless.HarnessCli.Exit(code)` and run without
  `-quit`. ⚠ version-sensitive: a synchronous `EditorApplication.Exit` at startup crashed once on 6000.3.21f1 (exit 134);
  `HarnessCli.Exit` defers it one tick and survives domain reloads. Other skills ship their own copy of this pattern
  (asset-pipeline `Harness.Assets.*Batch` via BatchExit.cs, scene-prefab-safety `SceneAudit.RunBatch`): run them with `exec … --no-quit`.
- ⚠ version-sensitive: `-build <path>` needs `-activeBuildProfile` on 6000.3.21f1; `-buildTarget` + `-build` exits 1.
  Batchmode cannot switch the active target from code: one target per invocation.
- Build Profiles must live under `Assets/` (profiles under `Packages/` fail from the CLI, forum report).
- Logs go to `<root>/Logs/harness/` (git-ignored by Unity's default `.gitignore` for `Logs/`).

## Failure handling / stop conditions
- `RESULT: FAIL setup …` (exit 3): fix the setup (install the editor version, add the test framework, install HarnessCli),
  do not retry blindly.
- `project-open` (exit 4): switch to MCP or ask the user to close the editor; never kill an editor you did not start.
- `timeout` (124): look at the log tail. First open of a cold project imports everything (minutes); raise `--timeout`
  once. A second timeout → stop and report the last 30 log lines. A run without the test framework never finishes.
- Exit 1 with `no log written`: an argument made Unity exit before opening the project (e.g. `-version`); fix the arguments.
- Unity exit 134 / `Fatal Error!` after `[HARNESS] EXIT 0`: the job succeeded but shutdown crashed; rerun once, then report.
- `no tests ran`: wrong `--filter`/`--assembly`/`--category`, or the test asmdef lacks `UNITY_INCLUDE_TESTS`/nunit
  references. Use `--allow-empty` only when zero tests is expected.
- Licensing lines (`Access token is unavailable`, `Curl error 42`) are noise when the run continues.

## References
- references/cli-reference.md: read when you need a raw flag, the four build approaches, log markers, exit codes of
  other tools (official Unity CLI beta), portable timeouts, or CI notes.

## Verify
Run on the project (or a clone) with no editor open:
- `<skills>/headless-ops/scripts/unity.sh compile` exits 0 and prints `RESULT: OK compile 0 errors …`.
- `<skills>/headless-ops/scripts/unity.sh test editmode` exits 0 and prints `RESULT: OK tests EditMode total=N passed=N failed=0 …`
  with N ≥ 1, and the XML it names has `failed="0"` on `<test-run>`.
- For builds: `unity.sh build <target|profile>` exits 0, prints `RESULT: OK build Succeeded …`, and the
  `build-report.json` it names has `"result": "Succeeded"`.
- `pgrep -f "Unity.app/Contents/MacOS/Unity.*-projectPath <root>"` returns nothing afterwards.
