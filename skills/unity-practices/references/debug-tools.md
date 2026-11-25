# Debug scenes and tools for repeated issues

Scaffold once per project: `scaffold.py debug-kit --out Assets/Game/Debug --namespace <Ns>`. You get:
- `DebugOverlay`: FPS, frame ms, GC alloc in frame, custom watch values (`DebugOverlay.Watch("enemies", n)`). Toggle with F1 (Input System or the old Input Manager). Shown in the editor and development builds only.
- `DebugCommands`: static methods marked `[DebugCommand("god")]` run from a small console (backquote key), and from the agent: `DebugCommands.Run("spawn Grunt 10")` through MCP `execute_code`, or a `-executeMethod` entry point.
- `DebugDraw`: gizmo helpers (range circles, paths, labels) that run only when Gizmos are on, so they are free in builds.
- `Editor/DebugSceneBuilder`: menu `Tools/Debug/Create Debug Scene` builds `Assets/Scenes/Debug/Debug_<Name>.unity` with a camera, light, ground, the overlay and spawn points, plus the prefab under test. One scene per recurring problem, kept in the repo.

## Workflow for a repeated issue
1. `issue_cache.py find "<symptom>"`. On a hit, apply the stored fix and check it in the stored debug scene.
2. On a miss: reproduce the issue in a debug scene (the builder makes one in a single menu call), with just the systems involved.
3. Add a `[DebugCommand]` that recreates the state (for example `spawn Grunt 50`, `hp 1`), so the repro takes one call next time.
4. Add `DebugOverlay.Watch` values for the variables involved.
5. Fix the issue. Then `issue_cache.py add "<symptom>" --fix "..." --files ... --scene Assets/Scenes/Debug/Debug_<Name>.unity`.
6. If it can come back, add a PlayMode test that loads the debug scene and asserts the behaviour (play-verify / headless-ops).

## Rules
- Debug code is stripped from release builds: `#if UNITY_EDITOR || DEVELOPMENT_BUILD`, or `[Conditional]` methods.
- Debug scenes are not in the Build Profile's scene list.
- Log with a tag prefix (`[AI]`, `[POOL]`) so logs can be filtered and parsed by scripts.
