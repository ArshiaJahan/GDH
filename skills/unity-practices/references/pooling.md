# Object pooling

Scaffold: `scaffold.py pooling --out Assets/Game/Pooling --namespace <Ns>` creates `PoolService` (one `UnityEngine.Pool.ObjectPool<T>` per prefab), `PooledObject` (knows its pool, `Release()`), `IPoolable` (`OnGet`/`OnRelease` hooks), and `ReleaseAfter` (auto-release timer for VFX and bullets).

## When
Pool anything spawned more than a few times a second, or in bursts: bullets, hit VFX, damage numbers, enemies, audio one-shots. Don't pool one-off objects (bosses, UI screens).

## Rules
- Use the built-in `UnityEngine.Pool.ObjectPool<T>(createFunc, actionOnGet, actionOnRelease, actionOnDestroy, collectionCheck, defaultCapacity, maxSize)`. `collectionCheck: true` in development catches double release; it costs a lookup, so it can be off in release builds.
- Prewarm during loading: Get and then Release `defaultCapacity` items, so the first fight doesn't spike.
- `maxSize` caps what the pool keeps; extra objects are destroyed on release.
- Reset state in `OnGet`/`OnRelease`: health, velocity (`rb.linearVelocity = Vector3.zero` in Unity 6), trails (`TrailRenderer.Clear()`), particle systems (`Clear()` + `Play()`), coroutines, event subscriptions.
- Release instead of Destroy. Never keep a reference to a released object; clear target fields.
- Parent pooled objects under one inactive-safe root to keep the hierarchy tidy, and don't reparent them every frame.
- `SetActive` costs something; for thousands of tiny items, consider disabling the renderer and collider, or using GPU instancing / particles instead of GameObjects.
- Collections: `ListPool<T>.Get()` / `HashSetPool<T>` / `DictionaryPool` for temporary lists in hot paths, with `using var _ = ListPool<T>.Get(out var list);`.

## Checklist
- [ ] Every `Instantiate` in a hot path goes through the pool (`cs_lint.py --only INSTANTIATE_HOT`).
- [ ] Prewarmed; `maxSize` set.
- [ ] OnGet resets everything that OnRelease or gameplay changed.
- [ ] No Destroy on pooled objects; no double release (collectionCheck in dev).
- [ ] Profiler: 0 B GC alloc per frame during combat.
