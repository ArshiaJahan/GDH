# Fix patterns (Unity 6000.3, 2D)

Contents: 1. Pooling · 2. Zero-alloc hot paths · 3. Physics2D queries and settings · 4. Rendering and batching · 5. Tilemaps · 6. Particles · 7. Many enemies

## 1. Pooling (UnityEngine.Pool)
```csharp
using UnityEngine.Pool;
ObjectPool<Projectile> pool = new ObjectPool<Projectile>(
    createFunc: () => Instantiate(prefab, poolRoot),
    actionOnGet: p => p.gameObject.SetActive(true),
    actionOnRelease: p => p.gameObject.SetActive(false),
    actionOnDestroy: p => Destroy(p.gameObject),
    collectionCheck: Debug.isDebugBuild,   // double-release check costs time; dev builds only
    defaultCapacity: 64, maxSize: 512);    // maxSize = max INACTIVE kept; prewarm by Get+Release at load
Projectile p = pool.Get(); … pool.Release(p);
```
- architecture-patterns ships `ComponentPool<T>` (Harness.Arch) with prewarm and position/rotation Get; prefer it in projects using those templates.
- Reset state in `actionOnGet` (velocity, HP, trail `Clear()`), not in `OnEnable` of every component.
- Particle hits: one pooled system per effect type and `Emit(EmitParams, count)` at the hit point (game-feel-pass FeedbackPlayer does this for Particles rows).

## 2. Zero-alloc hot paths
| Allocates | Use instead |
|---|---|
| `list.Where(...).ToList()`, `OrderBy`, `Any` with a capturing lambda | `for` loop into a reused `List<T>` (`Clear()` first) |
| `"HP: " + hp`, `$"…"`, `string.Format` per frame | update text only when the value changes; cached digit strings (`DamageNumbers` caches 0..999); `TMP_Text.SetText("{0}", hp)` (TextMeshPro, no alloc) |
| `GetComponent<T>()` / `Camera.main` / `FindObjectsByType` per frame | cache in Awake; registries (architecture-patterns RuntimeSet) |
| `new WaitForSeconds(x)` each loop | cache the instance; or Awaitable `await Awaitable.WaitForSecondsAsync(x, destroyCancellationToken)` |
| `foreach` over `IEnumerable<T>` / interface-typed collections | `for` over `List<T>`/array (foreach over `List<T>` directly is fine) |
| Boxing: `object o = myStruct`, `Dictionary<MyEnum,…>` without comparer (older runtimes), `params object[]` | generic APIs; explicit `IEqualityComparer` |
| `Debug.Log` in Update | remove, or `[Conditional("DEVELOPMENT_BUILD")]` wrapper |
| `gameObject.tag == "Enemy"` | `CompareTag("Enemy")` |
| `GetComponents<T>()` returning arrays | `GetComponents(List<T>)` overload with a reused list |
| Coroutine started per hit | one long-lived loop, or Awaitable |
Find them: Profiler (Deep Profile or allocation call stacks) → Hierarchy sorted by GC Alloc; then grep the hot scripts for `=>`, `new `, `+ "`, `$"`, `.ToList`, `GetComponent<`, `Find`.

## 3. Physics2D queries and settings
```csharp
readonly List<Collider2D> hits = new List<Collider2D>(32);
ContactFilter2D filter;
void Awake() { filter = new ContactFilter2D { useTriggers = false }; filter.SetLayerMask(enemyMask); }
int n = Physics2D.OverlapCircle(center, radius, filter, hits);           // fills the list, no garbage
RaycastHit2D[] rayHits = new RaycastHit2D[8];
int r = Physics2D.Raycast(origin, dir, filter, rayHits, distance);       // array overload
```
⚠ version-sensitive: on 6000.3 `Physics2D.OverlapCircleNonAlloc`, `RaycastNonAlloc` etc. compile with warning CS0618 "has been deprecated. Please use OverlapCircle/Raycast" (verified 6000.3.21f1); they are not removed. `Rigidbody2D.velocity` → `linearVelocity` (CS0618, UnityUpgradable; the API Updater can rewrite it).
Settings (Project Settings > Physics 2D, or `manage_physics`):
- Layer Collision Matrix: disable every pair that never needs contact (enemy↔enemy, projectile↔projectile, pickup↔enemy).
- Simulation Mode FixedUpdate; Fixed Timestep 0.02 s default (Time settings). Fewer, larger steps = cheaper; 1/60 only if the game needs it.
- Bodies: Kinematic for scripted movers (enemies following paths), Dynamic only when physics response is needed; Sleeping Mode Start Awake; Collision Detection Discrete except fast projectiles (or raycast projectiles instead of bodies).
- Colliders: Circle/Capsule/Box over Polygon; TilemapCollider2D with Composite Operation = Merge (CompositeCollider2D) for terrain; Static bodies never moved by transform.
- Never move a body by `transform.position` every frame (forces transform sync); use `MovePosition`/`linearVelocity`.
- Queries per frame: throttle target acquisition (10 Hz round-robin), cache results.

## 4. Rendering and batching (URP 2D Renderer)
- Sprite Atlas (V2): pack sprites drawn together (a character's frames, a biome's props) so they share one texture; Unity batches consecutive sprites with the same texture/material. Interleaving sorting order between two atlases breaks batches; group sorting layers by atlas.
- One material per batchable group; avoid per-instance material copies (`renderer.material` creates a copy — use `sharedMaterial` or MaterialPropertyBlock only when needed).
- SRP Batcher: on by default in URP assets; it speeds up draws that share a shader variant. [UNVERIFIED] how the 2D Renderer's sprite batching interacts with the SRP Batcher on 6000.3; renderers with a MaterialPropertyBlock are not SRP-batched. Measure with the Frame Debugger, not by assumption.
- GPU Resident Drawer is for MeshRenderers (3D) [UNVERIFIED]; it does not help SpriteRenderers.
- 2D Lights: each light adds passes over the lit area; keep light count per screen low, prefer baked-looking sprites; turn off shadow casters on small sprites.
- Pixel-perfect camera: upscale render texture costs fill; check Upscale Render Texture only if needed.
- UI: separate Canvases for static vs changing UI (a change rebuilds the whole canvas); disable Raycast Target on non-interactive graphics.

## 5. Tilemaps
- `TilemapRenderer.mode`: `Chunk` (default, batches tiles per chunk — needs all tiles of a tilemap in one atlas), `Individual` (per-tile sorting, more draws), `SRPBatch` (6000.x, SRP-batched tile rendering) [UNVERIFIED] relative cost on 2D Renderer — compare Chunk vs SRPBatch with the probe.
- Detect Chunk Culling Bounds = Auto; split huge maps into rooms (roguelike rooms are natural chunks) and disable off-screen rooms.
- Animated tiles and frequent `SetTile` calls rebuild chunks: batch edits with `SetTiles` / `SetTilesBlock`, and avoid per-frame tile changes.
- Colliders: TilemapCollider2D + CompositeCollider2D (static body), regenerated only when the map changes.

## 6. Particles
- `main.maxParticles` per system (e.g. 50 for hit sparks), short lifetimes, `Culling Mode` Automatic, `Stop Action` Disable for pooled systems.
- One system per effect type, `Emit` at positions, instead of one GameObject per hit.
- Avoid Collision, Lights, Trails and Noise modules on mass effects; prefer sprite sheets (Texture Sheet Animation) to many particles.
- Sort with the sprite layers they belong to (Renderer > Sorting Layer) to avoid breaking batches mid-scene.

## 7. Many enemies (hundreds)
- One `EnemyManager.Update` iterating arrays of enemy data instead of hundreds of MonoBehaviour `Update()` calls; disable components on far/off-screen enemies.
- Spread expensive work across frames: `for (i = frame % k; i < n; i += k)`.
- Animator per enemy is costly at scale: simple sprite flipbook scripts or culling (`Animator.cullingMode = CullCompletely`) for off-screen.
- Pathfinding: flow fields for swarms (one field, many readers) instead of A* per enemy.
- Burst/Jobs (com.unity.burst/collections are in the bench) only after the simpler steps; they change architecture.
