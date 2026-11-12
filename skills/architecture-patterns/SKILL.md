---
name: architecture-patterns
description: Drops dependency-free C# architecture templates (namespace Harness.Arch) into Unity 6 (6000.3) 2D roguelikes - ScriptableObject definitions and runtime sets, SO event channels, an Input System InputReader, versioned JSON saves with migrations, bootstrap + additive scene loading, a service locator, asmdef layout, run-vs-meta state, a seeded RNG and pooling, with EditMode/PlayMode tests. Use when starting a game's code structure, adding saves/input/scene flow/events/pooling/RNG, or deciding which pattern fits.
---

# architecture-patterns

Pick the smallest pattern that solves the problem, drop in the matching template, keep it compiling and tested.

Pinned: Unity 6000.3 LTS (tested 6000.3.21f1, macOS), Input System 1.20.x, Test Framework 1.6.0, URP 17.3 2D. No third-party packages.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. mcp__UnityMCP__read_console). For tool parameters see unity-mcp-orchestrator. `<skill>` = this skill's folder.

## When to use / not to use
- Use when a project has no code structure yet, or when adding: data definitions, cross-system events, input, saving, scene flow, global services, run/meta state, seeded randomness, pooling, assembly definitions.
- Not for: fixing compile errors (compile-fix-loop), proving behaviour in Play Mode (play-verify), import settings (asset-pipeline), scene/prefab edits (scene-prefab-safety), profiling (perf-pass).

## Which pattern when
| Need | Use | Not |
|---|---|---|
| Static design data (enemies, items, upgrades) | `Definition` subclasses + `[CreateAssetMenu]`, one `DefinitionDatabase` | Hard-coded stats, JSON for data designers edit in the Inspector |
| Save references to data | `Definition.Id` (string) | Object refs, asset paths, GUIDs in save files |
| "All enemies alive", "all interactables" | `RuntimeSet<T>` + `RuntimeSetMember` | `FindObjectsByType` every frame, static lists |
| Shared value read by many (HP for HUD) | `Variable<T>` (`IntVariable`) | Singletons with public fields |
| One-to-many, cross-scene, designer-wired (PlayerDied, RunEnded) | SO `EventChannel<T>` / `VoidEventChannel` + listener | `SendMessage`, `FindObjectOfType` |
| Owner-known, code-only, same object/system (Health.Changed) | plain C# `event Action<T>` | An SO asset per event (asset sprawl, harder to follow) |
| Input | `InputReader` SO raising C# events | Polling `Keyboard.current` in gameplay; old `UnityEngine.Input` (throws when Active Input Handling = Input System) |
| Persistent progress | `JsonSaveStore` + `SaveData` subclass + `SaveMigrator` | `PlayerPrefs` for anything but settings; `BinaryFormatter` (unsafe, obsolete) |
| Scene flow | Bootstrap scene + `SceneLoader` (additive, one content scene) | `DontDestroyOnLoad` sprawl, `LoadScene` single-mode for everything |
| Global systems (save store, audio, loader) | `Services` locator, registered in Bootstrap | Locator for scene-local refs (use serialized fields) |
| Run vs meta | `RunState` (dies with the run) vs `MetaProgress` (survives) | One mixed save object |
| Randomness | `SeededRng` + `RngStreams` from a logged run seed | `UnityEngine.Random` / `System.Random` in gameplay |
| Bullets, hit FX, damage numbers | `ComponentPool<T>` (wraps `UnityEngine.Pool.ObjectPool<T>`) | Instantiate/Destroy per shot |

Service locator vs DI: the static `Services` map is enough for a solo 2D roguelike (a handful of globals, registered once in Bootstrap). Prefer constructor/serialized-field injection inside systems; adopt a DI container (VContainer, Zenject) only when the team already uses one; never mix two styles for the same service. Details: [references/scenes-and-services.md](references/scenes-and-services.md).

## Inputs
- Project root, which patterns are wanted (default: all), the game's root folder (default `Assets/Game/`), first content scene name.
- Whether the editor is open (MCP route) or closed (batchmode via headless-ops).

## Procedure
1. **Precheck.** Read `mcpforunity://instances`, `set_active_instance`, then `mcpforunity://editor/state`: require `ready_for_tools` and not `is_compiling`. `read_console(types=["error"])` must be empty before you start (otherwise compile-fix-loop first). Check `Packages/manifest.json` for `com.unity.inputsystem` (InputReader needs ≥ 1.8) and `com.unity.test-framework`.
2. **Check for clashes.** Search the project for existing asmdefs named `Game.Runtime`/`Game.Editor`/`Game.Tests.*` and types in namespace `Harness.Arch`. If a project already has its own runtime asmdef, add the template files to it (and add its reference to `Unity.InputSystem`) instead of creating a second one.
3. **Copy templates** (new files only, so Unity creates the `.meta`s; never copy `.meta` files):
   ```bash
   G="$P/Assets/Game"; T=<skill>/templates
   mkdir -p "$G"; cp -R "$T/Runtime" "$T/Editor" "$G/"; mkdir -p "$G/Tests"; cp -R "$T/Tests/EditMode" "$T/Tests/PlayMode" "$G/Tests/"
   ```
   Pick-and-choose instead: copy only the folders you need plus their dependencies and delete tests for removed parts (dependency table in [references/asmdef-and-tests.md](references/asmdef-and-tests.md)).
   Rename the namespace only once, before the first compile, in every file and in each asmdef's `rootNamespace`.
4. **Compile.** Editor open: `refresh_unity(compile="request", wait_for_ready=true)`, then `read_console(types=["error"])` = 0 entries. Editor closed: headless-ops compile (or `Unity -batchmode -nographics -quit -projectPath "$P" -logFile <log>`; exit 0 and no `error CS` in the log).
5. **Wire the scenes** (scene-prefab-safety rules apply; use manage_scene/manage_gameobject/manage_components):
   - Create `Assets/Game/Scenes/Bootstrap.unity` with GameObjects `SceneLoader` (+ optional loading screen implementing `ILoadingScreen`) and `Bootstrapper` (`firstContentScene` = your menu/run scene). Bootstrap must be build index 0; every content scene must be in the build list.
   - Turn on `Tools/Harness/Arch/Play From Bootstrap` (`execute_menu_item`) so Play always starts in Bootstrap and then loads the scene you were editing.
6. **Create assets** with `manage_scriptable_object` or the Create menu (`Harness/Definitions/*`, `Harness/Events/*`, `Harness/Variables/*`, `Harness/Runtime Sets/*`, `Harness/Input/Input Reader`). Put them under `Assets/Game/Data/`. Fill `DefinitionDatabase` with every definition; ids must be unique and never change after release.
7. **Extend by subclassing**, never by editing the generic bases: new payload = `XEventChannel : EventChannel<X>` + `XEventListener : EventListener<X, XEventChannel>`, each in its own file named after the class; new definition = `class WeaponDef : Definition`; new save = `class SettingsSave : SaveData` with its own slot name.
8. **Save changes = new version.** Bump `CurrentVersion`, keep the old DTO as a nested `V<n>` class, register `Register<V<n>, New>(n, map)`, add a migration test with a literal old JSON string. Read [references/save-system.md](references/save-system.md) before changing any save shape.
9. **Run tests** (Verify). Then add game-specific tests next to the templates (e.g. `DefinitionDatabase.Validate()` on the real database asset).

## Rules
- **Layer, don't replace:** when replacing a system, prefab or scene, build the new one beside the old, verify parity with play-verify, then remove the old in a separate step with user approval. Use the harness's `replace-system` workflow when available.
- Definitions are read-only at runtime. Runtime state lives in `RunState`/`MetaProgress`, `Variable<T>` (never written to the asset) or plain C# objects.
- Every SO with runtime state implements `IResettable` and registers with `RuntimeAssetReset`; statics reset in `[RuntimeInitializeOnLoadMethod(SubsystemRegistration)]`. ⚠ version-sensitive: with Enter Play Mode Options "domain reload" off (Unity 6 Project Settings > Editor), statics, SO fields and event subscribers survive between Play sessions.
- Listeners subscribe in `OnEnable` and unsubscribe in `OnDisable`, always. A channel raise with zero listeners is legal and silent.
- Gameplay code never touches `InputAction`s; it subscribes to `InputReader` events. Switch maps via `EnableGameplay()`/`EnableUI()`. ⚠ version-sensitive: project-wide actions (`InputSystem.actions`, Input System ≥ 1.8) are used when `InputReader.actions` is empty; Unity 6 templates ship `Assets/InputSystem_Actions.inputactions` with maps `Player`/`UI` (action names in InputReader are configurable). [UNVERIFIED] the 1.20 docs page for project-wide actions (404 during research); behaviour verified only by compile.
- Saves: `JsonUtility` by default (no `Dictionary`, no polymorphism, no top-level arrays, needs `[Serializable]` + public/`[SerializeField]` fields). Use Newtonsoft (`com.unity.nuget.newtonsoft-json`) only when you need those, behind your own serializer seam. Write only through `JsonSaveStore.Save` (temp file + fsync + replace, `.bak` kept). Never overwrite a save that failed to load or is newer than the build.
- Save files store ids, numbers, strings and RNG state only; never Unity object references, scene names that may be renamed, or floats used as keys.
- One run seed per run, logged at start (`[RNG] run seed = N`) and stored in `RunState.seed`; separate streams (`map`, `loot`, `combat`) so extra loot rolls never change the map. Do not change `SeededRng` math: the golden-value test protects shared seeds and saved runs.
- Pools: every pooled object resets itself in `IPoolable.OnSpawned`; never `Destroy` a pooled object, call `ReturnToPool()`; `ObjectPool<T>` is not thread-safe.
- Scene loading: never await the same `Awaitable` twice; never call `LoadContentAsync` while `IsLoading`; scenes not in the build list throw.
- Assemblies: runtime code in `Game.Runtime` (no `UnityEditor` references outside `#if UNITY_EDITOR`), editor code in `Game.Editor` (Editor platform only), tests in `Game.Tests.EditMode`/`Game.Tests.PlayMode` with `UNITY_INCLUDE_TESTS`. Scripts outside any asmdef (Assembly-CSharp) can use `Game.Runtime`, but not the other way round.

## Failure handling / stop conditions
- `error CS0246 ... InputSystem`: the Input System package is missing or < 1.8; InputReader compiles out (versionDefine `HARNESS_INPUT_SYSTEM`). Install the package or delete `Runtime/Input/`.
- Duplicate type/assembly errors after copying: a clash from step 2. Remove the duplicate files you just added (exact paths, with their new `.meta`) and merge into the existing assembly instead.
- `KnownValues_AreStableAcrossPlatformsAndVersions` fails: someone changed RNG math. Revert it; do not update the golden values unless the user accepts that all shared seeds/saved runs change.
- Migration test fails: fix the migration step, never the test's old JSON (it represents files already on players' disks).
- More than 2 compile-fix iterations on template code: stop and report the errors with file(line) (template drift vs. Unity version).

## References
- [references/data-and-events.md](references/data-and-events.md): read when creating definitions, runtime sets, variables or event channels, or choosing SO channels vs C# events.
- [references/save-system.md](references/save-system.md): read before adding a save file, changing a save shape, or switching to Newtonsoft.
- [references/scenes-and-services.md](references/scenes-and-services.md): read when setting up Bootstrap, additive loading, a loading screen, persistent systems, or service locator vs DI.
- [references/input.md](references/input.md): read when wiring InputReader, action maps, rebinding or UI/gameplay switching.
- [references/roguelike.md](references/roguelike.md): read when designing run/meta state, seeds, daily runs or pooling.
- [references/asmdef-and-tests.md](references/asmdef-and-tests.md): read when adding assemblies, picking a subset of templates, or writing/running the tests.

## Verify
1. **Compiles:** `read_console(types=["error"])` returns 0 entries after `refresh_unity(compile="request", wait_for_ready=true)`; or batchmode compile exits 0 and the log has no `error CS`.
2. **EditMode tests pass:** `run_tests(mode="EditMode", assembly_names=["Game.Tests.EditMode"])` → `get_test_job(job_id, wait_timeout=60)` shows `failed=0` and at least 26 passed (save round-trip/migration, event channels, RNG determinism + golden values, pools). Batchmode: `Unity -batchmode -nographics -projectPath "$P" -runTests -testPlatform EditMode -assemblyNames Game.Tests.EditMode -testResults <xml> -logFile <log>` (no `-quit`, wrap in a timeout) → `<test-run ... failed="0">` and exit 0.
3. **PlayMode tests pass** (if Tests/PlayMode was copied): same with `mode="PlayMode"` / `-testPlatform PlayMode`; 2 Harness tests passed, `failed="0"`.
4. **Wiring** (if step 5 ran): Play from Bootstrap logs `[RNG] ... seed =` when a run starts (if your run start calls `RunSeed.CreateAndLog`), the content scene becomes active, and `read_console(types=["error"])` stays at 0 entries.
