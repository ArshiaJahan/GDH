---
name: perf-pass
description: Runs a profiler-driven performance pass on Unity 6 (6000.3) 2D games - budgets (16.6 ms at 60 fps, 0 B GC per frame, batches, Physics2D ms), baseline via the runtime PerfProbe ([PERF] lines + CSV) or MCP manage_profiler, a GC/draw-call/physics checklist, and perf_report.py before/after proof. Use when the game has low FPS, stutter, GC spikes or too many draw calls, or when asked to optimize, profile or meet a perf budget.
---

# perf-pass

Measure, fix one thing, measure again: every change is justified by a before/after number against a budget.

Pinned: Unity 6000.3.21f1, URP 17.3 (2D Renderer), MCP for Unity 10.3.0, Test Framework 1.6.0, Memory Profiler 1.2.x, Profile Analyzer 1.4.x.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. `mcp__UnityMCP__manage_profiler`). For tool parameters see unity-mcp-orchestrator. `<skills>` = the folder holding these skills.

## When to use / not to use
- Use when a frame budget is missed or at risk, before a milestone/release, after adding a system that scales with entity count, or when play-verify shows `fps` drops.
- Not for compile errors (compile-fix-loop), visual polish (game-feel-pass), import settings alone (asset-pipeline), build size/packaging (build-ship).

## Inputs
- Target platform + frame rate (default 60 fps), the worst-case scenario (scene, enemy/projectile/particle counts, room size), and any budgets from the GDD (Technical Constraints). Ask if the scenario is unknown: measuring an idle scene proves nothing.

## Budgets (defaults in perf_report.py; record project values in PERF.md)
| Key | Default | Meaning |
|---|---|---|
| `cpu_main_ms_p95` | ≤ 16.6 | main-thread work per frame, 95th percentile (60 fps). Falls back to `frame_ms_p95` |
| `gc_alloc_avg` | ≤ 0 B | managed allocation per frame in steady state (after warm-up; loads/room transitions excluded) |
| `batches_avg` | ≤ 100 | render batches (tune per art style; 2D with atlases usually far lower) |
| `setpass_avg` | ≤ 30 | SetPass calls (material/shader switches) |
| `p2d_ms_p95` | ≤ 2.0 | `Physics2D.Simulate` per frame |
30 fps target: `--budget cpu_main_ms_p95<=33.3`. Mobile/Web: leave 20–30 % headroom for thermals and the missing incremental GC on Web.

## One-time setup
1. Copy `<skills>/perf-pass/templates/Harness.Perf/` to `Assets/Harness/Perf/` (Runtime asmdef `Harness.Perf`, no dependencies; Tests/PlayMode has a scenario template + probe self-test). Run compile-fix-loop.
2. Create `PERF.md` at the project root from references/PERF.template.md: scenario, budgets, run log.

## Procedure
1. **Precheck (MCP path).** `set_active_instance`; read `mcpforunity://editor/state` (`ready_for_tools`, not compiling). `manage_profiler` is in the `profiling` group and `execute_code` in `scripting_ext`: if hidden, `manage_tools(action="activate", group=...)`.
2. **Scenario.** Make the worst case reproducible: a test scene or debug method that spawns N enemies + projectiles + particles in a large tilemap room, fixed seed. Same scenario for every measurement.
3. **Audit.** Run `python3 <skills>/perf-pass/scripts/unity_antipatterns.py --project <game> --baseline <game>/.workspace/antipatterns-baseline.json` before profiling; use the top-files score table and `via Class.Method` paths to guide where to look. For changed code add `--changed Assets/...cs`; the whole project remains indexed. Read references/antipatterns.md for rules, fixes, suppressions and the baseline ratchet. Use `--update-baseline` to record reviewed existing debt; new findings remain work items. Static findings guide measurement; they do not justify an optimization on their own.
4. **Baseline.** Pick one path (details and counter availability: references/measure.md):
   - **Editor, MCP:** `manage_editor(action="play")`, wait for `is_playing`, then `execute_code`: `var p = Harness.Perf.PerfProbe.Begin("baseline", 20f, 3f); return p.label;`. Drive the scenario (play-verify's ScriptedInput or a debug call). Poll `execute_code("var p = Harness.Perf.PerfProbe.Current; return p == null ? \"done\" : p.MeasuredFrames.ToString();")` until `done`; read the summary with `read_console(action="get", types=["log"], filter_text="[PERF] kind=", format="plain", page_size="50")`. The `kind=start` line has the CSV path (`Logs/harness/perf/baseline-<time>.csv`). Add render stats from `manage_graphics(action="stats_get")` and frame timing from `manage_profiler(action="get_frame_timing")` with the Game view visible.
   - **Headless PlayMode test:** copy `PerfScenarioTests.Scenario_Swarm` to your scene; run `<skills>/headless-ops/scripts/unity.sh test playmode --filter <name>` (PlayMode runs never get `-nographics` there; raw: `-runTests -testPlatform PlayMode -testFilter <name>`, no `-nographics`, never `-quit`, with a timeout). CSV: `Logs/harness/perf/test-<label>.csv`.
   - **Development player (final numbers):** build-ship Development build, run `<app> -perfProbe baseline -perfSeconds 30 -perfQuit`; CSV in `Application.persistentDataPath/perf/`, `[PERF]` lines in Player.log.
   - Editor runs only: also record a floor (same path, empty scene, label `floor`) for `--floor`.
5. **Read the baseline.** `python3 <skills>/perf-pass/scripts/perf_report.py --after <baseline.csv> [--floor <floor.csv>]`. Every FAIL is a work item; n/a means the metric was not measured on this path (e.g. render counters in batchmode).
6. **Find the cause before fixing.** Which bucket is over: CPU scripts, GC, rendering, physics, particles?
   - GC: `manage_profiler(action="profiler_start", log_file="Logs/harness/perf/gc.raw", enable_callstacks=true)`, run 5 s, `profiler_stop`; ask the user to open the .raw in the Profiler window (Hierarchy, sort by GC Alloc) or search the code for the checklist patterns below.
   - Draw calls: `manage_profiler(action="frame_debugger_enable")`, `frame_debugger_get_events(page_size=50)`: consecutive draws that did not batch name the reason (different texture/material, sorting interleave). `frame_debugger_disable` afterwards.
   - Physics: `p2d_bodies/p2d_awake/p2d_contacts/p2d_queries` in the summary; `manage_physics` for the layer collision matrix and settings.
7. **Fix one item** from the checklist (code: references/fixes.md). Compile (compile-fix-loop), run the same scenario, label `after-<fix>`.
8. **Compare.** `perf_report.py --after <after.csv> --baseline <baseline.csv> [--floor ...] --md Logs/harness/perf/<run>.md`. Keep the fix only if its target metric improved and nothing regressed. Repeat 6–8 until budgets pass.
9. **Memory (long runs, room transitions).** With com.unity.memoryprofiler: `manage_profiler(action="memory_take_snapshot", snapshot_path="MemoryCaptures/room1.snap")` after room 1 and again after room 10, then `memory_compare_snapshots(snapshot_a, snapshot_b)`. Growth in textures, GameObjects or managed objects between equivalent states = leak (unreleased Addressables, static lists, event subscriptions). MemoryCaptures/ is git-ignored.
10. **Log.** Append the run table, fixes and any accepted exceptions to PERF.md; commit per vcs-hygiene. BACKLOG.md perf rows (`metric:frame_ms_p95 <= 16.6`, `metric:gc_alloc_avg == 0`) are checked by play-verify's `check_criteria.py`, which reads the `[PERF] kind=summary` keys from the console dump or log.

## Checklist (2D roguelike)
GC (target 0 B/frame in steady state)
- [ ] Pool everything spawned in play: projectiles, enemies, pickups, VFX, damage numbers (`UnityEngine.Pool.ObjectPool<T>`, or architecture-patterns `ComponentPool`). No per-frame `Instantiate`/`Destroy`.
- [ ] No LINQ, lambdas capturing locals, `foreach` over non-List interfaces, `params` calls, boxing (`object`, non-generic collections, enum keys without a comparer) or string concat/interpolation in Update/FixedUpdate/LateUpdate.
- [ ] UI text only on change (cache the last value; prebuilt digit strings); no `ToString()` per frame.
- [ ] Cache `GetComponent`, `Camera.main`, `FindObjectsByType` results in Awake; never call Find* per frame.
- [ ] Physics2D queries: `ContactFilter2D` + reused `List<T>` or array overloads (`Physics2D.OverlapCircle(p, r, filter, list)`). ⚠ version-sensitive: the `*NonAlloc` variants are deprecated on 6000.3 (warning CS0618), not removed; migrate when touched.
- [ ] Reuse collections (`Clear()`, preallocated capacity); `WaitForSeconds` instances cached; Awaitable instead of per-call coroutines where it helps.
CPU / scripts
- [ ] Hundreds of enemies: one manager loop updating plain arrays beats hundreds of `Update()` calls; spread AI/pathfinding over frames (round-robin), throttle target searches (e.g. 10 Hz).
- [ ] No `Debug.Log` in hot paths of release builds (strip or guard with a define).
Rendering (URP 2D)
- [ ] Sprite Atlas per area/character set so sprites share textures; same material for sprites that should batch; avoid interleaving sorting layers/orders between atlases.
- [ ] Keep SRP Batcher on (URP asset) and the shader variant count low; MaterialPropertyBlocks on SpriteRenderers opt them out of SRP batching while set (Flash in game-feel-pass clears its block). [UNVERIFIED] exact 2D Renderer batching rules; confirm with the Frame Debugger.
- [ ] Tilemaps: `TilemapRenderer.mode = Chunk` (static terrain, one atlas per tilemap) or `SRPBatch`; `Individual` only when sprites must sort between tiles. Modes on 6000.3: Chunk, Individual, SRPBatch.
- [ ] 2D lights and shadows are expensive per light: cap lights per screen; use unlit sprites where lighting adds nothing.
- [ ] Overdraw: big transparent sprites and full-screen particles cost fill rate; check with the Scene view Overdraw mode.
Particles
- [ ] `main.maxParticles` set per system, pooled systems (`Emit` on one shared system instead of one system per hit), no collision/lights modules on mass effects, culling mode Automatic, `Stop Action` Disable for pooled ones.
Physics 2D
- [ ] Layer Collision Matrix: projectiles collide only with what they hit (`manage_physics` collision matrix); enemies do not need to collide with each other unless designed.
- [ ] Bodies sleep (Sleeping Mode Start Awake is fine, never Never Sleep in mass); kinematic for scripted movers; triggers for pickups; CircleCollider2D over Polygon where possible; TilemapCollider2D + CompositeCollider2D for terrain.
- [ ] Fixed Timestep 0.02 (or 1/60 if the game needs it), `Physics2D.simulationMode` FixedUpdate (Script only with a reason); Auto Sync Transforms off; move bodies with `Rigidbody2D.MovePosition`/`linearVelocity` (⚠ `velocity` is obsolete on 6000.3, CS0618), not `transform.position`.
Memory and loading
- [ ] Texture import: correct max size, compression, no Read/Write; audio: Vorbis/ADPCM + Load Type by length (asset-pipeline owns the settings).
- [ ] Release Addressables handles; unsubscribe events in OnDisable; clear static caches between runs.

## Rules
- Measure first; never optimize without a baseline number, never keep a change that does not move its metric.
- Same scenario, same path, same machine state for baseline and after. Editor numbers are indicative; budgets are signed off in a Development player.
- One fix per measurement so the effect is attributable; revert fixes that do not help.
- Never relax a budget silently. A missed budget the user accepts goes in with `--accept KEY="reason"` and a PERF.md entry (who, date, why).
- Do not leave probes, profiler recording or the Frame Debugger enabled; remove `PerfProbe.Begin` calls from game code before shipping (the command-line path is fine).
- ⚠ version-sensitive: batchmode `-nographics` never completes profiler frames: every ProfilerRecorder stays empty (PerfProbe logs `kind=warning reason=no-profiler-samples`). Batchmode editor runs also render nothing (batches/setpass are 0 → n/a).

## Failure handling
- `no-profiler-samples`: re-run without `-nographics`, or in the editor/player.
- Editor `gc_alloc_avg` over budget with no floor: WARN, not FAIL. Measure a floor run or a Development player before chasing it (an empty scene in an Editor PlayMode test allocates ~0.3–0.4 KB/frame on 6000.3.21f1).
- Numbers noisy (p95 jumps > 20 % between identical runs): longer run (`seconds` 30+), close other apps, fixed seed, run 3× and use the median; report the noise.
- A fix regresses another metric: revert, note it in PERF.md, try the next item.
- Stop and ask when the remaining cost is content (art density, design counts): that is a design trade-off, not a code fix.

## References
- references/antipatterns.md: read when running the static audit, investigating a rule, suppressing a reviewed exception or updating the baseline.
- references/measure.md: read when choosing a measurement path, mapping counters to editor/player availability, or using manage_profiler/manage_graphics.
- references/fixes.md: read when applying a checklist item (code patterns for pooling, Physics2D queries, zero-alloc text, batching, tilemaps, particles, physics settings).
- references/PERF.template.md: read when creating or appending to PERF.md.

## Verify
- `python3 <skills>/perf-pass/scripts/unity_antipatterns.py --project <game> --baseline <game>/.workspace/antipatterns-baseline.json` exits 0 with `RESULT: OK <n> findings (0 new)`; accepted debt is in the reviewed baseline and any suppression includes a reason.
- `python3 <skills>/perf-pass/scripts/perf_report.py --after <after> --baseline <baseline> [--floor <floor>]` exits 0 and prints `RESULT: OK`: every budgeted metric PASS, ACCEPTED (user-approved, recorded in PERF.md) or n/a with a stated reason, and no `REGRESSED` row.
- Both runs are the same scenario and path: the summary lines show the same `label` prefix, `editor`/`dev` flags and similar `frames`; for render budgets at least one run came from the editor with Game view or a player (render counters not n/a).
- `read_console(action="get", types=["error"], format="json", page_size="200")` during the after-run returned 0 entries, and PERF.md has the new run row.
