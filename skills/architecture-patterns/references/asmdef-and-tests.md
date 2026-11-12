# Assembly definitions, picking a subset, tests

## Layout
```
Assets/Game/
  Runtime/Game.Runtime.asmdef            all platforms; refs Unity.InputSystem; versionDefine HARNESS_INPUT_SYSTEM (inputsystem >= 1.8.0); autoReferenced
  Editor/Game.Editor.asmdef              Editor only; refs Game.Runtime
  Tests/EditMode/Game.Tests.EditMode.asmdef   Editor only; refs Game.Runtime, UnityEngine.TestRunner, UnityEditor.TestRunner;
                                              overrideReferences + nunit.framework.dll; defineConstraints UNITY_INCLUDE_TESTS; autoReferenced false
  Tests/PlayMode/Game.Tests.PlayMode.asmdef   all platforms; same references/constraints as EditMode
```
- `rootNamespace` = `Harness.Arch` (Editor: `Harness.Arch.Editor`, tests: `Harness.Arch.Tests`). New scripts created inside get that namespace.
- Adding package references: add the assembly name to `references` (e.g. `Unity.Cinemachine`, `Unity.Addressables`, `Unity.Newtonsoft.Json`, `UnityEngine.UI`, `Unity.RenderPipelines.Universal.Runtime`, `Unity.2D.Animation.Runtime`). Asmdefs do not see packages automatically (only Assembly-CSharp does).
- Optional packages: reference them by name plus a `versionDefines` entry and wrap the code in `#if <DEFINE>` (as InputReader does), so the assembly still compiles without the package.
- Scripts outside any asmdef (Assembly-CSharp) can use `Game.Runtime` types (autoReferenced) but `Game.Runtime` cannot use them. Move gameplay code into `Game.Runtime` (or a further asmdef that references it) as soon as tests need it.
- Grow by feature, not by layer, once compile times matter: e.g. `Game.Combat` → refs `Game.Runtime`. Avoid cycles (Unity refuses them).
- Editor-only code inside runtime files: `#if UNITY_EDITOR` (as `Definition.OnValidate` and `Bootstrapper` do). Never reference `UnityEditor` otherwise, or player builds fail.

## Dependencies between template parts
| Part | Needs |
|---|---|
| Data (Definition, DefinitionDatabase, RuntimeSet, Variable, RuntimeAssetReset) | nothing |
| Events | Data/RuntimeAssetReset.cs |
| Input | com.unity.inputsystem ≥ 1.8 (compiles out otherwise) |
| Save | nothing |
| Roguelike/SeededRng | nothing |
| Roguelike/RunState, MetaProgress | Save, SeededRng |
| Roguelike/ComponentPool, PooledObject | nothing (UnityEngine.Pool) |
| Services | nothing |
| Scenes/SceneLoader | Services |
| Scenes/Bootstrapper | Services, SceneLoader, Save, MetaProgress |
| Editor/PlayFromBootstrap | Bootstrapper |
| Tests: EventChannelTests | Events, Data |
| Tests: SaveSystemTests | Save, RunState, MetaProgress, SeededRng |
| Tests: SeededRngTests | SeededRng, RunState |
| Tests: PoolTests, PlayMode tests | ComponentPool, PooledObject (PlayMode also IntEventChannel/IntEventListener) |
Delete tests whose parts you did not copy; keep the rest.

## Tests shipped
EditMode (26): EventChannelTests 6 (void/typed channel, no-listener raise, stale-subscriber reset, Variable reset, DefinitionDatabase lookup + duplicate ids), SaveSystemTests 8, SeededRngTests 8 (same seed/same sequence, different seeds, golden values, stream independence, JSON state round-trip, Range bounds and coverage, Shuffle determinism, WeightedIndex), PoolTests 4. PlayMode (2): listener forwards to UnityEvent while enabled; pool return in Play Mode.

## Running
- MCP: `run_tests(mode="EditMode", assembly_names=["Game.Tests.EditMode"])` → `get_test_job(job_id=..., wait_timeout=60, include_failed_tests=true)`. PlayMode: `mode="PlayMode"`, `init_timeout=120000`.
- Batchmode (project closed), with a timeout; `-quit` must NOT be combined with `-runTests` (it exits before the tests finish):
  ```bash
  "$UNITY" -batchmode -nographics -projectPath "$P" -runTests -testPlatform EditMode \
    -assemblyNames Game.Tests.EditMode -testResults "$P/Logs/editmode.xml" -logFile "$P/Logs/editmode.log"
  ```
  Pass: exit 0, log has `Test run completed. Exiting with code 0`, XML root `<test-run ... failed="0">`. Compile errors: exit 1, no XML, `error CS` lines in the log. headless-ops wraps this with a watchdog.
- Tests write saves to a temp folder and create SOs with `ScriptableObject.CreateInstance` (destroyed in TearDown); they never touch project assets or `persistentDataPath`.
