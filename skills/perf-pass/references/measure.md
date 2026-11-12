# Measuring performance (Unity 6000.3)

Contents: 1. Which path · 2. Counter availability · 3. PerfProbe API and output · 4. MCP calls · 5. Headless and player runs · 6. Pitfalls

## 1. Which path
| Path | Good for | Not good for |
|---|---|---|
| Editor Play Mode + MCP (PerfProbe via execute_code, manage_profiler, manage_graphics) | fast iteration, render stats with the Game view, Frame Debugger, allocation call stacks | sign-off: editor overhead inflates ms and GC |
| Headless PlayMode test (PerfScenarioTests), batchmode WITHOUT -nographics | repeatable CPU/GC/physics numbers in CI, no editor needed | render counters (batchmode renders nothing: 0 → n/a) |
| Development player + `-perfProbe` | final numbers for budgets incl. render counters; GC without editor noise | quick iteration (needs a build: build-ship) |
| Release player + `-perfProbe` | frame time and render counters as shipped | GC alloc and Physics2D counters (not available, see table) |

## 2. Counter availability (6000.3.21f1, from ProfilerRecorderHandle.GetDescription flags)
`AvailabilityNonDevelopment` = also available in release players. Everything else: Editor and Development players only.
| PerfProbe key | Category / name | Release player |
|---|---|---|
| frame_ms | Internal / Main Thread (marker, whole frame incl. waits) | yes |
| cpu_main_ms | Render / CPU Main Thread Frame Time (work only) | yes; [UNVERIFIED] players need Player Settings > Frame Timing Stats on, else 0 (perf_report then falls back to frame_ms) |
| gc_alloc, gc_alloc_count | Memory / GC Allocated In Frame, GC Allocation In Frame Count | no |
| gc_used_mb, gc_reserved_mb, sys_used_mb | Memory / GC Used Memory, GC Reserved Memory, System Used Memory | yes |
| go_count | Memory / Game Object Count | no |
| batches, setpass, drawcalls, tris | Render / Batches Count, SetPass Calls Count, Draw Calls Count, Triangles Count | yes |
| p2d_ms | Physics2D / Physics2D.Simulate (marker) | [UNVERIFIED] markers are normally dev-only |
| p2d_bodies, p2d_awake, p2d_contacts, p2d_queries | Physics2D / Total Bodies, Awake Bodies, Total Contacts, Total Queries | no |
More counters exist (3466 handles on 6000.3: "Dynamic Batches Count", "Physics Used Memory (2D)", "Texture Memory", "Trigger Stay"...). List them in your project with `ProfilerRecorderHandle.GetAvailable(list)` + `ProfilerRecorderHandle.GetDescription(h)` (Unity.Profiling.LowLevel.Unsafe) and add a `Def` row in PerfProbe.cs.

## 3. PerfProbe API and output
- `PerfProbe.Begin(label, seconds = 0, warmup = 3, csv = null)` → probe on a DontDestroyOnLoad object; `seconds = 0` runs until `PerfProbe.End()` (returns the summary). `Current`, `IsDone`, `HasSamples`, `LastSummary`, `CsvFile`, `MeasuredFrames`.
- Command line (players and batch): `-perfProbe <label> -perfSeconds 30 -perfWarmup 3 -perfCsv <path> -perfQuit`.
- Log lines (one per window, default 1 s, then a summary):
  `[PERF] kind=start label=baseline warmup=3 seconds=20 csv=/…/Logs/harness/perf/baseline-20261106-101500.csv editor=1 dev=1 valid=frame_ms,cpu_main_ms,…`
  `[PERF] kind=summary label=baseline t=20 frames=1201 fps=60.04 editor=1 dev=1 frame_ms_avg=16.6 frame_ms_max=21.3 frame_ms_p95=16.9 cpu_main_ms_avg=4.1 … gc_alloc_avg=0 gc_alloc_max=0 gc_alloc_nz_pct=0 … p2d_bodies_avg=300 …`
- Suffixes: `_avg`, `_max`, `_p95` (times), `_nz_pct` (% of frames where gc_alloc > 0). Units: ms, bytes, MB, counts.
- CSV columns: `kind,label,t,frames,fps,editor,dev,<key>_avg,<key>_max[,_p95][,_nz_pct]…`; rows `window` and one `summary`. Empty cell = metric not available.
- The frame after each log/CSV write is not sampled (the probe's own garbage). Run-wide p95 uses the first `maxFrames` (36000) frames.
- Default CSV folder: `<project>/Logs/harness/perf/` (editor; Logs/ is git-ignored) or `Application.persistentDataPath/perf/` (player; macOS: `~/Library/Application Support/<company>/<product>/perf/`).

## 4. MCP calls (editor open; tool parameters: unity-mcp-orchestrator)
```
manage_tools(action="activate", group="profiling")          # if manage_profiler is hidden
manage_editor(action="play")                                 # then poll mcpforunity://editor/state until is_playing
execute_code(code="var p = Harness.Perf.PerfProbe.Begin(\"baseline\", 20f, 3f); return p.label;")
execute_code(code="var p = Harness.Perf.PerfProbe.Current; return p == null ? \"done\" : p.MeasuredFrames.ToString();")
read_console(action="get", types=["log"], filter_text="[PERF] kind=summary", format="plain", page_size="20")
manage_graphics(action="stats_get")                          # batches/SetPass/tris for the current frame (Game view visible)
manage_profiler(action="get_frame_timing")                   # FrameTimingManager: cpu/gpu frame times
manage_profiler(action="get_counters", category="Memory", counters=["GC Allocated In Frame","GC Used Memory"])
manage_profiler(action="frame_debugger_enable"); manage_profiler(action="frame_debugger_get_events", page_size=50); manage_profiler(action="frame_debugger_disable")
manage_profiler(action="profiler_start", log_file="Logs/harness/perf/capture.raw", enable_callstacks=true) … manage_profiler(action="profiler_stop")
manage_profiler(action="memory_take_snapshot", snapshot_path="MemoryCaptures/a.snap")   # needs com.unity.memoryprofiler
manage_profiler(action="memory_compare_snapshots", snapshot_a="MemoryCaptures/a.snap", snapshot_b="MemoryCaptures/b.snap")
manage_editor(action="stop")
```
[UNVERIFIED] these manage_profiler/manage_graphics calls were taken from the 10.3.0 schema, not exercised in this harness's tests (no editor was open). `execute_code` bodies must be C# 6 safe (no `$""`, no `out var`).
In the Editor, the Game view must be visible and unthrottled for meaningful render stats; an unfocused editor may throttle Play Mode.

## 5. Headless and player runs
- Headless test (headless-ops runner or raw): `Unity -batchmode -projectPath <p> -runTests -testPlatform PlayMode -testFilter Harness.Perf -testResults <xml> -logFile <log>` with a watchdog; no `-quit`, no `-nographics`. Verified on 6000.3.21f1: 300 dynamic bodies + 6 shots/frame scenario, 3 s at ~3–5k fps, CSVs in `Logs/harness/perf/test-*.csv`.
- Editor floor: an empty-scene probe in the same path (verified: `gc_alloc_avg≈410 B`, 10 allocations/frame, 100 % of frames). Pass it to perf_report with `--floor`.
- Player (macOS): `"<Build>/Game.app/Contents/MacOS/<Product>" -perfProbe baseline -perfSeconds 30 -perfQuit -logFile Logs/harness/perf/player.log`; feed the CSV or the log to perf_report. Set the build's resolution/quality explicitly (`-screen-width`, `-screen-height`, `-screen-fullscreen 0`) so runs are comparable. [UNVERIFIED] PerfProbe in a built player was not run in this harness's tests.
- Uncapped frame rate (batchmode, vsync off) inflates fps and hides vsync waits; budgets therefore use `cpu_main_ms` (work), not fps.

## 6. Pitfalls
- `-nographics`: ProfilerRecorder.Count stays 0, every metric empty (verified). PerfProbe warns `kind=warning reason=no-profiler-samples`; tests `Assert.Ignore`.
- Enter Play Mode Options with domain reload off keep statics: PerfProbe resets `Current` at SubsystemRegistration; your own caches must too.
- Incremental GC (default on) spreads collections but does not reduce allocation; the budget is allocation, not GC time. Web has no incremental GC.
- First seconds include shader warm-up, asset loads and JIT: keep `warmup` ≥ 3 s for scene runs; measure room transitions separately as a spike budget (e.g. `frame_ms_max <= 50`).
