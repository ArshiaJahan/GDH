# Driving the game during play-verify

Pick the lightest option that reaches the state a criterion needs. All options work in the Editor (MCP path); options A, B and D also work inside PlayMode tests (headless path).

## A. Call game code (no input simulation, no dependencies)
Best when the game has debug entry points, or when the criterion is about the result of an action, not the input mapping.
- `execute_code` during Play Mode (method body, returns a value):
  ```
  GameObject.Find("Player").SendMessage("DebugAttack");
  return Harness.Verify.VerifyProbe.DumpAll();
  ```
- In a ScriptedInput script: `send Player DebugAttack`, `send Spawner SpawnWave 3`, `call MyGame.Cheats.SetSeed 1234` (static method, any loaded assembly, 0 or 1 argument).
- Add small debug methods to game code behind `#if UNITY_EDITOR || DEVELOPMENT_BUILD` (e.g. `Cheats.Teleport(roomId)`, `Cheats.KillAll()`) rather than reaching into private fields.
- execute_code compiles every loaded assembly as a reference, so `Harness.Verify.*` and game types are visible by full name. With the CodeDom fallback it is C# 6: no `$"..."`, no `out var`; `Object` is ambiguous (System + UnityEngine), write `UnityEngine.Object`. Blocked by safety checks: `while(true)`, `File.Delete`, `Process.Start`, `EditorApplication.Exit`, `AssetDatabase.DeleteAsset`.

## B. Virtual keyboard through the Input System (tests the real bindings)
Best when the criterion is "pressing X does Y" or the game reads `PlayerInput`/actions only.
- `Harness.Verify.InputSystem/VirtualKeyboard.cs` adds an Input System `Keyboard` device and queues `KeyboardState` events, so `InputAction`s, `PlayerInput`, project-wide actions and `Keyboard.current` see real key presses. It installs itself as `ScriptedInput.KeyHandler` (Editor and development builds).
- Script commands: `down Space`, `up Space`, `tap Space [frames]`, `hold LeftArrow 0.8`. Key names are `UnityEngine.InputSystem.Key` names (case-insensitive) plus `left right up down jump esc`.
- It sets `InputSettings.editorInputBehaviorInPlayMode = AllDeviceInputAlwaysGoesToGameView` and `backgroundBehavior = IgnoreFocus` so input arrives with the Game view unfocused, and restores both on quit (exit Play Mode).
- Gamepad/mouse: same pattern (`InputSystem.AddDevice<Gamepad>()` + `InputSystem.QueueStateEvent(pad, new GamepadState{ buttons = ... })`); add only when a criterion needs it.
- Legacy Input Manager (`UnityEngine.Input.GetKey`) cannot be fed this way. If the project's Active Input Handling is "Input System Package (New)" only, `Input.GetKey` throws InvalidOperationException at runtime; use option A for such code or port it.
- Prior art on this Mac: `~/HtmlTo2D/Assets/_Project/Scripts/Runtime/DevTools/DebugInputDriver.cs` (same technique) and `.../Editor/Playtest/Autopilot.cs` (timed command scripts with `until` conditions, run from execute_code).

## C. InputTestFixture (PlayMode tests only)
The Input System's own test helper isolates devices per test and gives `Press(key)`, `Release`, `PressAndRelease`, `Set(control, value)`.
- Needs the package's test assembly: add `"testables": ["com.unity.inputsystem"]` to `Packages/manifest.json` and reference `Unity.InputSystem.TestFramework` and `Unity.InputSystem` from the test asmdef. [UNVERIFIED] for Input System 1.20: class name `UnityEngine.InputSystem.InputTestFixture`, derive the test class from it (or call `Setup()`/`TearDown()`).
- It replaces all devices with test devices for the test's duration, so real-keyboard code paths and `VirtualKeyboard` must not be mixed in the same test. Prefer option B unless you need per-test device isolation.

## D. Autoplay bot (long runs, soak tests, roguelike floors)
A game-specific MonoBehaviour that plays by simple rules (move toward nearest enemy, attack when in range, take the exit when the room is clear) through the same public methods the input layer calls. Keep it in a `Debug`/`DevTools` folder behind `#if UNITY_EDITOR || DEVELOPMENT_BUILD`; let it keep counters with `VerifyProbe.Set("rooms.cleared", n)` (checked by `metric:rooms.cleared >= 3`) and `VerifyProbe.Mark("boss.dead")` at milestones (checked by `log:"event=boss.dead"`).

## Determinism
- Seed every random source from one seed and log it: `VerifyProbe.Log("seed", seed)`. Re-runs with the same seed must produce the same `[VERIFY]` values.
- `fps N` in ScriptedInput sets `Time.captureFramerate`, so game time advances exactly 1/N per rendered frame however slowly the editor renders; `wait`/`hold` are then frame-exact. Turn it off (`fps 0`) for real-time fps metrics.
- Prefer `until key op value timeout` over fixed waits; fixed waits flake when the editor is busy or unfocused.
- Batchmode play jobs with `Time.captureFramerate`, screenshots at game seconds and video: see the prior art in `~/Documents/SHAY_PC/SHAY_PC/Tools/unity-cli/shay play` (README in the same folder); run such jobs through headless-ops.
