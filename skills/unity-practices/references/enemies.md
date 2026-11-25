# Object and enemy systems

Scaffold: `scaffold.py enemies --out Assets/Game/Enemies --namespace <Ns>` creates `EnemyConfig` (an SO with stats), `Health` (IDamageable, events), `EnemyBrain` (a small state machine), `WaveConfig` + `WaveSpawner` (spawns through the pool kit), and `EnemyRegistry` (live set, no FindObjects).

## Design
- Data vs behaviour: stats live in `EnemyConfig` ScriptableObjects. Prefabs reference one config, and variants are prefab variants plus another config, not new classes.
- Components: `Health` (damage, death event), `EnemyBrain` (states), `Mover` (NavMeshAgent or rigidbody), `Attack`. Each one can be tested and reused.
- Interfaces for interaction: `IDamageable.TakeDamage(in DamageInfo)`. Projectiles don't know about enemy classes; they use `TryGetComponent<IDamageable>`.
- State machine: an enum plus a switch for 3-6 states, or state classes (`IState { Enter; Tick; Exit }`) when states have data or grow past ~6. Use a behaviour tree only when the design really needs one.
- Think rate: run expensive decisions (target search, path requests) on a timer (0.1-0.25 s), staggered per enemy, not every frame. Movement can still update every frame.
- Targeting: keep a registry (a static list or a runtime-set SO) and use distance-squared checks. Use `Physics.OverlapSphereNonAlloc` / `Physics2D.OverlapCircle` with a buffer or `ContactFilter2D`; never `FindObjectsByType` in gameplay.
- Spawning: waves are data (`WaveConfig`: entries of config, count, interval). Spawn through the pool. Despawn means release to the pool, not Destroy.
- Death: raise `Died` once (guard with a flag), disable colliders, play VFX from the pool, then release. Score, loot and quests listen to events; Health never calls them directly.
- Many enemies (thousands): consider ECS/Entities or a manager that updates plain C# objects in one loop instead of one MonoBehaviour Update each.

## Checklist
- [ ] No per-enemy-type subclasses where a config would do.
- [ ] Decisions throttled; no FindObjects in Update.
- [ ] Spawn and despawn go through the pool; a reused enemy resets its health, state and velocity in OnGet.
- [ ] Damage goes through IDamageable; death is raised once.
- [ ] Gizmos show aggro and attack ranges (debug-tools.md).
