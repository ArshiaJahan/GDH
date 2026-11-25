# Easily changeable parameters

Scaffold: `scaffold.py tuning --out Assets/Game/Config --namespace <Ns>` creates `ConfigAsset` (a base SO with `OnValidate` clamping and a `Changed` event), `GameTuning` (an example of grouped settings with `[Range]`/`[Tooltip]`), `LiveTuning` (re-applies values in Play Mode when an SO changes), and `ConfigLoader` (optional JSON override in `persistentDataPath`, for playtest builds).

## Rules
- Every number a designer might change lives in a ScriptableObject, not in code or scattered prefab fields: speeds, damage, cooldowns, spawn rates, curves, costs.
- One SO type per concept (`EnemyConfig`, `WeaponConfig`, `DifficultyConfig`), and many assets for its variants. Reference them through serialized fields, not `Resources.Load` by string.
- SO assets are shared data: never write runtime state into them (in the editor that change is saved to disk). Copy them into runtime state (`var hp = config.maxHealth;`) or use `Instantiate(config)` for a per-run copy.
- Inspector quality: `[Range(min,max)]`, `[Min(0)]`, `[Tooltip]`, `[Header]`, `AnimationCurve` for anything that scales with level or time. `OnValidate` clamps the values and keeps related fields consistent.
- Live tuning: SO edits in Play Mode persist after Play Mode, which is useful for tuning; listen to `Changed` (raised from OnValidate) so systems re-read the values without a restart.
- Difficulty and balancing: one `DifficultyConfig` of multipliers applied at read time, not duplicated configs. The balance-pass skill (if installed) simulates the numbers.
- Tables: many rows (items, loot) as a CSV/JSON TextAsset imported into SOs by an editor script, so a spreadsheet is the source of truth when designers prefer one.
- Build overrides: `ConfigLoader` reads `persistentDataPath/tuning.json` in development builds only, so playtesters can test numbers without a rebuild.
- Remote values for live games: Unity Remote Config or your backend, layered on top of the SO defaults.

## Checklist
- [ ] No literals in gameplay code except 0, 1 and -1 (`cs_lint.py --only MAGIC_NUMBER`).
- [ ] Each tunable has a Range/Min and a Tooltip with its unit.
- [ ] Runtime code never writes into an SO asset.
- [ ] Changing a value in Play Mode takes effect without a restart.
