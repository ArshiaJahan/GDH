# Roguelike milestone catalog and criteria cookbook

Read when you draft milestones for a 2D roguelike, or when you are unsure how to make a criterion testable.

Contents: 1. Default milestones and seed stories · 2. GDD/feature-spec field mapping · 3. Signal cookbook · 4. Rewriting vague criteria · 5. Adapting the ladder

## 1. Default milestones and seed stories

Every milestone ends playable. Cut seed stories the GDD does not need and add GDD-specific ones. Owner skill is in brackets.

### M0 Skeleton / boot (target: 1 session)
- Repo hygiene: .gitignore, LFS, UnityYAMLMerge driver, PROJECT.md created [vcs-hygiene, project-memory]
- Folder layout, asmdefs (Runtime/Editor/Tests.EditMode/Tests.PlayMode), root namespace [architecture-patterns]
- Boot -> Title -> Game scene flow, scene loader, build scene list [architecture-patterns, scene-prefab-safety]
- Input actions asset with Move/Attack/Dash/Pause, wired to a stub player [architecture-patterns]
- Placeholder sprites for player, enemy, wall and floor tiles; pixel-art import preset [asset-pipeline]
- Batchmode EditMode + PlayMode run and a macOS dev build script [headless-ops, build-ship]
- Criteria style: scene-active checks (PlayMode), `[Boot] ready` log line, results XML `failed == 0`, build `exit:0`.

### M1 Core loop playable (one room)
- Player movement with config ScriptableObject (speed, accel) [architecture-patterns]
- Primary attack, hitbox, damage, Health component with Died event [architecture-patterns]
- One enemy archetype: chase + contact damage [architecture-patterns]
- Death -> restart loop under N seconds [architecture-patterns]
- Minimal HUD: HP readout [architecture-patterns]
- Criteria style: EditMode for formulas (damage, health), PlayMode for movement/collision/restart timing, play-verify for "the loop is playable" with `[Combat]`/`[Run]` log lines and a screenshot.

### M2 Run structure (procgen + meta-progression)
- Seeded RNG service (one seed per run, logged) [architecture-patterns]
- Floor/room generator with validators (connected, one exit, spawn not in wall) [architecture-patterns]
- Room clear -> doors open -> next room; floor exit -> next floor [architecture-patterns]
- Run end screen with summary [architecture-patterns]
- Meta currency + save/load (JSON in persistentDataPath, versioned) [architecture-patterns]
- Unlock 1 meta upgrade that changes the next run [architecture-patterns]
- Criteria style: EditMode property tests over many seeds (`500 seeds -> all connected`), determinism (`same seed -> same layout`), PlayMode save round-trip, play-verify `[Run] floor=2 seed=1234`.

### M3 Content and juice
- MVP counts from GDD §9 (enemies, items, rooms, one boss) as data assets [architecture-patterns, asset-pipeline]
- Hit-stop, screen shake, flashes, particles, SFX per verb [game-feel-pass]
- Art and audio import settings, sprite atlas [asset-pipeline]
- Difficulty curve per floor from GDD §7 [game-designer for numbers, architecture-patterns for data]
- Criteria style: content counts via EditMode asset scans (`all EnemyDef assets have sprite and stats`), feel values as logged numbers (`[Feel] hitstop ms=60`), screenshots that show the effect.

### M4 Polish and ship
- Main menu, pause, settings (volume, fullscreen, remap if GDD §14 says Must) [architecture-patterns]
- Accessibility Must items from GDD §14 [architecture-patterns, game-feel-pass for shake/flash toggles]
- Performance budget from GDD §17 [perf-pass]
- Release builds per target, version, changelog, smoke run [build-ship]
- External playtest from game-designer `templates/playtest-plan.md` [human, game-designer]
- Criteria style: metric thresholds (`frame_ms_p95 <= 16.6 ms`), headless smoke run (`exit:0`, boot log line), manual criteria with observe: signals and a tester count.

## 2. GDD / feature-spec field mapping

| Source | Becomes |
|---|---|
| GDD §1 Overview (genre, platform) | M4 build targets; M0 build script target |
| GDD §2 Pillars | Tag each story with the pillar in `- GDD:`; stories that serve no pillar go to Later |
| GDD §3 Core Loop verbs table | M1 stories, one per verb; the Feedback column seeds M3 game-feel criteria |
| GDD §3 Fail state / retry time | M1 death-restart criterion with the stated retry time |
| GDD §4.x Mechanics: Rules, Key variables, Edge cases | One story per mechanic; one criterion per rule; one criterion per edge case that has a decided answer; variables go into config assets, not criteria text |
| GDD §5 Systems | M2 stories (procgen, save, economy, AI); feedback loops become EditMode simulation tests |
| GDD §6 Controls | M0 input story (action map), M1 per-verb criteria; responsiveness target becomes a metric |
| GDD §7 Progression / Difficulty | M2 meta-progression; M3 difficulty curve data |
| GDD §8 Economy (faucets/sinks) | M2 currency story; EditMode sim test: net per run within target range |
| GDD §9 Content Plan | M3: MVP column only; Target and Stretch go to Later |
| GDD §10 Procedural generation rules | M2 generator validators, each a property test over many seeds |
| GDD §12 Art and Audio | M0 placeholders, M3 import settings and juice |
| GDD §13 UI and UX | M1 minimal HUD, M4 menus and settings |
| GDD §14 Accessibility | Must rows -> M4 (earlier if they shape input/HUD); Should rows -> Later |
| GDD §17 Technical Constraints | M0 project setup; perf budget -> M4 metric criteria |
| GDD §18 Analytics events | Log lines used as play-verify signals (`[Run] run_ended cause=...`) |
| GDD §19 Milestones | Align titles and order; keep the vertical-slice ladder if the GDD table is vague |
| GDD §20 Risks | Prototype the riskiest mechanic in M1 even if the GDD places it later |
| GDD §21 Open Questions | `## Open questions` section; mark affected stories `blocked` |
| Feature spec §3 Rules (numbered) | One criterion per rule; keep the rule number in the criterion text |
| Feature spec §4 Tuning table | Default values quoted in Given; ranges stay in the spec |
| Feature spec §5 Edge cases | One criterion per decided edge case (EditMode or PlayMode) |
| Feature spec §6 UI and Feedback | play-verify criteria (log + screenshot) |
| Feature spec §8 Telemetry | log: signal text |
| Feature spec §9 Acceptance Criteria | Copy as rows; add a test type and signal to each; split compound criteria |
| Feature spec §10 Test Plan | Chooses the test type; playtest questions become manual criteria |

## 3. Signal cookbook

| Test type | Who runs it | Signal that proves it |
|---|---|---|
| EditMode | headless-ops (batchmode) or `run_tests(mode="EditMode")` | `test:Fixture.Method` passes; results XML `failed="0"` |
| PlayMode | headless-ops or `run_tests(mode="PlayMode", init_timeout=120000)` | `test:Fixture.Method` passes |
| play-verify | play-verify skill in a running editor (MCP); its `check_criteria.py` reads this table format | `log:"[Tag] text"` seen in the console; `screenshot:<name> shows <what>` (judged by the agent, so pair it with a log); `metric:<name> <op> <n>`, value taken from a `[VERIFY] <name>=<value>` log line the game or a probe emits |
| headless | headless-ops / build-ship scripts | `exit:<code>`; `file:<path>` exists; `log:"..."` in the Editor or Player log; `metric:` parsed from XML or a log |
| manual | human playtest (game-designer playtest plan) | `observe:<what and how many>`, e.g. `observe:5 of 6 testers finish run 1 unaided` |

Choosing a test type:
1. Pure logic (damage formula, RNG, generator validity, save serialization) -> EditMode.
2. Needs physics, frames, scenes, or MonoBehaviour lifecycles -> PlayMode.
3. Needs a human-meaningful look at the running game (feedback, layout, HUD) -> play-verify, backed by a log line so it is not screenshot-only.
4. Build, CLI, file outputs, player smoke runs -> headless.
5. Fun, clarity, comprehension -> manual, with a tester count.

Test naming: fixture per feature, method `M<n>_S<nn>_<Behaviour>`, `[Category("M<n>")]` on the fixture, so a milestone runs with `category_names=["M1"]` (MCP) or `-testCategory "M1"` (batchmode).

Log lines: emit from game code with a stable bracketed tag and key=value pairs: `[Run] floor=2 seed=1234`, `[Combat] hit target=Enemy dmg=1`, `[Save] wrote coins=25`. Strip them from release builds behind a define if the GDD needs it.

## 4. Rewriting vague criteria

| Vague | Testable |
|---|---|
| Movement feels responsive | Given Move pressed, When 1 frame passes, Then velocity is non-zero (PlayMode) + metric:input_to_motion_ms <= 100 |
| Combat is satisfying | Then hit-stop 60 +/- 10 ms and shake starts (play-verify log + screenshot); satisfaction itself -> manual with tester count |
| Levels are varied | Given 100 seeds, Then at least 80 distinct room-graph hashes (EditMode) |
| The game runs well | metric:frame_ms_p95 <= 16.6 ms in the busiest room for 60 s |
| Saving works | Given coins 25, When saved and reloaded, Then coins == 25 and file version == 1 (PlayMode) |
| Enemies are fair | Given an enemy attack, Then a telegraph of >= 300 ms precedes damage (PlayMode timing test) |

## 5. Adapting the ladder

- Small jam game: merge M3 and M4; keep M0-M2.
- No procgen (handmade levels): M2 becomes "Level sequence + meta-progression"; generator stories become level-load and completion stories.
- No meta-progression (pure roguelike): M2 keeps procgen and run end; drop save stories except settings.
- GDD §19 has its own milestones: keep its names in titles (`## M1 First playable (core loop)`), but keep the M<n> IDs and the one-playable-increment rule.
- Riskiest mechanic (GDD §20) always moves into M1.
