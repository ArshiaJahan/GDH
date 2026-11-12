# Roguelike structure: run vs meta, seeded RNG, pooling

Files: `templates/Runtime/Roguelike/{RunState,MetaProgress,SeededRng,ComponentPool,PooledObject}.cs`. Tests: `SeededRngTests`, `SaveSystemTests`, `PoolTests`, PlayMode `ListenerPlayModeTests.Pool_WorksInPlayMode`.

## Run state vs meta-progression
| | RunState (`run.json`) | MetaProgress (`meta.json`) |
|---|---|---|
| Lifetime | created at run start, deleted on death/win | forever |
| Holds | seed, depth, health, run currency, item ids, RNG stream states | unlocks, persistent currency, stats (`runsStarted`, `runsWon`, `bestDepth`) |
| Saved | on room/floor transitions and on quit (suspend/resume) | after each run ends and after purchases |
| Reads | `DefinitionDatabase.TryGet` for item ids | `IsUnlocked(id)` filters loot tables |

Run lifecycle:
```csharp
uint seed = RunSeed.CreateAndLog();            // logs "[RNG] run seed = N" (or RunSeed.FromString("2026-11-06") for a daily run)
var run = RunState.NewRun(seed, maxHealth: 5);
meta.runsStarted++; store.Save("meta", meta);  // count the run before it can be abandoned
store.Save("run", run);                         // at every floor transition
// death or win:
meta.currency += run.runCurrency / 2; meta.bestDepth = Mathf.Max(meta.bestDepth, run.depth);
store.Save("meta", meta); store.Delete("run");
```
Resume: `store.TryLoad<RunState>("run", out var run)` → `ok` means continue; the RNG streams continue exactly where they stopped (`RoundTrip_RunState_ResumesRngExactly`).

## Seeded RNG
- `SeededRng`: xorshift32 on a lowbias32-hashed seed, `[Serializable]` with one `uint state` field, so it round-trips through JsonUtility. Class (not struct) to avoid silent copies. API: `NextUInt`, `Range(int,int)` (max exclusive, no modulo bias), `NextFloat` [0,1), `Range(float,float)`, `Chance(p)`, `Pick(list)`, `WeightedIndex(weights)` (−1 if all zero), `Shuffle(list)` (Fisher-Yates), `State`/`FromState`.
- `RngStreams(seed).Get("map")`: independent stream per subsystem, seeded from `Hash(seed ^ FNV1a(name))`, so loot rolls never shift the map. Streams used by `RunState`: `map`, `loot`, `combat`. Add more names freely; never rename an existing one after release.
- `RunSeed.CreateAndLog(context)` logs `[RNG] <context> seed = N`; `RunSeed.FromString(text)` is FNV-1a (stable across platforms, unlike `string.GetHashCode`).
- Not for cryptography. Visual-only randomness (particles, screen shake) may use `UnityEngine.Random`; anything that changes game state uses the run's streams.
- Determinism also needs: fixed iteration order (no `HashSet`/`Dictionary` enumeration when rolling), no `Time.deltaTime`-dependent rolls, rolling at logical events rather than per frame.
- Golden values in `KnownValues_AreStableAcrossPlatformsAndVersions` (seed 42 → 3669911245, 3667817022, 2414785042; `FromString("2026-11-06")` → 1881022441) were computed by an independent Python implementation. They protect shared seeds and saved runs; do not edit them.
- Reproduce a bug: copy the seed from the log line, start a run with `RunState.NewRun(thatSeed, ...)`.

## Pooling
- `ComponentPool<T>(prefab, parent, defaultCapacity=16, maxSize=512, collectionCheck=true)` wraps `UnityEngine.Pool.ObjectPool<T>` (stack-based, not thread-safe). `Get(pos, rot)`, `Release(item)`, `Prewarm(n)`, `Clear()`, `Dispose()`, counts.
- Each instance gets a `PooledObject` handle: the object returns itself with `GetComponent<PooledObject>().ReturnToPool()` (bullet hits wall). `IPoolable.OnSpawned/OnDespawned` on any child component reset state (health, velocity, trail renderers).
- `collectionCheck` throws on double release (keep it on in development; `PoolTests.DoubleRelease_Throws`). Over `maxSize`, released objects are destroyed.
- Pool per prefab, owned by a spawner or registered in `Services` for global FX. Prewarm during the loading screen. Clear pools when the content scene unloads (pooled objects parented to the content scene are destroyed with it; parent them to a Bootstrap-scene root if they must persist).
- Pool when the profiler shows Instantiate/GC spikes or more than ~10 spawns/s of one prefab (bullets, hit sparks, damage numbers, pickups). Do not pool rare, unique objects (bosses, rooms).
