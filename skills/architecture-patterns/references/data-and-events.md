# Data definitions, runtime sets, variables, event channels

Files: `templates/Runtime/Data/*`, `templates/Runtime/Events/*`. Namespace `Harness.Arch`, assembly `Game.Runtime`.

## Definitions (static design data)
- `Definition : ScriptableObject` holds `Id` (stable string stored in saves), `DisplayName`, `Icon`. `OnValidate` fills an empty id from the asset name (lowercase, spaces → `_`). Set ids deliberately for anything that ships: renaming an asset must not change saves.
- Concrete examples: `EnemyDef` (health, speed, contact damage, `spawnWeight`, `minDepth`, prefab), `ItemDef` (rarity, price, stackable, `requiresUnlock`).
- New type: one file per class, file name == class name (Unity needs this for ScriptableObject/MonoBehaviour assets):
  ```csharp
  [CreateAssetMenu(menuName = "Harness/Definitions/Weapon", fileName = "WeaponDef")]
  public sealed class WeaponDef : Definition { [Min(0)] public int damage = 1; public float cooldown = 0.3f; }
  ```
- `DefinitionDatabase` lists every definition. `TryGet<T>(id, out def)` resolves ids from saves; `OfType<T>()` builds loot/spawn tables; `Validate()` returns null entries, empty and duplicate ids. Add an EditMode test that loads the real database asset (`AssetDatabase.LoadAssetAtPath<DefinitionDatabase>(...)`) and asserts `Validate()` is empty.
- Spawn tables: `rng.WeightedIndex(defs.Select(d => d.spawnWeight).ToList())` with the run's `SeededRng`; filter by `minDepth` first.
- Create assets with `manage_scriptable_object(action="create", type_name="Harness.Arch.EnemyDef", folder_path="Assets/Game/Data/Enemies", asset_name="Slime", patches=[...])` (see unity-mcp-orchestrator for the patch format) or the Create menu.

## Runtime sets
- `RuntimeSet<T>` is an asset holding a live list (never serialized). `TransformRuntimeSet` is the concrete example; `RuntimeSetMember` on a prefab adds itself in `OnEnable`, removes in `OnDisable`.
- Use for "every enemy alive" (wave clear check `set.Count == 0`), "every interactable in range" candidates, minimap markers. `Added`/`Removed` events let UI react without polling.
- New set type: `[CreateAssetMenu(...)] public sealed class EnemyRuntimeSet : RuntimeSet<Enemy> { }` plus a member component typed to it.

## Variables
- `Variable<T>`: `InitialValue` is serialized; the runtime `Value` lives in a `[NonSerialized]` field, so Play Mode never dirties the asset. `Changed` fires only on real changes.
- `IntReference` = inspector toggle between a constant and an `IntVariable`. Good for tuning values shared by several prefabs.
- Do not use variables for state that must be saved; copy into `RunState`/`MetaProgress` instead.

## Event channels
- `VoidEventChannel` (no payload) and `EventChannel<T>` (`IntEventChannel` example). `Raise(...)` invokes the C# event; zero listeners is fine.
- `EventListener<T, TChannel>` MonoBehaviour forwards a channel to a `UnityEvent<T>` for designer wiring (`IntEventListener`, `VoidEventListener`). Code subscribers use `channel.Raised += Handler` in `OnEnable` and `-=` in `OnDisable`.
- New payload type, three files:
  ```csharp
  [Serializable] public struct DamageInfo { public int amount; public Vector2 point; }
  [CreateAssetMenu(menuName = "Harness/Events/Damage Channel")] public sealed class DamageEventChannel : EventChannel<DamageInfo> { }
  public sealed class DamageEventListener : EventListener<DamageInfo, DamageEventChannel> { }
  ```

### SO channel vs plain C# event
| Situation | Pick |
|---|---|
| Sender and receivers in different scenes/prefabs, wired in the Inspector (RunEnded → UI, audio, analytics) | SO channel |
| Designers need to hook responses without code | SO channel + listener |
| Owner is known and code-only (Health → its own HealthBar) | `public event Action<int> Changed` |
| High frequency (per frame, per bullet) | plain C# event or direct call (no asset lookup, no UnityEvent cost) |
| Needs a return value or ordering guarantees | direct method call / interface |
Avoid both for request/response; call a service method instead.

## Domain reload off (Enter Play Mode Options)
⚠ version-sensitive: Unity 6 lets you disable domain reload; ScriptableObjects and statics then keep runtime state between Play sessions. Every runtime-state SO implements `IResettable` and registers with `RuntimeAssetReset` in `OnEnable`; `RuntimeAssetReset.ResetAll()` runs at `SubsystemRegistration` and clears set contents, variable values and channel subscribers. Add the same to every new stateful SO. Test: `EventChannelTests.ResetRuntimeState_DropsStaleSubscribers`.
