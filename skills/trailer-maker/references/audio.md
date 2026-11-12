# Audio: music, VO, SFX, captions, mix

Read when generating or placing audio, writing VO, or when the mix sounds wrong. ElevenLabs tools are the harness's
`music`, `tts`, `sound_effect`, `transcribe`; every generation becomes an item (id `itm_…`) and is metered.

## Spend first
Estimate before generating and tell the user: music bills per minute (the confirm card estimates ~1,500 credits per
minute), sound effects per second (~40 credits/s at the default), speech per character. A 60 s trailer typically
needs: 1 minute of music (+ 1–2 alternates), 3–8 VO lines, ~10 SFX. Generations over `confirm_over_characters` ask
for approval. Reuse items instead of regenerating; record what you used in `audio/sources.json`:
`{"music": {"item": "itm_…", "plan": "audio/composition_plan.json", "seed": 7, "credits": 1520}, "vo": [...], "sfx": [...]}`.

## Music cut to the beat sheet (ElevenLabs composition plan)
1. Group beats into 3–6 sections (each 3,000–120,000 ms). Section lengths = beat lengths, so section changes land on
   the cut points by construction.
2. Write `audio/composition_plan.json` and call `music` with it (`music_v2_5` always keeps section durations):
```json
{"chunks": [
  {"text": "[Cold open] already at full energy, driving drums", "duration_ms": 7000,
   "positive_styles": ["dark synthwave", "driving drums", "120 bpm", "trailer energy", "instrumental",
                       "great production quality"], "negative_styles": ["vocals", "slow intro"]},
  {"text": "[Groove] steady pulse under gameplay", "duration_ms": 13000, "positive_styles": ["same palette", "steady"]},
  {"text": "[Build] two rising waves", "duration_ms": 25000, "positive_styles": ["rising", "risers", "toms"]},
  {"text": "[Climax] densest section, big hits", "duration_ms": 10000, "positive_styles": ["full", "big hits"]},
  {"text": "[Button] hard stop on the last downbeat", "duration_ms": 5000, "positive_styles": ["final hit", "tail"]}]}
```
   `music(composition_plan=<that object>, seed=<int>)` — the seed makes a re-roll reproducible-ish. The first
   chunk's styles set the genre: give it 6–7 styles. Instrumental by default (no lyrics under VO).
3. Copy the item's file to `audio/music.mp3`, then `python3 <skills>/trailer-maker/scripts/beat_grid.py
   audio/music.mp3 --sections audio/composition_plan.json --out audio/beats_grid.json` and set
   `"beat_grid": "audio/beats_grid.json"` in the EDL. `RESULT: FAIL low confidence` → pass `--bpm` (the tempo in the
   prompt) or cut to section boundaries only.
4. Snap: `trailer_edl.py check edl.json --grid audio/beats_grid.json` lists cuts off the grid; move `in`/`out` or
   `dur` by the reported frames. Big moments on `downbeats`.
A licensed track works the same way from step 3 (record the license in REPORT.md).

## VO
- Optional. Short lines (≤ 12 words), one idea each, written for the muted test too (cards or captions carry them).
- Script as `vo-script.md` with timeline marks, one line per cue: `@12.0 Every run rewrites the map.`
- `tts` per line (parallel), copy to `audio/vo-NN.mp3`, place with `"vo": [{"path", "at", "gain_db"}]`.
- Music ducks under VO automatically (`duck`: threshold 0.03, ratio 8, attack 20 ms, release 300 ms). Raise
  `threshold` if the music pumps, lower it if VO is masked.

## SFX
Accents the game doesn't make: whooshes into title cards, a hit on the logo, a riser into the climax, the button.
`sound_effect(description, duration_s)` → `audio/sfx-*.mp3` → `"sfx": [{"path", "at", "gain_db"}]`. Keep game SFX in
the clips (game feel sells); `game.gain_db` −6 dB under music is a good start.

## Captions
- From VO: `trailer_edl.py srt vo-script.md --out captions/en.srt` (block captions, ≤ 42 chars/line, ≤ 2 lines,
  1–6 s, at the `@` marks).
- From audio: `transcribe` the VO (or the master) → its transcript JSON → `trailer_edl.py srt transcript.json
  --out captions/en.srt [--offset <VO start>]`. Audio events come out as `[explosion]`.
- Hand-check every cue (names, terms). Add key SFX in brackets where they matter.
- Vertical burn-in: `srt ... --cards captions/cards.json --font "Assets/Fonts/Game SDF.asset"`, then
  `TrailerCards.Render("Trailer/<slug>/captions/cards.json")` renders `captions/png/cue-NNN.png`.

## Mix and loudness
`render` builds the mix: game (gain) + music (ducked) + VO + SFX → limiter at −1 dBFS → two-pass `loudnorm`
(I −14 LUFS, TP −1 dBTP, LRA 11) → `build/master.wav`. Every export carries the same master; `qc` measures the
result (±1 LU; true peak warn above −1, fail above −0.5 dBTP after AAC).

## FMOD / Wwise
The Recorder captures only Unity's built-in audio. With middleware, capture game audio separately and add it in the
edit (see references/shot-list.md), or set `"game": {"enabled": false}` and rebuild the soundscape from SFX.
