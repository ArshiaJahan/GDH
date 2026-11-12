<!-- Format adapted from SethGammon/Citadel (MIT); see THIRD_PARTY_NOTICES.md -->
# POSTMORTEMS

Keep an index of prevention rules and the failure entries they came from. The filled example below illustrates the format; replace it with actual project evidence when initializing POSTMORTEMS.md.

## Rule index
| ID | Rule | Enforced by | Applies to |
|---|---|---|---|
| [PM-007](#pm-007-hit-flash-stayed-on-after-pooling-2026-11-12) | Pooled objects reset every feedback component in OnDisable. | skill:game-feel-pass | Assets/**/Feel/**, Assets/**/*Pool*.cs |

## Entries

### PM-007 Hit flash stayed on after pooling (2026-11-12)
- What broke: A reused enemy retained its hit-flash tint. · Caught by: human · Cost: 40 min, $3.10
- Root cause: Returning the enemy to its pool interrupted the flash before its tint reset; OnDisable did not restore the visual state.
- Rule: Pooled objects reset every feedback component in OnDisable.
- Enforced by: skill:game-feel-pass
- Applies to: Assets/**/Feel/**, Assets/**/*Pool*.cs
