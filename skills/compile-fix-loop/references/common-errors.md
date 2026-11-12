# Common compile errors in Unity 6000.3 and their fixes

Facts marked **[observed]** were reproduced on Unity 6000.3.21f1 (bench project: URP 17.3, Input System 1.20.1, Cinemachine 3.1.7, Test Framework 1.6.0, Active Input Handling = Input System only). Others are standard C#/Unity knowledge; [UNVERIFIED] marks what was not checked on 6000.3.

## How errors arrive in waves [observed]
- A **syntax error** (CS1002 `; expected`, CS1513 `} expected`, ...) hides every other diagnostic of that assembly. The log shows only it. Fix it first; the next compile shows the rest.
- **Declaration-level errors** (unknown type in a field, base class or `using`) hide method-body errors and warnings in the same assembly. After fixing them, new errors from method bodies appear. The count going up after a correct fix is normal: judge progress by root causes, not raw counts.
- **Dependent assemblies wait.** `Assembly-CSharp-Editor` (and any asmdef that references a broken one) is not compiled while its dependency has errors. Its errors only show after the dependency is clean.
- Roslyn already suppresses most cascades from an unknown type (`EnemySpawner s; s.Spawn()` gives one CS0246, not CS1061s).
- Each error is printed 2–3 times in a batchmode log (`##### Output`, `## Output:`, and once more). `parse_unity_log.py` deduplicates and reads the assembly name from `## Script Compilation Error for: Csc .../<Assembly>.dll`.

## C# error codes
| Code | Meaning | Usual Unity cause → fix |
|---|---|---|
| CS0246 | type or namespace not found | missing `using`; asmdef lacks a reference (see below); package not installed; type renamed (table below); typo. A missing namespace in a `using` line makes every type from it fail: fix the `using` first. |
| CS0234 | `X` does not exist in namespace `Y` | namespace moved (Cinemachine 3, URP `Experimental`), or asmdef reference missing. [observed] `UnityEngine.InputSystem` in an asmdef without `"Unity.InputSystem"` gives CS0234. |
| CS0012 | type defined in an assembly that is not referenced | add that assembly to the asmdef `references`. |
| CS0103 | name does not exist in the current context | typo, missing field, local out of scope, missing `using static`. |
| CS1061 | type has no member `X` | API renamed (table below) or wrong type; check with `unity_reflect(action="get_type")`. |
| CS0117 | type has no definition for static `X` | same as CS1061 for statics. |
| CS0115 | no suitable method found to override | Unity messages (`Update`, `OnEnable`) are not virtual: drop `override`; or a base API changed signature. |
| CS0029 / CS0266 / CS1503 | type conversion / argument type | real logic error; fix the type (explicit cast only when it is semantically right). |
| CS0120 | object reference required | calling an instance member statically; get the instance (serialized field, `FindFirstObjectByType`, DI). |
| CS0122 | inaccessible due to protection level | do not widen access blindly; use the public API or `[SerializeField] private`. |
| CS0101 / CS0111 | duplicate type / member | duplicate file (`Player 1.cs`, a backup copy) or same class in two folders; delete the duplicate only after confirming it is a copy. |
| CS0436 / CS0433 | type conflicts between assemblies | same type in your code and a package/plugin DLL; rename or remove one copy, check asmdef references. |
| CS0619 | obsolete API, now an error | migrate to the replacement in the message. [observed] `Physics2D.autoSimulation` → `Physics2D.simulationMode`. |
| CS0618 | obsolete API, warning | not blocking; migrate as a follow-up (list in the report). |
| CS0672 | overrides an obsolete member | warning; plan the migration (URP render passes, below). |
| CS1002 / CS1513 / CS1022 / CS1519 | syntax | missing `;`, `}`; stray token. Fix the first one per file. |
| CS0006 | metadata file could not be found | stale `Library/Bee`; recompile; if persistent, it is an infra issue for a human (reimport/`-rebuildLibrary` via headless-ops), never delete Library yourself. |

## Assembly definitions (asmdef)
- Scripts without an asmdef go to `Assembly-CSharp` / `Assembly-CSharp-Editor`, which reference every package automatically. Scripts under an `.asmdef` see **only** what it lists in `references`.
- Common names to add: `Unity.InputSystem`, `Unity.Cinemachine`, `Unity.RenderPipelines.Universal.Runtime`, `Unity.RenderPipelines.Core.Runtime`, `Unity.TextMeshPro`, `UnityEngine.UI`, `Unity.Addressables`, `Unity.ResourceManager`, `Unity.2D.Animation.Runtime`, `Unity.2D.Tilemap.Extras`, `Unity.Newtonsoft.Json`, `Unity.Mathematics`, `Unity.Collections`.
- Test asmdefs: `references` `UnityEngine.TestRunner` + `UnityEditor.TestRunner` + the game asmdef(s), `overrideReferences: true`, `precompiledReferences: ["nunit.framework.dll"]`, `defineConstraints: ["UNITY_INCLUDE_TESTS"]`, `autoReferenced: false`; EditMode tests also `includePlatforms: ["Editor"]`.
- Game code cannot reference test assemblies, and runtime asmdefs cannot use `UnityEditor` (move to an `Editor` asmdef with `includePlatforms: ["Editor"]`, or wrap in `#if UNITY_EDITOR`). Code that compiles in the editor but uses `UnityEditor` outside `#if UNITY_EDITOR` fails only in player builds.
- [observed] An asmdef `references` entry naming an assembly that does not exist (by name) is silently ignored in 6000.3: no error, the code that needs it fails with CS0246/CS0234 instead. [UNVERIFIED] GUID references (`"GUID:..."`) to missing assemblies may log "Assembly has reference to non-existent assembly".
- Optional dependencies: `versionDefines` (`{"name":"com.unity.inputsystem","expression":"1.0.0","define":"HAS_INPUTSYSTEM"}`) plus `#if HAS_INPUTSYSTEM` in code.
- Never create cycles (A → B → A); move shared types into a third asmdef.

## Renamed / moved / obsolete APIs in 6000.3
| Old | New (6000.3) | Severity on 6000.3.21f1 |
|---|---|---|
| `using Cinemachine;` | `using Unity.Cinemachine;` (Cinemachine 3.x) | CS0246 error [observed] |
| `CinemachineVirtualCamera`, `CinemachineFreeLook` | `CinemachineCamera` (+ components); keep fields typed as `CinemachineVirtualCameraBase` where possible; `m_` prefixes removed | `Unity.Cinemachine.CinemachineVirtualCamera` exists but CS0618 warning [observed] |
| `Object.FindObjectOfType<T>()` | `Object.FindFirstObjectByType<T>()` (deterministic first) or `FindAnyObjectByType<T>()` (faster, any) | CS0618 warning [observed] |
| `Object.FindObjectsOfType<T>()` | `Object.FindObjectsByType<T>(FindObjectsSortMode.None)` (sorting by InstanceID is slower; only ask for it if order matters); `FindObjectsInactive.Include` to include inactive | CS0618 warning [observed]; `FindObjectsByType(FindObjectsSortMode)` itself has no warning [observed]. ⚠ version-sensitive: InstanceID/EntityId changes after 6000.3 may affect sort-mode overloads [UNVERIFIED]. |
| `Physics2D.OverlapCircleNonAlloc`, `RaycastNonAlloc`, other `*NonAlloc` | `Physics2D.OverlapCircle(point, r, ContactFilter2D, Collider2D[] or List<Collider2D>)`, `Physics2D.Raycast(origin, dir, ContactFilter2D, RaycastHit2D[] or List<>, distance)` | ⚠ CS0618 warning: deprecated, still present [observed] |
| `ContactFilter2D.NoFilter()` | `ContactFilter2D.noFilter` (static property) | CS0618 [observed] |
| `Rigidbody2D.velocity` | `Rigidbody2D.linearVelocity` | CS0618, `(UnityUpgradable)` [observed] |
| `Rigidbody2D.drag` / `angularDrag` | `linearDamping` / `angularDamping` | CS0618, `(UnityUpgradable)` [observed] |
| `Rigidbody2D.isKinematic` | `bodyType = RigidbodyType2D.Kinematic` | CS0618 [observed] |
| `Collider2D.usedByComposite` | `compositeOperation` (`Collider2D.CompositeOperation.Merge`) | CS0618 [observed] |
| `Physics2D.autoSimulation` | `Physics2D.simulationMode = SimulationMode2D.FixedUpdate/Update/Script` | **CS0619 error** [observed] |
| `GraphicsSettings.renderPipelineAsset` | `GraphicsSettings.defaultRenderPipeline` (and `QualitySettings.renderPipeline` per level) | CS0618, `(UnityUpgradable)` [observed] |
| `UnityEngine.Experimental.Rendering.Universal.Light2D` | `UnityEngine.Rendering.Universal.Light2D` | CS0234 error [observed] |
| `ScriptableRenderPass.Execute(ScriptableRenderContext, ref RenderingData)` | `RecordRenderGraph(RenderGraph, ContextContainer)` (Render Graph) | CS0672 warning on override [observed]. ⚠ version-sensitive: whether URP Compatibility Mode (non-Render-Graph path) still runs `Execute` in 17.3 is [UNVERIFIED]; migrate rather than rely on it. |
| `PlayerSettings.GetScriptingDefineSymbolsForGroup(BuildTargetGroup)` (and `Set...`) | `PlayerSettings.GetScriptingDefineSymbols(NamedBuildTarget.Standalone)` (`using UnityEditor.Build;`) | CS0618 [observed] |
| `BuildPipeline.BuildPlayer(scenes, path, target, options)` | `BuildPlayerWithProfileOptions` / Build Profiles (see build-ship) | "will be replaced" per docs; ⚠ version-sensitive |

## Input System vs the old Input Manager
- `UnityEngine.Input.GetKey/GetAxis` **compiles** with any setting [observed] but throws `InvalidOperationException` at runtime when Player Settings > Active Input Handling is "Input System Package (New)" (`activeInputHandler: 1` in ProjectSettings.asset; 0 = old, 2 = both). It is a play-verify/console error, not a compile error.
- Fix by porting: `Keyboard.current.spaceKey.wasPressedThisFrame`, `Mouse.current.position.ReadValue()`, or better `InputAction`s / `PlayerInput` / project-wide actions (`InputSystem.actions`, [UNVERIFIED] for 1.20). Switching to "Both" is a project decision: ask.
- `UnityEngine.InputSystem` types in an asmdef need `"Unity.InputSystem"` in `references` [observed CS0234 without it].
- `Keyboard.current` can be null (no keyboard, batchmode); null-check in runtime code.

## API Updater
- Messages ending in `(UnityUpgradable) -> NewName` can be rewritten automatically. The editor offers this when opening a project; in batchmode it runs only with `-accept-apiupdate` (headless-ops: `unity.sh --accept-apiupdate compile`). It edits your `.cs` files in place: require a clean git tree and the user's consent, then review `git diff`.
- Non-upgradable obsoletes (no `(UnityUpgradable)`) must be migrated by hand.

## Not compile errors, but often confused with them
- "The referenced script on this Behaviour is missing": a `.cs` was deleted/renamed or its class name no longer matches the file name; fix the reference (scene-prefab-safety), not code.
- "No MonoBehaviour scripts in the file, or their names do not match the file name": rename the class or file so they match.
- Shader/material errors (magenta): asset-pipeline, not this skill.
- `Burst` errors (`BC####`) appear in the same console; `parse_unity_log.py` reports them as compile errors with code `BC####`.
