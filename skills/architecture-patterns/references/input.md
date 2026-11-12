# Input: InputReader over the Input System

File: `templates/Runtime/Input/InputReader.cs` (compiled only when `com.unity.inputsystem` ≥ 1.8 via the `HARNESS_INPUT_SYSTEM` versionDefine in `Game.Runtime.asmdef`). Tested on Input System 1.20.1.

## Setup
1. Project Settings > Player > Active Input Handling = Input System Package (or Both). ⚠ version-sensitive: with "Input System" only, any `UnityEngine.Input.*` call throws `InvalidOperationException` (the bench project is set this way).
2. Actions asset, pick one:
   - Project-wide actions (default): Project Settings > Input System Package > Project-wide Actions. Unity 6 templates ship `Assets/InputSystem_Actions.inputactions` with maps `Player` (Move, Look, Attack, Interact, Crouch, Jump, Previous, Next, Sprint) and `UI` (Navigate, Submit, Cancel, Point, Click, ...) (checked in the 6000.3.21f1 2D template package). Leave `InputReader.actions` empty to use `InputSystem.actions`. [UNVERIFIED] the 1.20 docs page for project-wide actions (404 during research); the API compiles and is used by the template.
   - Explicit `InputActionAsset`: assign it to `InputReader.actions`. Use this when the project has several assets or for tests.
3. Create the reader asset: Create > Harness/Input/Input Reader (`Assets/Game/Data/InputReader.asset`). Set action paths if your names differ: `moveAction = "Player/Move"`, `attackAction = "Player/Attack"`, `interactAction = "Player/Interact"`, `dashAction = "Player/Sprint"`, `pauseAction = "UI/Cancel"`.

## Use
```csharp
public sealed class PlayerController : MonoBehaviour
{
    [SerializeField] InputReader input;
    Vector2 move;
    void OnEnable()  { input.Move += OnMove; input.Dash += OnDash; input.EnableGameplay(); }
    void OnDisable() { input.Move -= OnMove; input.Dash -= OnDash; }
    void OnMove(Vector2 v) => move = v;
    void OnDash() { /* start dash */ }
}
```
- Events: `Move(Vector2)` (also on cancel with zero), `AttackStarted`, `AttackCanceled` (hold-to-charge), `Interact`, `Dash`, `Pause`. Polling alternative: `MoveValue`.
- Map switching: `EnableGameplay()` (Player on, UI off, pause action kept on), `EnableUI()` (UI on, Player off, sends `Move(Vector2.zero)` so characters stop), `DisableAll()` for cutscenes/loading.
- Add an action: add a `[SerializeField] string xAction`, an `event Action X`, bind/unbind in `Bind`/`Unbind`, a handler. Keep gameplay ignorant of `InputAction`.

## Rules
- One InputReader asset per player. Local co-op: one asset per player with separate `InputActionAsset` copies (or `PlayerInput` + `PlayerInputManager`; then let PlayerInput own the actions and feed the reader instead).
- Do not enable/disable action maps from gameplay scripts; go through the reader so UI/gameplay state stays consistent.
- Rebinding: `asset.FindAction(path).PerformInteractiveRebinding()`; persist `asset.SaveBindingOverridesAsJson()` in a settings save (`SettingsSave`), restore with `LoadBindingOverridesFromJson` before `EnableGameplay`.
- Tests: Input System test helpers (`InputTestFixture`, in `Unity.InputSystem.TestFramework`) need the package's test assembly referenced; for logic tests prefer calling the subscriber methods directly. play-verify covers driving real input.
- The reader holds no state across domain-reload-off sessions except bindings; `OnDisable` unbinds.
