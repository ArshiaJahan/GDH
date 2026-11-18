# Determinism in record/replay v1

What the replay system guarantees and what it leaves to the game.

## Guarantees (same environment, same content)

The guarantee is repeatability in the environment you recorded in, checked
against the state you register through providers. Replay never refuses when the
environment differs (Unity version, OS, CPU, packages, content). It runs, and
the report says `environment: differs` with the differing fields.

- **Fixed timestep.** ReplayLoop sets `Time.fixedDeltaTime` and
  `Time.captureDeltaTime` to the configured dt (default 1/60). Record and
  replay use the same dt; actual fixed-tick counts per frame are recorded and
  asserted. `captureFramerate=60` is the reciprocal, not a separate clock.

- **Seeded RNG.** `GdwRandom.Reset(uint seed)` seeds an xorshift32 generator.
  Named streams (`GdwRandom.Stream("combat")`) use FNV1a stream derivation so
  different game systems draw from independent sequences. `ExportStates()` and
  `ImportStates()` let you checkpoint/restore RNG state. `UnityEngine.Random`
  is seeded with `Random.InitState(seed)` before scene initialization, and its
  state is checkpointed at every frame (exact-version limitations apply).

- **Input replay.** `InputEventTrace` records every input event with
  `recordFrameMarkers=true`. Replay uses
  `trace.Replay().WithAllDevicesMappedToNewInstances().PlayAllFramesOneByOne()`
  with manual input processing — exactly one controlled input update per replay
  frame. Physical gameplay input is suppressed; virtual devices replace it.

- **Script-mode physics.** `Physics.simulationMode = SimulationMode.Script` and
  `Physics2D.simulationMode = SimulationMode2D.Script`. Each physics scene is
  simulated once per scheduled fixed tick, after gameplay FixedUpdate, with the
  recorded fixed dt. No double simulation.

- **Frame-by-frame checkpoint hashes.** Every frame records an aggregate
  SHA-256 hash of all registered providers plus per-provider hashes. The
  initial state (frame −1) is checkpointed before any gameplay. At replay, each
  checkpoint is compared: mismatch at the first divergent frame, tick, and
  provider.

- **State providers.** Framework providers cover transforms (position,
  rotation, scale, active), rigidbody pose/velocity/sleep state (3D and 2D),
  RNG streams, scene identity, and input trace metadata. Games register
  additional providers via `IReplayStateProvider`.

- **ReplayLoop teardown.** On success, error, cancellation, reload or PlayMode
  exit: prior time, input, physics and loop settings are always restored.

## What is NOT deterministic in v1

These sources of divergence are expected and not covered:

- **Timer-based Input System interactions** (Hold, Tap with custom timeout
  parameters). They are not guaranteed to replay identically, because replayed
  events can shift timer expiry. Avoid them in recorded paths.

- **Async operations.** `AsyncOperation`, `UniTask`, `await`, job system
  completion order depends on thread scheduling.

- **`MonoBehaviour` callback order.** `Awake`, `OnEnable`, `Start`, etc. across
  multiple objects is not guaranteed to be deterministic.

- **`timeScale` changes.** Replay sets `Time.timeScale` to 1 and restores it
  afterwards. Game code that changes it at runtime can diverge.

- **Unscaled time.** `Time.unscaledTime` and `Time.unscaledDeltaTime` are not
  fixed by `captureDeltaTime`. Use `ReplayClock.UnscaledTime` in opted-in code.

- **HitStop and real-time waits.** Effects that wait wall-clock time diverge.

- **Legacy Input Manager.** Gameplay that reads `Input.GetAxis`,
  `Input.GetKey`, etc. is not supported. The Editor scans for it when a run
  starts and refuses to record or replay, naming the files and calls.

- **FixedUpdate on the first frame.** Replay steps physics exactly once per
  frame, but your own `FixedUpdate` callbacks can still run twice on frame 0.
  Keep first-frame gameplay out of `FixedUpdate`, or register its state so a
  difference shows up in the hashes.

- **Network, file I/O, timers, coroutine resume order.** All can vary between
  runs. Buffer external results at recorded tick barriers or reject them.

- **PhysX/Box2D floats.** Even with script-mode simulation, physics floats
  offer no cross-CPU or cross-version guarantee. A replay on a different CPU,
  OS or Unity version can diverge; the report shows `environment: differs`.
- **State you don't register.** Only registered providers are hashed. A
  difference in unregistered state is not detected.

## How to improve determinism in game code

1. Replace `UnityEngine.Random.Range` calls with `GdwRandom.Stream("name")`.
2. Register state providers for HP, inventory, objectives, timers.
3. Use `ReplayClock.Delta` / `ReplayClock.Tick` instead of `Time.deltaTime` /
   `Time.frameCount` in timed logic.
4. `IReplaySnapshot` (capture/restore) ships in the package and is used only
   if a game registers it. Replay always starts from a scene reset or load.
5. Avoid `System.Random` — its seed-dependent sequence still depends on
   call order. Use `GdwRandom` or provide an explicit state adapter.
6. Read inputs through the Input System (`InputAction`, `InputActionMap`)
   rather than legacy `Input` class calls.

## Framework providers

| Provider ID | Fields |
|---|---|
| `unity.transforms` | count, &lt;sid&gt;.position (VEC3), .rotation (QUAT), .scale (VEC3), .active (BOOL) |
| `unity.physics` | count, &lt;sid&gt;.position, .rotation, .linear_velocity, .angular_velocity, .sleeping (BOOL) |
| `unity.rng` | seed (U32), stream.&lt;name&gt;.state (U32), stream.&lt;name&gt;.draws (U64) |
| `unity.scene` | guid (STRING), path (STRING), loaded (U32) |
| `unity.input` | events (U64), frames (U64), trace_sha256 (STRING) |
| `unity.snapshot` | adapter_id (STRING) + game fields prefixed `snapshot.` |

## Reading

- [Unity `Time.captureDeltaTime` docs](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Time-captureDeltaTime.html)
- [Unity `Physics.Simulate` docs](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Physics.Simulate.html)
- [Unity `InputEventTrace` docs](https://docs.unity3d.com/Packages/com.unity.inputsystem@1.20/api/UnityEngine.InputSystem.LowLevel.InputEventTrace.html)
- [InputRecorder sample (Unity)](https://github.com/Unity-Technologies/InputSystem/tree/develop/Assets/Samples/InputRecorder)
