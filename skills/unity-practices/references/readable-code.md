# Human-readable code

Based on Unity's C# style guide e-book (Unity 6 edition) and common C# conventions.

## Naming
- PascalCase: types, methods, properties, events, public constants, namespaces. camelCase: locals and parameters. Private fields: `_camelCase` or `camelCase`; pick one per project and write it in PROJECT.md.
- Names say intent: `secondsUntilRespawn`, not `t2`; `IsGrounded`, `CanAttack` for bools; verbs for methods (`ApplyDamage`); events in past tense or "On" (`Died`, `OnHealthChanged`).
- Units in names when they're not obvious: `rangeMeters`, `cooldownSeconds`, `speedPerSecond`.
- No abbreviations except well-known ones (`id`, `ui`, `hp` is fine in game code if the project uses it).

## Structure
- File order: constants, serialized fields, private fields, properties, events, Unity messages (Awake → OnEnable → Start → Update → OnDisable → OnDestroy), public methods, private methods.
- Methods short (≤ ~30 lines), one level of abstraction; early returns instead of nested ifs.
- No magic numbers: named constants or config fields (tuning.md).
- `[Header]`, `[Tooltip]`, `[Range]`, `[Min]` on serialized fields: the Inspector is documentation for designers.
- Comments explain why, not what. XML `///` summaries on public APIs used by other systems.
- Keep `#region` rare; if a class needs regions, it is probably too big.
- Format with `.editorconfig` + `dotnet format` / Rider so diffs stay about behaviour.

## Review steps (do in order, stop at the first failing step for a big file)
1. `cs_lint.py <files> --only NAMING,PUBLIC_FIELD,LONG_METHOD,MAGIC_NUMBER`
2. Rename for intent (IDE rename, so references follow; Unity serialized fields keep data with `[FormerlySerializedAs("old")]`).
3. Extract methods for each "and" in a method's description.
4. Move tunables to a config SO.
5. Recompile, rerun the lint, run the tests.

`[FormerlySerializedAs]` is required whenever you rename a serialized field, or the scene/prefab values are lost.
