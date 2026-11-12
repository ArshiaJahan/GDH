---
name: game-feel-pass
description: Adds and tunes game feel (juice) in Unity 6 (6000.3) 2D games with dependency-free Harness.Feel components (ScreenShake, HitStop, SquashStretch, Flash, Knockback, Tween, DamageNumbers, AudioVariation, FeedbackPlayer, optional Cinemachine 3 adapter) that log [FEEL] lines for play-verify, plus an input/camera/accessibility checklist. Use when a working mechanic "feels flat" or needs juice, hit stop, screen shake, hit flash, impact or combat polish.
---

# game-feel-pass

Make every important moment readable and satisfying, with reusable components, tuned numbers, accessibility switches and proof that each feedback fires.

Pinned: Unity 6000.3.21f1, URP 17.3 (2D Renderer), Input System 1.20.x, Test Framework 1.6.0, Cinemachine 3.1.x (optional, namespace `Unity.Cinemachine`), MCP for Unity 10.3.0.
Tools are MCP for Unity 10.3 tools; your client may prefix them (e.g. `mcp__UnityMCP__execute_code`). For tool parameters see unity-mcp-orchestrator. `<skills>` = the folder holding these skills.

## When to use / not to use
- Use after a mechanic works (its acceptance criteria pass) and before calling it done: combat hits, deaths, player damage, pickups, dash/jump/land, UI confirms. Also when playtest notes say "floaty", "no impact", "unresponsive".
- Not for making a mechanic work (architecture-patterns, compile-fix-loop), frame-rate problems (perf-pass), art import (asset-pipeline), or new mechanics design (game-designer).

## Inputs
- The moments to juice (from BACKLOG.md stories or the GDD's Mechanics/UI-Feedback sections) and the feel target ("snappy arcade", "weighty"). If none are given, use the default moment list in references/checklist.md.
- The project's camera setup (plain Camera, or Cinemachine 3 CinemachineCamera) and whether sprites use URP's default sprite material.

## Components (templates/Harness.Feel, namespace `Harness.Feel`, no package dependencies)
| Component | Use | Logs |
|---|---|---|
| `ScreenShake` | trauma 0..1, Perlin offset/roll on a camera-offset transform; `ScreenShake.Add(0.3f)` | `[FEEL] name=ScreenShake trauma=… main=1` |
| `HitStop` + `HitStopController` | `HitStop.Request(0.06f)`: timeScale freeze in real time; overlapping requests merge, restore once, cap `maxTotal` | `name=HitStop duration=… nested=0/1` |
| `SquashStretch` | on the visual child; `Play(-0.25f)` squash, `Play(+0.25f)` stretch, area-preserving | `name=SquashStretch x=… y=…` |
| `Flash` | hit flash: MaterialPropertyBlock (`_FlashAmount`, `_FlashColor`; shipped shader `Harness/SpriteFlashUnlit`) or SpriteRenderer tint fallback | `name=Flash mode=block/tint …` |
| `Knockback` | Rigidbody2D push via `linearVelocity` (⚠ `velocity` is obsolete on 6000.3, CS0618); `IsStunned` for movement code | `name=Knockback speed=… stun=…` |
| `Tween` / `Easing` | coroutine or Awaitable tweens for position/scale/colour/float, `unscaled` option | (none) |
| `FeedbackPlayer` | inspector list of feedback rows played with one call: `Play(hitPoint, dir, damage)` | `name=FeedbackPlayer player=… feedbacks=N` + one line per row |
| `DamageNumbers` | pooled floating numbers (ObjectPool, cached digit strings, TextMesh default) | `name=DamageNumber value=…` |
| `AudioVariation` | random clip + pitch/volume, round-robin voices, min interval | `name=Audio clip=… pitch=…` |
| `InputBuffer`, `CoyoteTimer` (InputTiming.cs) | structs for jump/attack buffering and coyote time | (none) |
| `FeelSettings` | accessibility: `ShakeScale`, `ReduceFlashing`, `HitStopScale` (+ Load/Save PlayerPrefs) | |
| `CinemachineShake` (Cinemachine/ folder) | optional: forwards `ScreenShake.Add` to a `CinemachineImpulseSource` | `name=CinemachineShake force=…` |
Particles and UnityEvent rows in FeedbackPlayer log `name=Particles` / `name=Event label=…`. `FeelLog.Enabled` defaults to `Debug.isDebugBuild` (no log spam in release).

## One-time setup
1. Copy `<skills>/game-feel-pass/templates/Harness.Feel/` to `Assets/Harness/Feel/` (Runtime, Shaders, Tests, Cinemachine). The Cinemachine assembly only compiles when com.unity.cinemachine ≥ 3.0 is installed (asmdef versionDefines); delete the folder if unwanted. Add `Harness.Feel` to the game asmdef references. Run compile-fix-loop.
2. Camera: plain camera → hierarchy `CameraRig` (follow script) → `CameraShake` (ScreenShake) → `Main Camera`. Cinemachine 3 → do NOT put ScreenShake under the Brain's camera; add `CinemachineImpulseSource` + `CinemachineShake` to a rig object and the `CinemachineImpulseListener` extension to the CinemachineCamera (`manage_camera(action="add_extension", ...)`).
3. White hit flash needs a shader with `_FlashAmount`/`_FlashColor`: assign a material using `Harness/SpriteFlashUnlit` (unlit sprites) or make a Sprite Lit Shader Graph exposing those two properties (lit sprites). Without it Flash uses the tint fallback (colours only; tint cannot whiten).
4. Options menu: call `FeelSettings.Load()` at boot; expose Screen shake (0–100 %), Reduce flashing, Hit-stop on/off; call `FeelSettings.Save()` on change.
5. Pause menus: use `HitStop.SetBaseTimeScale(0)` / `(1)` (or `HitStop.Cancel()` first) instead of writing `Time.timeScale` directly, so a hit-stop ending never unpauses the game.
Details, prefab wiring and code snippets: references/components.md.

## Procedure
1. **Precheck.** `set_active_instance`; `mcpforunity://editor/state` ready; the mechanic's criteria already pass (play-verify). Note the current feel in one line per moment.
2. **Plan the stack per moment.** For each moment pick the rows and start values from references/checklist.md (e.g. light hit: HitStop 0.04–0.06 s, Flash 0.06–0.1 s, Squash −0.15, Knockback 4–6, Shake 0.15–0.25, pitch ±8 %, DamageNumber). Bigger events get more rows, not just bigger numbers. Write the plan into the story's notes.
3. **Wire.** Add components to the PREFAB (scene-prefab-safety rules; `manage_prefabs(action="modify_contents", components_to_add=[...])` or prefab stage), put tuning values in the FeedbackPlayer rows, and call `GetComponent<FeedbackPlayer>().Play(hitPoint, hitDir, damage)` from the gameplay event (damage handler, death, pickup) — feedback code never decides gameplay outcomes.
4. **Input and camera.** Apply the input checklist (buffering, coyote time, cancel windows) and camera checklist (lookahead, deadzone, no shake on UI) where the moment needs them.
5. **Tune in Play Mode.** `manage_editor(action="play")`; trigger moments with `execute_code` (e.g. `GameObject.Find("Enemy").GetComponent<Harness.Feel.FeedbackPlayer>().Play(); return 1;`) or play-verify's ScriptedInput; capture before/after screenshots with `manage_camera(action="screenshot", include_image=true, max_resolution=512)` at the impact frame (HitStop makes it easy to catch). Adjust row values in the prefab; stop Play Mode before saving (play-mode changes are lost).
6. **Accessibility pass.** Verify ShakeScale 0 → no shake lines change the camera, ReduceFlashing → `amount=0.35` and single flash, HitStopScale 0 → no stop; no full-screen flash brighter than needed; flashes under 3 per second.
7. **Prove it** (Verify section), then record the tuned values per moment in the story notes / project-memory.

## Checklist (summary; values and recipes in references/checklist.md)
- [ ] Input: jump/attack buffer 0.10–0.15 s (`InputBuffer`), coyote time 0.08–0.12 s (`CoyoteTimer`), attacks cancelable into dash/dodge after the active frames, input read in Update (not FixedUpdate), no input lag from animation waits.
- [ ] Impact stack on every hit: hit-stop + flash + squash + knockback + sound with pitch variation + particles + number; kill = bigger stack + shake; player hurt = distinct colour + stronger shake + brief invulnerability blink.
- [ ] Anticipation (wind-up frames/scale before big attacks) and follow-through (recoil, settle with OutBack/OutElastic, dust on land).
- [ ] Camera: lookahead in move direction, deadzone so small moves do not scroll (CM3 `CinemachinePositionComposer`: `Lookahead.Enabled/Time/Smoothing`, `Composition.DeadZone.Size`, `Damping`), shake only on meaningful events, never shake UI.
- [ ] UI feedback: button press scale/sound, HP bar delayed "ghost" chunk, pickup counters punch-scale, damage numbers readable over art, unscaled time for UI during hit-stop.
- [ ] Audio: every action has a sound; pitch/volume variation; ducking or voice limits so 20 hits do not clip.
- [ ] Accessibility: shake intensity slider, reduce flashing, hit-stop toggle, no information conveyed by flash/shake alone.
- [ ] Performance: no Instantiate per hit (pools), tweens per event not per frame on hundreds of objects; run perf-pass if the stack is added to swarms.

## Rules
- Feedback reacts to gameplay; it never changes outcomes (exceptions that are gameplay: HitStop and Knockback — keep them consistent and data-driven).
- Anything that must move during a hit-stop uses unscaled time (ScreenShake, Flash, FeedbackPlayer delays default to unscaled; SquashStretch and DamageNumbers default to scaled so they freeze with the hit — change per feel).
- Scale, not position, on visual children; never scale the physics root.
- Respect `FeelSettings` in any new feedback you write; log a `[FEEL] name=<Feedback>` line through `FeelLog` so play-verify can see it.
- ⚠ version-sensitive: Rigidbody2D `linearVelocity`/`linearDamping` (Unity 6 names); Cinemachine 3 namespace `Unity.Cinemachine`, `CinemachineCamera`, `GenerateImpulseWithForce`.
- Keep magnitudes small first and raise them in play; overdone shake/hit-stop hurts readability and motion-sensitive players.

## Failure handling
- No `[FEEL]` line when expected: the FeedbackPlayer row is disabled, its target was not found (a `[FEEL] FeedbackPlayer '…': no Flash for row` warning names it), or `FeelLog.Enabled` is false (release build).
- Shake does nothing: camera transform written by another script or Cinemachine Brain → use the rig hierarchy or CinemachineShake; `main=0` in the log means no enabled ScreenShake.
- Game stays frozen: something wrote `Time.timeScale` during a stop (see pause rule); `HitStop.Cancel()` restores; `maxTotal` caps merged stops at 0.4 s.
- Flash shows no white: material lacks `_FlashAmount` (log says `mode=tint`) → assign the flash shader/material.
- Pink sprites after assigning the shader: shader not compatible with the active pipeline → check URP asset is assigned; report to the user.

## References
- references/components.md: read when wiring components (hierarchies, code calls, Flash shader/Shader Graph, Cinemachine adapter, DamageNumbers with TextMeshPro, pause integration).
- references/checklist.md: read when planning stacks (default moments, start values, input/camera/UI/accessibility details) and for the [FEEL] criteria template.

## Verify
1. Compile: compile-fix-loop's Verify passes (0 `error CS`; no new warnings from Harness.Feel).
2. Tests: `run_tests(mode="EditMode", assembly_names=["Harness.Feel.Tests.EditMode"])` and `run_tests(mode="PlayMode", assembly_names=["Harness.Feel.Tests.PlayMode"], init_timeout=120000)`, then `get_test_job(job_id, wait_timeout=60, include_failed_tests=true)` → `failed == 0` (11 EditMode + 5 PlayMode tests: HitStop nesting/restore, Tween completion scaled/unscaled, impact stack, accessibility). Headless: `-runTests -testPlatform EditMode|PlayMode -assemblyNames Harness.Feel.Tests.EditMode|Harness.Feel.Tests.PlayMode -testResults <xml>` (no `-quit`, timeout) → XML `failed="0"`.
3. play-verify run on the real scene (exact steps):
   a. Add rows to BACKLOG.md for the story, e.g. `| M2-S04-AC3 | Hitting an enemy plays the impact stack | play-verify | log:"[FEEL] name=HitStop"; log:"[FEEL] name=Flash"; log:"[FEEL] name=ScreenShake"; log:"[FEEL] name=DamageNumber" |`.
   b. `read_console(action="clear")`, `manage_editor(action="play")`, wait until `is_playing`.
   c. Trigger the moment through gameplay (ScriptedInput: walk to the enemy and attack) or `execute_code("GameObject.Find(\"Enemy\").GetComponent<Harness.Feel.FeedbackPlayer>().Play(); return 1;")`; wait ~1 s real time.
   d. `read_console(action="get", types=["log"], filter_text="[FEEL]", format="plain", page_size="100")` shows one line per expected feedback; `read_console(action="get", types=["error"], format="json", page_size="200")` returns 0 entries; save all console pages to `Logs/harness/verify/<run-id>/console.json`; `manage_editor(action="stop")`.
   e. `python3 <skills>/play-verify/scripts/check_criteria.py BACKLOG.md Logs/harness/verify/<run-id>/console.json --only M2-S04` → exit 0, `RESULT: OK`, CONSOLE row PASS.
4. After `manage_editor(action="stop")`, `Time.timeScale` is 1 (`execute_code("return Time.timeScale;")` in edit mode) and no Harness.Feel object was saved into the scene (`git status` shows only intended prefab/scene changes).
