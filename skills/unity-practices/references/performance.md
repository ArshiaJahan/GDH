# Performance

Measure first: profile a development build on the target device (Profiler, Deep Profile only for short captures). The editor adds overhead, so its numbers are not the game's. If perf-pass is installed, use its budgets and `perf_report.py` for before/after proof.

## Find the bound
- CPU main thread > frame budget (16.6 ms at 60 fps, 33.3 ms at 30): scripts, physics, animation, UI.
- Render thread / GPU: draw calls, overdraw, shaders, resolution, post-processing.
- Spikes: GC collections, `Instantiate`, asset loading, shader compilation (prewarm with a `ShaderVariantCollection`), `Resources.Load`.

## Common fixes (most frequent first)
1. GC allocations per frame: string building in Update (labels, debug logs), LINQ, closures/lambdas capturing variables, `foreach` on non-List collections in older code, boxing (enum keys in Dictionary without a comparer), `GetComponents` without a list. Target 0 B/frame. `cs_lint.py` finds most of these.
2. Instantiate/Destroy in combat: use pooling.md.
3. Many Updates: a manager that ticks a list beats 1,000 MonoBehaviour Updates. Throttle AI (enemies.md).
4. Physics: set the layer collision matrix; use NonAlloc queries; keep the fixed timestep at 0.02 unless needed; no mesh colliders on moving objects; `Physics.autoSyncTransforms` off (the default).
5. UI (uGUI): split static and dynamic Canvases; turn off Raycast Target on non-interactive graphics; don't animate layout groups; TextMeshPro `SetText` with number arguments instead of string concatenation.
6. Rendering: SRP Batcher-compatible shaders; GPU instancing for repeated meshes; GPU Resident Drawer (URP Forward+, SRP Batcher on, Graphics > BatchRendererGroup Variants = Keep All) for many static meshes; LODs; occlusion culling; static batching for static level geometry; lower the render scale on mobile.
7. Logs: `Debug.Log` is expensive and allocates. Strip it with `[Conditional("ENABLE_LOGS")]` wrappers or disable Stack Trace in player settings.

## In-game numbers
The debug-kit `DebugOverlay` shows FPS, frame ms, GC alloc in frame and pool counts, using `ProfilerRecorder` ("GC Allocated In Frame", "Main Thread"), which works in development builds.

## Checklist
- [ ] Bound identified (CPU, GPU or spikes) with a capture on the target.
- [ ] 0 B GC/frame during gameplay; no Instantiate in combat.
- [ ] Batches/SetPass counted before and after.
- [ ] The fix is measured, not assumed: ms before → after.
