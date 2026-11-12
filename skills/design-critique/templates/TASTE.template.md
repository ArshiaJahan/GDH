<!-- Format adapted from SethGammon/Citadel (MIT); see THIRD_PARTY_NOTICES.md -->
# TASTE — Mosslight Delve

Filled example for a 2D pixel-art roguelike. Adapt these decisions to the project before adopting this file as root `TASTE.md`.

Design pillars: [GDD §2](GDD.md#2-design-pillars) — deliberate combat, legible danger, a welcoming refuge between runs. Pillars define design; this file defines aesthetic and feel judgment.

## Three words
- **Crunchy** — Short, decisive impacts make each successful hit feel tangible.
- **Readable** — Threats, player state and navigation remain clear at native resolution.
- **Cozy** — Warm refuges and restrained dungeon colors make exploration inviting.

## The Three Words test
Require every screenshot or feel change to clearly show at least two of the three words. Answer yes or no per word with screenshot or observed timing/feel evidence. Identify the failing checkpoint when fewer than two words apply.

## Ranked heuristics
1. Threat readability beats decoration.
2. Feedback begins within 100 ms of input.
3. Give each screen one focal point; combat makes the player and nearest threat primary.
4. Reserve bright accents for actionable information and impact.
5. Favor quiet recovery and warm refuge lighting over constant spectacle.

Higher-ranked rules win conflicts.

## Anti-patterns
- No screen shake on normal hits; reserve it for exceptional impacts and expose an intensity control.
- No pure-black outlines on dark tiles.
- No UI text under 8 px at 320×180.
- No particle spam hiding enemies or their wind-ups.
- No information conveyed solely by color, shake or flashing.

## References
- **Nuclear Throne** — study compact impact silhouettes; compare the project's hit checkpoint at `Docs/References/combat-hit.png`.
- **Moonlighter** — study warm refuge versus cool dungeon contrast; compare `Docs/References/refuge.png`.
- Capture or supply those reference screenshots with source/permission notes before review; these example paths do not ship images. Borrow visual principles, not assets.

## Hard constraints
- PPU: 16; pixel-perfect camera, point filtering, no fractional sprite scaling.
- Reference resolution: 320×180; verify UI at native size and integer scales.
- Palette file: `Assets/Art/Palettes/mosslight.gpl`; restrict scene colors to this project-owned palette.
- Font sizes: minimum 8 px body/UI, 12 px headings at reference resolution.
- Accessibility: reduced flashing, shake intensity including zero, and hit-stop toggle; preserve readable feedback when disabled.
