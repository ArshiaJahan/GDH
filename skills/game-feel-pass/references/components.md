# Harness.Feel components: wiring and code

Contents: 1. Folder layout · 2. Calling feedback from gameplay · 3. ScreenShake and cameras · 4. HitStop and pause · 5. Flash shader requirement · 6. Knockback · 7. DamageNumbers (TextMesh / TextMeshPro) · 8. Tween · 9. FeedbackPlayer rows · 10. Tests

## 1. Folder layout (copy to Assets/Harness/Feel/)
```
Runtime/      Harness.Feel.asmdef (no references, autoReferenced) + all components
Shaders/      HarnessSpriteFlashUnlit.shader (URP 2D unlit sprite + flash)
Cinemachine/  Harness.Feel.Cinemachine.asmdef (refs Harness.Feel, Unity.Cinemachine; defineConstraints
              HARNESS_CINEMACHINE_3 set by versionDefines com.unity.cinemachine >= 3.0.0) + CinemachineShake.cs
Tests/EditMode  Harness.Feel.Tests.EditMode (HitStopController, Easing, InputBuffer, CoyoteTimer)
Tests/PlayMode  Harness.Feel.Tests.PlayMode (Tween, HitStop, FeedbackPlayer impact stack, accessibility)
```
Verified on 6000.3.21f1 (bench with URP 17.3, Cinemachine 3.1.7): all assemblies compile with 0 warnings, the shader imports without errors, 11/11 EditMode and 5/5 PlayMode tests pass (PlayMode with and without -nographics).

## 2. Calling feedback from gameplay
```csharp
using Harness.Feel;
public class EnemyHealth : MonoBehaviour
{
    [SerializeField] FeedbackPlayer hitFeedback, deathFeedback;
    public void TakeDamage(int amount, Vector2 hitPoint, Vector2 hitDirection)
    {
        hp -= amount;                                    // gameplay first
        hitFeedback.Play(hitPoint, hitDirection, amount); // then feedback (never the other way round)
        if (hp <= 0) deathFeedback.Play(hitPoint, hitDirection, amount);
    }
}
```
Direct calls without a FeedbackPlayer: `HitStop.Request(0.05f)`, `ScreenShake.Add(0.3f)`, `GetComponent<Flash>().Play()`, `squash.Play(-0.2f)`, `knockback.ApplyFrom(attacker.position)`, `DamageNumbers.Spawn(pos, 12, crit: true)`, `sfx.Play()`.

## 3. ScreenShake and cameras
- Plain camera: `CameraRig` (your follow/lookahead script writes its position) → `CameraShake` (ScreenShake, local pose 0) → `Main Camera`. ScreenShake writes only its own localPosition/localRotation around the pose captured in Awake (call `ResetRestPose()` if you move it in the editor at runtime).
- Pixel Perfect Camera: shake offsets below one pixel snap away or jitter; use `maxOffset` ≥ 1 pixel in world units (1/PPU) and `maxAngle = 0` (rotation breaks pixel grids).
- Cinemachine 3: the CinemachineBrain owns the Unity Camera transform, so ScreenShake must not sit under it. Setup:
  1. CinemachineCamera: `manage_camera(action="add_extension", target="CM Follow", extension="CinemachineImpulseListener")` (or Add Extension in the inspector).
  2. Rig object: `CinemachineImpulseSource` (Impulse Shape: Bump/Explosion, default velocity e.g. (0.3, 0.3, 0)) + `CinemachineShake` (`forceAtFullTrauma` 1–3).
  3. Gameplay keeps calling `ScreenShake.Add(trauma)`; CinemachineShake receives the already-scaled trauma through `ScreenShake.TraumaAdded` and calls `GenerateImpulseWithForce(trauma * forceAtFullTrauma)`.
  [UNVERIFIED] impulse visuals were not checked in a rendered scene; the adapter compiles against Cinemachine 3.1.7.
- Lookahead/deadzone with CM3 (`CinemachinePositionComposer`, verified field names in 3.1.7): `Lookahead.Enabled = true`, `Lookahead.Time` 0.2–0.5 s, `Lookahead.Smoothing` 5–10, `Lookahead.IgnoreY` for platformers; `Composition.DeadZone.Enabled = true`, `Composition.DeadZone.Size` (0.1, 0.1) of screen; `Damping` (0.5, 0.5, 0) for weight. Without Cinemachine: lerp the rig toward `target + velocity * lookaheadTime` with a deadzone rectangle.

## 4. HitStop and pause
- `HitStop.Request(duration, timeScale = 0)`: duration in real seconds × `FeelSettings.HitStopScale`, clamped to `maxDuration` (0.25); overlapping requests merge (latest end wins, lowest time scale wins, merged stop capped at `maxTotal` 0.4 s from the first request), and the time scale captured by the first request is restored exactly once.
- If Time.timeScale was changed by someone else during the stop, the end does not overwrite it. A pause that sets 0 while a freeze (0) runs cannot be told apart, therefore: pause with `HitStop.SetBaseTimeScale(0f)`, unpause with `HitStop.SetBaseTimeScale(1f)` (they write Time.timeScale directly when no stop is active).
- Disabling/destroying the `[HitStop]` object restores time (never leaves the game frozen). Domain-reload-off safe (statics reset in SubsystemRegistration).
- Animator-driven freeze instead of timeScale (only the two fighters freeze): set `animator.speed = 0` for the duration — not shipped; do it per character if global freeze feels wrong.

## 5. Flash shader requirement
- PropertyBlock path needs the renderer's material shader to declare `float _FlashAmount` (0..1) and `Color _FlashColor`, and to output `lerp(color.rgb, _FlashColor.rgb, _FlashAmount * _FlashColor.a)` with the sprite alpha unchanged.
- `Harness/SpriteFlashUnlit` (Shaders/) is URP 17.3's `Sprite-Unlit-Default` plus those two properties (SRP-Batcher-compatible CBUFFER). Create a material with it and assign it to SpriteRenderers that should flash white. [UNVERIFIED] on-screen result: verified only that it imports without errors and that Flash detects the property and sets/clears the block.
- Lit sprites (2D lights): Shader Graph → Sprite Lit; add Float `_FlashAmount` (reference name exactly `_FlashAmount`) and Color `_FlashColor`; Lerp(SampleTexture × VertexColor, FlashColor, FlashAmount) into Base Color, alpha from the texture.
- Tint fallback (no shader change): `tintColor` multiplies the sprite (red/orange hurt tint). It cannot make a sprite whiter.
- While a block is set the renderer is not SRP-batched; Flash calls `SetPropertyBlock(null)` when the flash ends.

## 6. Knockback
- Dynamic body: `resetVelocity` then `linearVelocity += dir * speed` (or `AddForce(dir * speed, ForceMode2D.Impulse)` with `useImpulse` to respect mass). Kinematic body: velocity decays linearly to zero over `stunDuration` in FixedUpdate.
- Movement scripts: `if (knockback.IsStunned) return;` before writing velocity, otherwise the next frame cancels the push.
- Linear damping (Unity 6 `linearDamping`, formerly `drag`) on the body shapes how far it slides.

## 7. DamageNumbers
- Zero setup: `DamageNumbers.Spawn(pos, value, crit)` creates `[DamageNumbers]` with a pooled TextMesh number (font `LegacyRuntime.ttf`, sorting order 100). Assign a prefab to style it.
- TextMeshPro: in your own assembly referencing `Unity.TextMeshPro`:
```csharp
public class TmpDamageNumber : Harness.Feel.DamageNumber
{
    [SerializeField] TMPro.TextMeshPro tmp;
    Color c;
    public override void SetText(string value, Color color) { tmp.SetText(value); tmp.color = c = color; }
    protected override void SetAlpha(float a) { var x = c; x.a *= a; tmp.color = x; }
}
```
- Pool sizes: `maxActive` 48 visible (extra spawns are skipped), `maxPooled` 64 inactive kept.

## 8. Tween
```csharp
Tween.Scale(this, icon, Vector3.one * 1.3f, 0.08f, Ease.OutQuad, unscaled: true,
    onComplete: () => Tween.Scale(this, icon, Vector3.one, 0.12f, Ease.OutBack, unscaled: true));
Coroutine c = Tween.Move(this, panel, new Vector3(0, -40, 0), 0.25f, Ease.OutCubic); StopCoroutine(c);
await Tween.RunAsync(0f, 1f, 0.3f, v => group.alpha = v, Ease.InOutQuad, unscaled: true, token: destroyCancellationToken);
```
Eases: Linear, In/Out/InOut Quad and Cubic, OutBack, OutElastic, OutBounce (all exactly 0 at t=0 and 1 at t=1). A tween stops when its host MonoBehaviour is disabled; each call allocates a coroutine + closure (events only, not per-frame swarms).

## 9. FeedbackPlayer rows (field meaning per kind)
| Kind | intensity | duration | timeScale | target (empty = search children) |
|---|---|---|---|---|
| ScreenShake | trauma 0..1 | – | – | – (ScreenShake.Main + adapters) |
| HitStop | – | seconds (0 → 0.05) | stop time scale | – |
| Flash | – | seconds (0 → component) | – | Flash |
| SquashStretch | + stretch / − squash | seconds (0 → component) | – | SquashStretch |
| Knockback | push speed (0 → component) | – | – | Knockback |
| Audio | volume scale (0 → 1) | – | – | AudioVariation |
| Particles | particles to Emit at the hit point (0 → Play()) | – | – | ParticleSystem |
| DamageNumber | – | – | – | DamageNumbers (empty → DamageNumbers.Main) |
| Event | – | – | – | – (UnityEvent `onPlay`) |
`delay` per row (real time by default) builds sequences: shake 0.02 s after the freeze starts, a second flash at 0.12 s. `cooldown` on the player throttles spam (e.g. 0.05 s for multi-hit weapons).
Editing rows through MCP: `manage_components(action="set_property", target="Enemy", component_type="FeedbackPlayer", property="feedbacks", value=[...])` [UNVERIFIED] for nested lists; editing in the prefab inspector (prefab stage) is the reliable path.

## 10. Tests
- EditMode (`HitStopControllerTests`): single stop restores once; nested requests merge to the latest end and restore the FIRST captured scale; lowest stop scale wins; non-1 base restored; external timeScale change not overwritten; SetBaseTimeScale during a stop; maxTotal caps a hit stream; zero duration ignored and Cancel returns base. `EasingAndTimingTests`: every Ease 0→1 with clamping; InputBuffer; CoyoteTimer.
- PlayMode: Tween.Move reaches the target and calls onComplete; unscaled tween completes at timeScale 0 while a scaled one waits; nested HitStop holds until the latest end then restores 1 (with `[FEEL]` lines asserted); full FeedbackPlayer impact stack logs 10 `[FEEL]` lines, restores time/colour/scale/property block, and `LogAssert.NoUnexpectedReceived()` (so every log line in that test is expected — add an AudioListener to test cameras); ShakeScale 0 disables shake.
