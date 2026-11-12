# Game-feel checklist, start values and [FEEL] criteria

Contents: 1. Default moments and impact stacks · 2. Input responsiveness · 3. Anticipation and follow-through · 4. Camera · 5. UI feedback · 6. Audio · 7. Accessibility · 8. [FEEL] acceptance criteria template

Values are starting points for a fast 2D action roguelike at 60 fps; tune in play, then record the final numbers.

## 1. Default moments and impact stacks (FeedbackPlayer rows)
| Moment | HitStop | Flash | Squash | Knockback | Shake | Audio | Other |
|---|---|---|---|---|---|---|---|
| Player light hit on enemy | 0.04–0.06 s | white 0.06–0.08 s | −0.15 | 4–6 | 0.10–0.20 | hit, pitch ±8 % | sparks Emit 6–10, number |
| Heavy hit / crit | 0.08–0.12 s | white 0.1 s | −0.3 | 8–12 | 0.35–0.5 | heavy hit + low thump | big sparks, crit number (scale 1.4) |
| Enemy death | 0.08 s | white 0.1 s, then fade | stretch +0.3 then shrink | – | 0.3–0.5 | death, pitch ±5 % | burst particles, loot pop (Tween OutBack) |
| Player hurt | 0.06–0.1 s | red tint or white 0.1 s, 3 blinks during i-frames | −0.2 | 6–8 away | 0.4–0.6 | hurt (distinct) | HP bar ghost chunk, vignette pulse |
| Pickup | – | – | +0.2 on pickup icon | – | – | pickup, rising pitch on streak | counter punch-scale, magnet pull |
| Dash | – | – | stretch along move +0.3 | – | 0–0.1 | whoosh | afterimages (pooled), dust |
| Jump / land | – | – | +0.25 / −0.3 | – | – (land from height: 0.1) | jump / land | dust Emit on land |
| Projectile fire | – | muzzle flash sprite | gun recoil Tween | player pushback 0.5 | 0.05 for heavy guns | fire, pitch ±10 % | shell/particle |
| UI confirm | – | – | button 1.1 → 1 OutBack | – | – | click | – |
Rules of thumb: bigger events add rows (and slightly longer stops), not only bigger numbers; keep total hit-stop per second under ~0.3 s; shake only on events the player should notice.

## 2. Input responsiveness
- [ ] Read input every frame (Update), act in the same frame where possible; physics in FixedUpdate consumes the buffered intent.
- [ ] Jump buffer 0.10–0.15 s (`InputBuffer.Press(Time.time)` on press, `Consume(Time.time)` when grounded).
- [ ] Coyote time 0.08–0.12 s (`CoyoteTimer.SetGrounded(isGrounded, Time.time)` each physics step; `Consume()` on jump).
- [ ] Variable jump height (cut upward velocity on release), faster fall than rise (gravity × 1.5–2 on descent).
- [ ] Attack cancel windows: after active frames, allow dash/dodge cancel; buffer the next attack during recovery (combo buffer 0.2 s).
- [ ] Turnaround and acceleration: near-instant direction change for action games (accel ≥ 60 u/s²) unless weight is a pillar.
- [ ] Input System 1.20: actions with `started/performed` for presses; avoid polling `wasPressedThisFrame` in FixedUpdate (missed presses).

## 3. Anticipation and follow-through
- [ ] Wind-up for big enemy attacks (0.2–0.5 s telegraph: squash, flash or colour pulse, sound) — readability > surprise.
- [ ] Player attacks: short anticipation (≤ 2 frames) for responsiveness, longer recovery; weapon trail / smear sprite.
- [ ] Settle motions with OutBack/OutElastic (scale back after squash), dust on land/turn, recoil after shots.
- [ ] Hit reactions face away from the hit direction (flip, small rotation Tween).

## 4. Camera
- [ ] Lookahead in move/aim direction (CM3 PositionComposer `Lookahead.Time` 0.2–0.5 s) so the player sees threats.
- [ ] Deadzone (CM3 `Composition.DeadZone.Size` ≈ 0.1) to avoid constant micro-scrolling; damping 0.3–0.6.
- [ ] Room-based roguelikes: confine per room (CinemachineConfiner2D) and blend on room change (0.3–0.5 s).
- [ ] Shake: trauma-based, decays in < 0.5 s for hits; never on UI cameras/canvases; rotation off with pixel-perfect cameras.
- [ ] Optional zoom punch on kills (orthographic size −3 % for 0.1 s, unscaled).

## 5. UI feedback
- [ ] Buttons: hover/press scale and sound; disabled state visibly different.
- [ ] HP bar: immediate drop + delayed "ghost" bar that catches up (Tween 0.3 s after 0.2 s delay); low-HP pulse.
- [ ] Counters (coins, combo): punch-scale on change, rising pitch for streaks.
- [ ] Damage numbers readable on all backgrounds (outline/shadow), crits bigger/coloured, cap visible count (DamageNumbers.maxActive).
- [ ] UI animations use unscaled time so they work during hit-stop and pause.

## 6. Audio
- [ ] Every player action and every hit has a sound; variations (2–4 clips) + pitch ±5–10 % (`AudioVariation`).
- [ ] Voice limits (`voices`, `minInterval`) so mass hits do not clip; mixer ducking for big events.
- [ ] Hit-stop does not slow audio (by design); stingers on kills/level-ups.

## 7. Accessibility
- [ ] Screen shake slider 0–100 % → `FeelSettings.ShakeScale` (0 must fully disable; covered by a test).
- [ ] Reduce flashing → `FeelSettings.ReduceFlashing` (Flash uses 35 % strength and one blink); avoid full-screen flashes; keep any flashing under 3 per second.
- [ ] Hit-stop toggle → `FeelSettings.HitStopScale` 0/1.
- [ ] Never convey critical information only by shake/flash/colour: add shape, icon or sound.
- [ ] Persist with `FeelSettings.Save()`; load at boot with `FeelSettings.Load()`.

## 8. [FEEL] acceptance criteria template (play-verify)
BACKLOG.md rows (gdd-to-backlog format; evaluated by `play-verify/scripts/check_criteria.py`):
```
| M2-S04-AC3 | Given an enemy, when the player hits it, then the impact stack plays | play-verify | log:"[FEEL] name=HitStop"; log:"[FEEL] name=Flash"; log:"[FEEL] name=SquashStretch"; log:"[FEEL] name=Knockback"; log:"[FEEL] name=DamageNumber" |
| M2-S04-AC4 | Killing an enemy shakes the camera | play-verify | log:"/\[FEEL\] name=ScreenShake trauma=0\.[3-9]/" |
| M2-S04-AC5 | Shake off in options means no camera shake | PlayMode | test:Accessibility_ShakeScaleZero_DisablesShake |
| M2-S04-AC6 | Hit-stop never leaves the game frozen | PlayMode | test:HitStop_Nested_FreezesUntilLatestEnd_ThenRestores |
```
Markdown-list form also works: `- F-1: impact stack plays `log:"[FEEL] name=HitStop"` `log:"[FEEL] name=Flash"``.
check_criteria adds the CONSOLE gate (0 errors/exceptions) automatically.
