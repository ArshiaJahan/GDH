# Backlog: <Game>

Source GDD: docs/GDD.md (v0.1, YYYY-MM-DD) · Feature specs: docs/specs/
Current milestone: M0
Rules: one playable increment per milestone; each story has >= 1 criterion; each criterion has a test type and an observable signal.
Validate: `python3 <skills>/gdd-to-backlog/scripts/backlog_lint.py BACKLOG.md` (must print RESULT: OK).

<!--
Format contract (backlog_lint.py enforces it):
  ## M<n> <title>            milestones in strictly increasing order, starting at M0
  Goal: / Exit: / Status:    Exit is required and testable; Status todo|active|done
  ### M<n>-S<nn> <title>     story IDs unique, prefix = milestone
  - Status: todo|doing|done|blocked|cut
  - Owner skill: one of the 13 harness skills, unity-mcp-orchestrator, game-designer or human
  - GDD: section / spec reference (optional)
  - Visual: yes             optional yes|no; overrides screenshot-evidence file-glob detection
  - Critique: no            optional yes|no; enables/disables the design-critique quality tier
  | AC | Given / When / Then | Test | Signal |   one row per criterion, no '|' inside cells
  Test: EditMode | PlayMode | play-verify | headless | manual
  Signal kinds: test:Fixture.Method  log:"text"  screenshot:<name> shows <what>
                metric:<name> <op> <number>[unit]  file:<path>  exit:<code>  observe:<what a human checks>
  Tests carry [Category("M<n>")] and the story ID in the method name (M1_S02_...).
-->

## M0 Skeleton / boot
Goal: The project boots from Boot to an empty Game scene with input, tests and a build pipeline working.
Exit: All M0 criteria pass; EditMode and PlayMode suites green in batchmode; macOS dev build launches.
Status: active

### M0-S01 Repo and project hygiene
- Status: todo
- Owner skill: vcs-hygiene
- GDD: §17 Technical Constraints

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M0-S01-AC1 | Given a fresh clone, When `git check-attr merge -- Assets/Scenes/Boot.unity` runs, Then it reports unityyamlmerge | headless | exit:0; log:"merge: unityyamlmerge" |
| M0-S01-AC2 | Given the project root, When project_snapshot.py --check runs, Then PROJECT.md has no drift | headless | exit:0; log:"RESULT: OK" |

### M0-S02 Boot flow Boot -> Title -> Game
- Status: todo
- Owner skill: architecture-patterns
- GDD: §13 UI and UX (menu flow)

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M0-S02-AC1 | Given Boot is build index 0, When Play starts from Boot, Then Title is the active scene within 5 s | PlayMode | test:BootFlowTests.M0_S02_BootLoadsTitleWithin5s |
| M0-S02-AC2 | Given the Title scene, When Start is pressed, Then the Game scene loads and logs the ready line | play-verify | log:"[Boot] game scene ready"; screenshot:M0-S02-game shows the empty arena |

### M0-S03 Test and build pipeline
- Status: todo
- Owner skill: headless-ops

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M0-S03-AC1 | Given the editor is closed, When the EditMode suite runs in batchmode, Then the results XML reports zero failures | headless | file:Logs/harness/editmode.xml; metric:failed == 0 |
| M0-S03-AC2 | Given a clean checkout, When a macOS development build is made, Then the build exits 0 and the app logs the boot line | headless | exit:0; log:"[Boot] ready" |

## M1 Core loop playable
Goal: In one room the player moves, attacks, kills an enemy, can die and restarts in under 3 s.
Exit: All M1 criteria pass; a 2-minute play-verify session shows 0 console errors.
Status: todo

### M1-S01 Player movement
- Status: todo
- Owner skill: architecture-patterns
- GDD: §4.1 Movement, §6 Controls

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S01-AC1 | Given MoveSpeed 6 in PlayerConfig, When Move right is held for 1 s, Then the player moves 6 +/- 0.3 units right | PlayMode | test:PlayerMovementTests.M1_S01_MovesSpeedTimesTime |
| M1-S01-AC2 | Given the player at a wall, When Move into the wall is held, Then the position does not pass the wall collider | PlayMode | test:PlayerMovementTests.M1_S01_WallBlocksMovement |

### M1-S02 Melee attack and enemy death
- Status: todo
- Owner skill: architecture-patterns
- GDD: §4.2 Attack, specs/FS-002-attack.md §9

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S02-AC1 | Given an enemy with 3 HP and attack damage 1, When the hitbox overlaps it 3 times, Then the enemy dies and Died fires once | EditMode | test:HealthTests.M1_S02_DiesAtZeroAndRaisesOnce |
| M1-S02-AC2 | Given the play scene, When the player attacks an adjacent enemy, Then a hit is logged and the enemy flashes | play-verify | log:"[Combat] hit target=Enemy"; screenshot:M1-S02-hit shows the white hit flash |

### M1-S03 Death and restart
- Status: todo
- Owner skill: architecture-patterns

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S03-AC1 | Given player HP 1, When an enemy deals 1 damage, Then the run ends and a new room is playable within 3 s | PlayMode | test:RunFlowTests.M1_S03_RestartWithin3s |

## M2 Run structure
Goal: A seeded run of N rooms with procgen layouts, room-clear progression, run end, and saved meta currency.
Exit: All M2 criteria pass; the same seed produces the same floor layout twice.
Status: todo

### M2-S01 Seeded floor generation
- Status: todo
- Owner skill: architecture-patterns
- GDD: §5 Systems (procgen), §10 Procedural generation rules

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M2-S01-AC1 | Given seed 1234, When the floor is generated twice, Then both room graphs are identical | EditMode | test:FloorGenTests.M2_S01_SameSeedSameLayout |
| M2-S01-AC2 | Given 500 random seeds, When floors are generated, Then every floor is connected and has exactly 1 exit | EditMode | test:FloorGenTests.M2_S01_AllFloorsConnected |

### M2-S02 Meta currency persists
- Status: todo
- Owner skill: architecture-patterns
- GDD: §7 Progression, §8 Economy

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M2-S02-AC1 | Given 0 saved coins, When a run ends with 25 coins and the game restarts, Then the save reports 25 coins | PlayMode | test:SaveTests.M2_S02_CoinsSurviveRestart |

## M3 Content and juice
Goal: MVP content counts from the GDD content plan with hit feedback, audio and placeholder-free art.
Exit: All M3 criteria pass; MVP counts reached; game-feel checklist complete.
Status: todo

### M3-S01 Hit feedback pass
- Status: todo
- Owner skill: game-feel-pass

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M3-S01-AC1 | Given a melee hit, When it lands, Then hit-stop lasts 60 +/- 10 ms and camera shake starts | play-verify | log:"[Feel] hitstop ms=60"; screenshot:M3-S01-shake shows the offset camera frame |

## M4 Polish and ship
Goal: Menus, settings, performance budget and release builds for the target platforms.
Exit: All M4 criteria pass; release build smoke-tested on every target; CHANGELOG updated.
Status: todo

### M4-S01 Performance budget
- Status: todo
- Owner skill: perf-pass

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M4-S01-AC1 | Given the busiest room with 30 enemies, When 60 s of play are profiled, Then frame time p95 stays under budget | play-verify | metric:frame_ms_p95 <= 16.6 ms; metric:gc_alloc_avg == 0 |

### M4-S02 Release builds
- Status: todo
- Owner skill: build-ship

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M4-S02-AC1 | Given version 1.0.0, When the macOS release build runs for 30 s, Then it logs boot and quits cleanly | headless | exit:0; log:"[Boot] ready version=1.0.0" |
| M4-S02-AC2 | Given the release build, When a fresh tester plays one run, Then they finish it without help | manual | observe:5 of 6 testers finish run 1 unaided |

## Later (not scheduled)
- Stretch content from GDD §9 (Target / Stretch counts).

## Open questions
- (copy from GDD §21; link the story each one blocks)
