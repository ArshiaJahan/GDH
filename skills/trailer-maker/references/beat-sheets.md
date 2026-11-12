# Beat sheets

Read when writing `Trailer/<slug>/beats.json`. Start from `templates/beats.template.json` (a 60 s gameplay cut).
Seconds below are targets for a 60 s cut; scale them to the brief's length.

| Type (Steam category) | Length | Beats |
|---|---|---|
| `gameplay` (Gameplay, Steam slot 1) | 45–75 s | 0–5 **thumbstopper** (late-game, busy, hook visible) · 5–7 title flash (optional) · 7–20 **genre + hook** (verbs; hook ≤ 10 s) · 20–45 **escalation** (layers, complications, rule of threes) · 45–55 **climax / content montage** (bosses, biomes, builds; fastest cutting, on downbeats) · 55–60 **end slate** (logo, platforms, Wishlist) |
| `announce` (Teaser) | 30–60 s | 0–3 gameplay cold open · 3–15 premise / fantasy (VO or 1–2 cards) · 15–40 hook + variety · 40–50 title reveal on a music hit · 50–60 "Coming <window>" + Wishlist |
| `launch` (General) | 60–90 s | 0–5 best moment · 5–25 hook / verbs · 25–55 escalation + story beats · 55–75 breadth montage (+ ≤ 2 review quotes if any) · 75–90 "Out now" + price/platforms + Buy/Wishlist |
| `festival` (Next Fest / demo) | 30–45 s | 0–5 thumbstopper · 5–25 one complete game loop · 25–38 escalation peak · 38–45 "Play the demo now" + dates |
| `tell-show-repeat` (Gameplay) | 45–75 s | genre shot · [card → matching shot(s)] × 3–5 · montage · end slate (easiest template; cards about the fantasy, not features) |
| `social` (vertical 9:16 / 1:1) | 15–30 s | 0–1.5 action at frame 1 · a loop of all key verbs · last 2–3 s title + CTA burned in; captions burned; text inside the safe zone (top 10 %, bottom 20 %, right 12 % reserved for the app's UI) |

## beats.json
```json
{"version": 1, "type": "gameplay", "target_s": 60, "bpm": null,
 "core_message": "one sentence", "cta": "Wishlist on Steam",
 "beats": [
   {"id": "thumbstopper", "start": 0, "end": 5, "hook": true, "intent": "late-game chaos showing the hook",
    "shots": ["s01", "s02"], "card": null, "vo": null, "music": "cold open, already at full energy"},
   {"id": "end-slate", "start": 55, "end": 60, "end_slate": true, "intent": "logo + platforms + CTA",
    "shots": [], "card": "Wishlist now", "vo": null, "music": "button ending"}]}
```
- `id` unique; the **hook beat** has `"hook": true` or an id containing `hook`; the **last beat** is the end slate
  (`"end_slate": true` or an id containing `slate`).
- Beats are contiguous: each `start` equals the previous `end`, the first starts at 0.
- `shots` are shot ids from shots.json; `card` is the on-screen text (≤ 7 words); `vo` the line spoken in this beat;
  `music` the energy note that becomes a composition-plan chunk (references/audio.md).

## What `trailer_edl.py check --beats beats.json` enforces
Errors: unknown type, no core message, gaps/overlaps, end ≤ start, duplicate ids, no hook beat, hook starting after
15 s, a card longer than 7 words, last beat not an end slate, a social cut over 180 s.
Warnings: total outside the type's range, hook after 10 s, a card shorter than 0.5 s + 0.33 s/word, end slate
outside 3–6 s (social 2–3 s), missing CTA or intent.
With `--shots shots.json` too, every beat's shots must exist and every shot's `beat` must be a beat id.

## Music sections from the beat sheet
Group neighbouring beats into 3–6 music sections (each 3–120 s, ElevenLabs' chunk limits) and generate the music with
a **composition plan whose chunk durations equal the section lengths** (music_v2/v2_5 always keep them). The cut
points then fall on section changes by construction; `beat_grid.py --sections composition_plan.json` names them in
the grid.
