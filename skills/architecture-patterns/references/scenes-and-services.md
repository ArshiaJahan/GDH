# Bootstrap, additive scene loading, persistent systems, services

Files: `templates/Runtime/Scenes/{Bootstrapper,SceneLoader}.cs`, `templates/Runtime/Services/Services.cs`, `templates/Editor/PlayFromBootstrap.cs`.

## Scene layout
```
Bootstrap (build index 0, never unloaded)   SceneLoader, Bootstrapper, LoadingScreen, AudioManager, EventSystem, persistent camera if any
  + exactly one content scene, additive      MainMenu | Hub | Run | Credits
      + optional sub-scenes for a run        e.g. Run_UI loaded additively by the Run scene's own code
```
- Persistent systems live in Bootstrap instead of `DontDestroyOnLoad`; they are found via `Services` or serialized refs inside Bootstrap.
- Every scene must be enabled in the build list (Build Profiles / Build Settings). `SceneLoader.LoadContentAsync` throws `ArgumentException` otherwise (checked with `Application.CanStreamedLevelBeLoaded`). Add scenes with `manage_build(action="scenes", ...)` (see unity-mcp-orchestrator) or `EditorBuildSettings.scenes`.
- Only one `AudioListener` and one `EventSystem` across loaded scenes: keep them in Bootstrap.

## Flow
1. `SceneLoader.Awake` registers itself in `Services` (and `SceneLoader.Instance`).
2. `Bootstrapper.Start` (async): registers `JsonSaveStore`, loads `MetaProgress` (missing → new; failed → warning + new, without overwriting the file), registers it, then `await LoadContentAsync(firstContentScene, destroyCancellationToken)`.
3. `LoadContentAsync(name)`: show loading screen → unload current content scene → `LoadSceneAsync(name, Additive)` polling `progress` each `Awaitable.NextFrameAsync` → `SetActiveScene` (new objects and lighting go there) → `Resources.UnloadUnusedAssets()` → `ContentSceneLoaded` event → hide loading screen (in `finally`).
4. Gameplay asks for the next scene: `await Services.Get<SceneLoader>().LoadContentAsync("Run");` Guard double triggers with `IsLoading`.

Awaitable rules (Unity 6, 6000.3 ✓): instances are pooled; never await the same `Awaitable` twice; cancellation throws `OperationCanceledException` (catch it at the top of `async void` methods, as Bootstrapper does). [UNVERIFIED] awaiting an `AsyncOperation` directly (`await SceneManager.UnloadSceneAsync(...)`) is used in the template and compiles on 6000.3.21f1; the docs only imply it.

## Loading screen hook
Implement `ILoadingScreen` on a MonoBehaviour in Bootstrap and assign it to `SceneLoader.loadingScreen`:
```csharp
public sealed class FadeLoadingScreen : MonoBehaviour, ILoadingScreen
{
    [SerializeField] CanvasGroup group; [SerializeField] UnityEngine.UI.Slider bar;
    public async Awaitable ShowAsync() { group.blocksRaycasts = true; for (float t = 0; t < 1; t += Time.unscaledDeltaTime * 4) { group.alpha = t; await Awaitable.NextFrameAsync(); } group.alpha = 1; }
    public void SetProgress(float p) { if (bar) bar.value = p; }
    public async Awaitable HideAsync() { for (float t = 1; t > 0; t -= Time.unscaledDeltaTime * 4) { group.alpha = t; await Awaitable.NextFrameAsync(); } group.alpha = 0; group.blocksRaycasts = false; }
}
```
Use unscaled time (the game may be paused). Prewarm pools during the screen (`ComponentPool.Prewarm`).

## Play From Bootstrap (editor)
`Tools/Harness/Arch/Play From Bootstrap` (toggle, EditorPrefs) sets `EditorSceneManager.playModeStartScene` to build scene 0. On Play it stores the scene you were editing in `SessionState`; `Bootstrapper` loads that scene instead of `firstContentScene`. Turn it on with `execute_menu_item(menu_path="Tools/Harness/Arch/Play From Bootstrap")`. With it off, scenes must tolerate missing services (`Services.TryGet`).

## Service locator vs DI
- `Services` = static `Dictionary<Type, object>`: `Register<T>`, `Unregister<T>(instance)`, `Get<T>` (throws with a hint if Bootstrap is not loaded), `TryGet<T>`. Cleared at `SubsystemRegistration` (domain reload off safe).
- Use it for: save store, scene loader, audio, meta progress, analytics: few, global, created once in Bootstrap.
- Do not use it for: references inside a prefab or scene (serialized fields are explicit and visible), per-run objects (pass `RunState` to the systems that need it), anything created per enemy.
- Prefer passing dependencies in (constructor parameters for plain C# systems, serialized fields for components) and call `Services.Get` only at composition points (Awake/Start of top-level managers), never inside Update loops.
- DI container (VContainer, Zenject/Extenject): only if the team already knows it or the project has many swappable implementations/tests that need them. It adds a package, lifetime scopes and startup ordering to learn. Do not mix a container and `Services` for the same service.
- Testing: register fakes with `Services.Register<IAudio>(new FakeAudio())` in `[SetUp]`, call `Services.Reset()` in `[TearDown]`. Register interfaces (`Register<IAudio>(impl)`) when you plan to swap implementations.
