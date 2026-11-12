# Unity 6000.3 command line: flags, exit codes, log markers, CI notes

Read when you need a flag that `unity.sh` does not wrap, want to run Unity without the wrapper, or interpret a log or
exit code. "✓ local" = observed on this Mac (6000.3.21f1, Apple Silicon); "✓ docs" = 6000.3 manual; [UNVERIFIED] = neither.

## Editor binary and version
- `/Applications/Unity/Hub/Editor/<ver>/Unity.app/Contents/MacOS/Unity`, `<ver>` = `m_EditorVersion` in
  `ProjectSettings/ProjectVersion.txt` (✓ local). Override with `UNITY_PATH`.
- `-version` prints the editor version and exits **without opening the project** (✓ local: exit 0, no log written).
  Never use `-version` as an argument name for your own `-executeMethod` code.

## Core flags (✓ docs, behaviour notes ✓ local where marked)
| Flag | Notes |
|---|---|
| `-batchmode` | No UI, dialogs suppressed; exception in startup code or `-executeMethod` → exit 1. Cannot open a project that an editor already has open. |
| `-nographics` | No GPU device. Fine for compile, EditMode/PlayMode logic tests and Standalone builds (✓ local: macOS build). Cannot bake GI; tests that render need graphics. |
| `-quit` | Quit after the other commands. **Never with `-runTests`** (quits before tests finish). Waits `-quitTimeout` s (default 300) for async work. |
| `-projectPath <dir>` | Project root. |
| `-logFile <file>` | Always pass it; with `-nographics` there is no other log. `-` = stdout. |
| `-executeMethod Ns.Class.Method` | Static method in an Editor assembly. Fail by throwing (exit 1, with `-quit`) or a deferred `EditorApplication.Exit(n)` (`HarnessCli.Exit`, no `-quit`; never synchronously, see Pitfalls). Args via `Environment.GetCommandLineArgs()`. |
| `-accept-apiupdate` | Lets the API Updater rewrite obsolete API in your scripts during batchmode (in place: clean git tree + consent). |
| `-buildTarget <t>` | Active target for this run. `osxuniversal`, `win64`, `webgl`, `android`, `ios`, `linux64` (docs list); `StandaloneOSX` also accepted (✓ local "Targeting platform: StandaloneOSX"). |
| `-activeBuildProfile <Assets/…asset>` | Activates a Build Profile for the run; its scripting defines compile before `-executeMethod`. Keep profiles under `Assets/` (from `Packages/` it fails, forum report). |
| `-build <path>` | Built-in player build. ⚠ version-sensitive: on 6000.3.21f1 it **requires `-activeBuildProfile`** (✓ local: with only `-buildTarget` the log says `-build is expected to be used along with -activeBuildProfile argument.` and exits 1). |
| `-buildOSXUniversalPlayer <path>`, `-buildWindows64Player <path>` | Legacy one-flag builds (✓ docs, not tested here). |
| `-standaloneBuildSubtarget Player\|Server` | Standalone subtarget. |
| `-ignorecompilererrors` | Do not use: hides real errors. |
| `-stackTraceLogType Full`, `-timestamps` | More detail in the log. |
| `-rebuildLibrary` | Full reimport; slow. Only with the user's consent. |
| `-disable-playback-engines` | Skip loading platform modules (faster open when not building). |
| `-forgetProjectPath`, `-upmLogFile <f>` | Keep the Hub's recent list clean / Package Manager log. |

## Test Framework flags (✓ docs; Test Framework 1.6.0 is a core package in 6000.3)
`-runTests -testPlatform EditMode|PlayMode|<BuildTarget> -testResults <xml>` plus optional
`-testFilter "A;B"` (regex, `!` negates), `-testCategory "A;!B"`, `-assemblyNames "a;b"`, `-runSynchronously`
(EditMode only; drops `[UnityTest]`), `-repeat N`, `-retry N`, `-randomOrderSeed N`, `-testSettingsFile f.json`,
`-playerHeartbeatTimeout s`.
- Missing `com.unity.test-framework` in `Packages/manifest.json` → `-runTests` **hangs forever** at 100% CPU (✓ local).
  Check the manifest first and always use a watchdog.
- Results are NUnit 3 XML: root `<test-run total passed failed skipped inconclusive result duration>`, one
  `<test-case fullname result>` per test with `<failure><message/><stack-trace/></failure>` (✓ local).
- Unity documents no common exit-code contract for tests: trust the XML, not the exit code.

## Build approaches (pick one per invocation; one target per invocation)
1. `-executeMethod Harness.Headless.HarnessCli.Build -buildTarget osxuniversal -out <dir>` (unity.sh `build macos`). ✓ local.
2. `-executeMethod Harness.Headless.HarnessCli.Build -activeBuildProfile P -buildProfile P -out <dir>` (unity.sh `build P`):
   `BuildPipeline.BuildPlayer(BuildPlayerWithProfileOptions)` ✓ local.
3. Built-in: `-quit -activeBuildProfile Assets/Settings/BuildProfiles/macOS.asset -build <out>/Game.app` ✓ local
   (log `Build Finished, Result: Success.`, exit 0). No JSON report; parse the log.
4. `-quit -buildTarget X -build <out>`: fails on 6000.3.21f1 (see `-build` above).
- Batchmode cannot switch target from code: `BuildProfile.SetActiveBuildProfile`, `EditorUserBuildSettings.SwitchActiveBuildTargetAsync`
  and `BuildPlayerOptions.target` ≠ active target do not work. Start Unity with the target or profile instead (✓ docs).
- Scenes: `-scenes "Assets/A.unity;Assets/B.unity"` (HarnessCli) > profile scene list (if `overrideGlobalScenes`) > `EditorBuildSettings.scenes`.
- Build Profiles have no public creation API in 6000.3 (create them in File > Build Profiles). The internal
  `BuildProfile.CreateInstance(BuildTarget, StandaloneBuildSubtarget)` worked by reflection (✓ local) but is not public API.

## Exit codes
| Source | Codes |
|---|---|
| Unity editor | 0 ok · 1 compile errors / exception / `Aborting batchmode` (✓ local) · 2 tests failed (✓ local: `Test run completed. Exiting with code 2 (Failed)`) · 134 crash (abort trap) |
| HarnessCli entry points | 0 ok · 1 failed · 2 bad arguments/setup (via deferred `EditorApplication.Exit`) |
| unity.sh | 0 ok · 1 failure · 2 tests failed · 3 setup/usage · 4 project open · 124 watchdog timeout |
| test_summary.py | 0 all passed · 2 failures · 1 unreadable XML or no tests ran |
| Official Unity CLI (beta) | 0 ok · 1 general · 2 bad args · 4 precondition · 6 command failure · 8 tests failed · 143 SIGTERM (per the CLI's own docs; 8 and 6 [UNVERIFIED] locally) |

## Log markers (grep these)
- `Exiting batchmode successfully now!` · `Batchmode quit successfully invoked - shutting down!` (ok)
- `error CS\d+` with `Assets/…cs(line,col)` · `Scripts have compiler errors.` · `Aborting batchmode due to failure:`
- `Test run completed. Exiting with code N (Ok|Failed)` · `Saving results to:`
- `Build Finished, Result: Success.` (built-in `-build`) · `[HARNESS] BUILD Succeeded …` / `[HARNESS] REPORT <json>` (HarnessCli)
- `executeMethod class 'X' could not be found` · `Multiple Unity instances cannot open the same project`
- `##utp:{…}` JSON lines (editor/project/compile info)
- Ignore: `Error: Access token is unavailable; failed to update`, `Curl error 42`, `debugger-agent: Unable to listen`,
  `Thread … may have been prematurely finalized`.

## Pitfalls seen on 6000.3.21f1
- `EditorApplication.Exit(code)` called synchronously inside `-executeMethod` at startup crashed once during domain
  unload (`Fatal Error! GetManagerFromContext: pointer to object of manager 'MonoManager' is NULL`, Burst frames,
  exit 134) even though the method had finished. HarnessCli defers Exit by one editor tick (`EditorApplication.delayCall`)
  and stores the code in `SessionState` so a domain reload (forced recompile) cannot swallow it. Run such methods
  without `-quit`. Synchronous methods that only throw on failure are fine with `-quit`.
- A watchdog kill leaves a stale `Temp/UnityLockfile`; the next run opens the project normally (✓ local).
- Only one Unity process per project. Copy the project (on APFS `cp -cR` makes a near-free clone, incl. `Library/`)
  to run jobs in parallel.

## HarnessCli.MenuItem and `-buildOutput`
- `-executeMethod Harness.Headless.HarnessCli.MenuItem -menu "Path/To/Item"` runs the menu item (`unity.sh menu "Path/To/Item"` wraps it), calls
  `AssetDatabase.SaveAssets()` and exits through the deferred `HarnessCli.Exit`; run it without `-quit`.
- `-buildOutput <dir>` is accepted as an alias of `-out` (HarnessCli.Build).

## Run on a copy (GameDevWorkstation `clone_when_open`)
With the Editor open and no live route, the `unity` tool can run compile/tests (official CLI batch) on an APFS copy at
`~/Library/Caches/GameDevWorkstation/unity-clones/<hash>/`: `cp -cR` the first time, then rsync of `Assets/`, `Packages/`
and `ProjectSettings/` only. Results are labelled "on a copy of the files on disk (unsaved Editor changes not included)".

## Portable timeout on macOS (no GNU `timeout`)
- unity.sh: background Unity + background watchdog subshell; **redirect both to /dev/null** (a background `sleep` that
  inherits the caller's stdout keeps tool calls hanging until it ends). TERM, 10 s grace, then KILL.
- One-liner: `perl -e 'alarm shift; exec @ARGV' 900 "$U" -batchmode … -logFile log` (SIGALRM ends Unity; ✓ local for a
  normal run, the kill path itself [UNVERIFIED]).

## Official Unity CLI (beta; GameDevWorkstation's `cli` / `auto` Unity backend)
`~/.unity/bin/unity` and `/Applications/Unity Hub.app/Contents/Resources/unity`, 1.0.0-beta.13 (not on PATH in non-login
shells). `unity test <proj> --mode EditMode --output r.xml --non-interactive --timeout 300 [--json]` ✓ local (exit 0, JSON
`{success, data.reports.nunit}`). GameDevWorkstation runs it through the `unity` tool; equivalents (✓ `--help`, beta.13):

| unity.sh | Official CLI (`--format json`; Editor log on stderr) | Notes |
|---|---|---|
| `compile` (closed) | `unity run <proj> --timeout T --log-file L -- -nographics` | batch + `-quit` added by the CLI; Unity's exit code |
| `compile` (open, Pipeline) | `unity recompile --project-path <proj> --timeout T` | exit 0 ok · 6 errors (`data.errors[]` file/line/column/code/message) · 7 no Editor ✓ local |
| `test editmode --category C` | `unity test <proj> --mode EditMode --output X --timeout T -- -testCategory C -nographics` | no `--category` flag; exit 0 · 8 tests failed · 6 no verdict (`TEST_TIMED_OUT`, `TEST_RUN_ERROR`) |
| `build <target>` | `unity build <proj> --target T \| --profile P --output-path O --log-file L --timeout T` | verdict from the log; exit 6 = failed; `data.outputPath` |
| `exec M` | `unity run <proj> -- -executeMethod M` | always `-quit`: HarnessCli methods (deferred Exit) stay on unity.sh |

Reserved after `--` (exit 6 before any Editor starts, ✓ local): `-batchmode -quit -projectPath -useHub -hubIPC` (+ for
`test`: `-runTests -testPlatform -testResults -testFilter` and the coverage trio). `unity status` with no Editor: exit 6
`STATUS_NO_INSTANCES` ✓ local; `unity command` with no Editor: exit 6 ✓ local. Live tests: Pipeline 0.10 names the command
`test run` (args `mode` editor|playmode|all, `filter`, `filter-type` testName|assembly|category, `timeout` s), the 1.0 docs
`run_tests`; read the Editor's list (`unity command --query test --format json`). Editor params go after a `--` fence
(the CLI eats its own `--timeout` anywhere in the tail). [UNVERIFIED] whether `unity run/test` start the Editor in their
own process group (GameDevWorkstation kills the CLI's group and then sweeps `-batchmode` Unity with this `-projectPath`).

## CI notes
- One job per platform (one target per Unity invocation); serialise jobs per project copy.
- Cache `Library/` per platform and Unity version; a cold import of the bench took 73 s, warm compile ~9 s.
- Always `-logFile`, keep the log as an artifact; publish NUnit XML; fail on the XML, not only on the exit code.
- Licensing on a fresh machine needs the Hub/licence client to have activated the editor (batchmode here resolves the
  entitlement through the running Hub's LicenseClient).
