# VERIFY report template and screenshot judging

Save as `Logs/harness/verify/<run-id>/VERIFY.md`. Copy it to `docs/verify/` only if the team versions reports.

```markdown
# VERIFY <run-id>: <scope, e.g. M1-S02 Melee attack>

Result: PASS | FAIL (<n> FAIL, <n> PASS) · Date: <YYYY-MM-DD HH:MM> · Unity 6000.3.21f1 · Path: MCP | headless
Scene: Assets/Scenes/Game.unity · Commit: <git rev-parse --short HEAD> (+dirty?) · Seed: <seed or n/a>

## Criteria
<paste the markdown table printed by check_criteria.py, unchanged>

## Screenshots
| Checkpoint | File | Observation |
|---|---|---|
| M1-S02-AC2 hit | Logs/harness/verify/<run-id>/shots/M1-S02-AC2-hit.png | Enemy sprite is fully white for this frame; HUD shows 2/3 hearts |

## Console
Errors: 0 · Exceptions: 0 · Warnings: <n> (list new ones) · Source: console.json (<n> entries)

## How it was driven
Input script / execute_code calls, verbatim:
    hold right 1; tap Space; until enemy.count == 0 10; probe

## Failures and next actions
- <ID>: expected <...>, got <...> (evidence). Suspected cause: <...>. Next: <task for the owner skill>.
```

## Judging a screenshot
Look at the image returned with `include_image=true` before writing anything. Check, in order:
1. Right moment: the scene/room and state the criterion's Given/When describe (HUD values, player position, enemy count).
2. The "Then" is visible: the specific thing (flash colour, UI element, text, sprite) at a plausible size and position, not just "something changed".
3. Nothing broken: magenta/pink materials (shader missing for URP), missing sprites (white or empty squares), UI overlapping or off-screen, camera pointing at nothing, black frame (captured during a load or with no camera rendering).
4. Overlay UI present when the criterion is about UI (captures without the `camera` parameter include Screen Space-Overlay canvases; captures with a `camera` do not).
Write one concrete sentence per screenshot ("Hearts show 2 of 3; enemy at x≈4 is white"), then pass `--evidence <ID>=PASS:<path> — <sentence>` or `=FAIL:...` to check_criteria.py.

## Comparing with an earlier run
No pixel diff is shipped (PNG decoding in the Python stdlib is not worth it). For regressions, open the previous run's shot and the new one side by side (both with `include_image` via the read tool) and compare the same checklist. For exact comparisons make runs deterministic first (seed, `Time.captureFramerate`, same Game view size); if pixel-level diffs are required, that is a tooling task for a human to approve (e.g. ImageMagick `compare -metric AE`).
