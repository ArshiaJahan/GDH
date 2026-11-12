# edl.json: the deterministic edit

Read when writing or changing `Trailer/<slug>/edl.json`. Start from `templates/edl.template.json`. All paths are
relative to the EDL's folder; all times are seconds (floats) and are rounded to frames on load.

```json
{"version": 1, "id": "steam-gameplay-20261112", "type": "gameplay", "fps": 60,
 "canvas": {"w": 1920, "h": 1080}, "scale_filter": "lanczos",
 "sources": {"s01": "capture/s01/take-02.mp4", "s05": "capture/s05/take-01.mp4"},
 "video": [
   {"id": "c01", "src": "s01", "in": 0.80, "out": 3.20, "speed": 1.0, "beat": "thumbstopper"},
   {"id": "c02", "src": "s05", "in": 2.00, "out": 3.00, "speed": 0.5, "freeze_end": 0.25,
    "transition_in": {"type": "cut"}, "vcrop": {"x": 0.62}},
   {"id": "c03", "card": "cards/title.png", "dur": 1.5, "bg": "#000000",
    "transition_in": {"type": "fadeblack", "dur": 0.25}}],
 "overlays": [{"image": "cards/wishlist.png", "start": 56.0, "end": 60.0, "pos": "bottom-center", "margin": 96, "fade": 0.2},
              {"image": "cards/rating-bug.png", "start": 0, "end": 4, "pos": "top-right", "margin": 48, "vertical": false}],
 "audio": {
   "game": {"enabled": true, "gain_db": -6},
   "music": {"path": "audio/music.mp3", "in": 0.0, "at": 0.0, "gain_db": 0, "fade_in": 0, "fade_out": 1.5},
   "vo": [{"path": "audio/vo-01.mp3", "at": 12.0, "gain_db": 0}],
   "sfx": [{"path": "audio/hit-boom.mp3", "at": 55.98, "gain_db": -3}],
   "duck": {"enabled": true, "threshold": 0.03, "ratio": 8, "attack_ms": 20, "release_ms": 300},
   "loudness": {"i": -14, "tp": -1.0, "lra": 11}},
 "beats_file": "beats.json", "beat_grid": "audio/beats_grid.json", "snap_tolerance_frames": 1,
 "captions": {"srt": "captions/en.srt", "burn_in_for": ["shorts", "tiktok"], "png_dir": "captions/png"},
 "poster_at": 7.5, "vertical": {"max_s": 60},
 "exports": ["steam", "youtube", "shorts"]}
```

## Semantics
- **Video items** play in order; there are no absolute start times, so gaps and overlaps are impossible.
  - Clip length = `(out − in) / speed + freeze_end` (frames: `round((out − in) / speed × fps) + round(freeze_end × fps)`).
  - Card length = `dur`. A card is a canvas-sized PNG (RGB or RGBA) composited over `bg`.
  - `transition_in` overlaps the previous item by `dur` (default 0.25 s): types `cut` (default), `fade`, `fadeblack`,
    `fadewhite`, `wipeleft`, `wiperight`, `slideleft`, `slideright` (ffmpeg xfade names). Item *k* starts at
    `end(k−1) − dur(k)`; the total is the end of the last item. The first item can't have a transition.
  - `speed` 0.1–4 (game audio follows with `atempo`; below 0.25 the clip's game audio is silent).
  - `vcrop.x` (0..1) is the horizontal focus for vertical exports (`layout: "crop"`); without it vertical uses
    `layout: "blurpad"`.
- **Overlays** are RGBA PNGs shown between `start` and `end` (timeline seconds) at `pos` (`center`, `top-left`,
  `top-center`, `top-right`, `middle-left`, `middle-right`, `bottom-left`, `bottom-center`, `bottom-right`) with
  `margin` pixels and an alpha `fade` in/out. `"vertical": false` leaves an overlay out of vertical cuts; on vertical
  canvases overlays wider than the canvas are scaled to fit.
- **Audio**: game audio from the clips (gain), music placed at `at` from `in` with fades, VO and SFX at `at`;
  music ducks under VO (sidechain compressor) when `duck.enabled`; then a −1 dBFS limiter and two-pass EBU R128
  loudness normalization to `loudness` → `build/master.wav` (48 kHz stereo).
- **Captions**: `srt` is the sidecar for YouTube/X; for `burn_in_for` platforms each cue *n* is burned from
  `<png_dir>/cue-NNN.png` (render them with TrailerCards from the cards.json `srt --cards` writes), placed above the
  bottom 20 % safe zone. Missing PNGs → a note and no burn-in.
- **poster_at**: the Steam poster frame (a gameplay frame without text).
- **beat_grid**: `beat_grid.py` output; `check` reports cuts more than `snap_tolerance_frames` off the nearest beat.

## Validation (`trailer_edl.py check edl.json [--beats beats.json] [--grid beats_grid.json]`)
Errors: unknown `src` or a missing file; `out ≤ in`; `out` beyond the source's duration (ffprobe); `speed` outside
0.1–4; a transition as long as either neighbour; overlays outside the timeline, not RGBA, or larger than the canvas;
a card PNG that isn't canvas-sized; audio `at` beyond the end; an unknown export; a social cut over 180 s; the first
item a card longer than 1.0 s (hook rule).
Warnings: total outside the type's range; no end slate in the last 6 s (a final card or an overlay visible at the end);
variable-frame-rate sources; missing captions for YouTube/X; poster on a card; cuts off the beat grid; the cut's
length vs beats.json; the hook clip starting after 15 s.

## Build outputs (`render`, `export`)
```
build/clips/<id>.mov      pass 1: one item → exact frame count, ProRes 422 HQ + PCM (cached by spec + source stat)
build/picture.mov         pass 2: cuts (concat), dissolves (xfade/acrossfade), overlays
build/premix.wav          pass 3: game + music (ducked) + VO + SFX, limiter
build/master.wav          pass 3: two-pass loudnorm, 48 kHz stereo
build/master.mov          pass 4: picture + master.wav (input of every export)
build/proxy.mp4           render --proxy: half-size H.264 preview (playable inline in the app)
build/vertical/...        the 9:16 re-render used by shorts/tiktok exports
```
`plan edl.json [--json] [--proxy] [--platform P]` prints every ffmpeg command without running it.

## Worked example (timeline math at 60 fps)
c01: in 0.80, out 3.20 → 144 frames, 0–144. c02 (cut): (3.00 − 2.00)/0.5 = 2.0 s = 120 frames + freeze 15 → 135
frames, 144–279. c03 (fadeblack 0.25 s = 15 frames): card 1.5 s = 90 frames, starts 279 − 15 = 264, ends 354.
Total 354 frames = 5.9 s.
