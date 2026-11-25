# Coding practices (Unity 6)

## Rules
- One responsibility per MonoBehaviour. Prefer composition (Health, Mover, Attack) over a deep `Enemy : Character : Entity` tree.
- `[SerializeField] private` fields, not `public` fields. Expose read-only state through properties.
- Cache components in `Awake` (`TryGetComponent` when it's optional). Never call `GetComponent`, `Find*`, `FindObjectsByType` or `Camera.main` in `Update`. `Camera.main` is cached by Unity, but each access still costs about as much as a GetComponent, so cache it yourself in hot code.
- `Awake`: your own references. `OnEnable`/`OnDisable`: subscribe and unsubscribe, always in pairs. `Start`: anything that needs other objects to be ready.
- Use `CompareTag("Enemy")`, not `tag == "Enemy"` (the comparison allocates a string).
- Null checks on `UnityEngine.Object`: use `if (obj)` / `obj == null`. Never use `?.` or `??` on them, because those skip Unity's destroyed-object check.
- Events: C# `event Action<T>` inside a system; ScriptableObject event channels between systems or scenes; `UnityEvent` only when designers wire things up in the Inspector.
- Async: `Awaitable` (Unity 6) or coroutines. Do not use `Task.Delay` in gameplay code. Pass `destroyCancellationToken` to awaited work, so it stops when the object is destroyed. Await each `Awaitable` only once: Unity reuses the instances.
- Physics goes in `FixedUpdate`, and input is read in `Update` and stored for it. Move rigidbodies with `Rigidbody.MovePosition` / velocity, not with `transform.position`.
- Time: `Time.deltaTime` in Update, `Time.fixedDeltaTime` in FixedUpdate. `Time.unscaledDeltaTime` for UI and pause menus.
- Assembly definitions per area (Runtime, Editor, Tests) keep recompiles small.
- Enter Play Mode Options with Domain Reload off: reset statics in a `[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]` method.
- Editor-only code goes in an `Editor` folder or asmdef, or inside `#if UNITY_EDITOR`.

## Checklist (new or reviewed script)
- [ ] No lookups or allocations in Update/FixedUpdate/LateUpdate (run `cs_lint.py`).
- [ ] Every `+=` subscription has a matching `-=` in OnDisable/OnDestroy.
- [ ] No public mutable fields; tunables come from a config ScriptableObject (tuning.md).
- [ ] No `?.` / `??` on Unity objects.
- [ ] Statics reset for Domain Reload off.
- [ ] The class name matches the file name, inside a namespace.
