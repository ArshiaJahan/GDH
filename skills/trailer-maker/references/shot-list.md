# Shot list and capture

Read when writing `Trailer/<slug>/shots.json`, adding trailer setups to the game, or capturing.

## shots.json (consumed by Harness.Trailer.TrailerCapture and `trailer_edl.py check --shots`)
```json
{"version": 1, "fps": 60, "resolution": {"w": 1920, "h": 1080}, "source": "game_view", "codec": "mp4",
 "output_dir": "Trailer/steam-gameplay-20261112/capture",
 "audio": {"capture": true, "mute_mixer_params": ["MusicVol"]},
 "shots": [{
   "id": "s01", "beat": "thumbstopper", "scene": "Assets/Scenes/Game.unity",
   "setup": "Game.TrailerSetups.LateGameArena", "setup_arg": "seed=42;wave=12",
   "input": "hold right 1; tap Space; wait 0.4; tap J",
   "warmup_s": 1.5, "duration_s": 6.0, "time_scale": 1.0, "takes": 3,
   "hide": {"objects": ["DebugOverlay", "FPSCounter"], "cursor": true},
   "camera": {"cinemachine": "", "ortho_size": 0},
   "notes": "dash through the bullet curtain = the hook"}]}
```
| Field | Meaning |
|---|---|
| `fps` | capture rate; 60 constant (Recorder `FrameRatePlayback.Constant` + `CapFrameRate`), so a slow or unfocused editor still yields smooth video |
| `resolution` | Game View output size; 1920×1080 for 16:9 masters (record bigger, e.g. 2560×1440, only if you need crop room) |
| `source` | `game_view` (required for the URP 2D Renderer: Targeted Camera capture has no capture pass there) |
| `codec` | `mp4` (H.264, small) or `prores` (ProRes 422 HQ, big, best for heavy grading/speed ramps) |
| `output_dir` | relative to the Unity project root and **outside `Assets/`** (import churn, quality-ladder visual gate) |
| `audio.capture` | Unity built-in audio only, stereo. **FMOD / Wwise output is not captured** — see below |
| `audio.mute_mixer_params` | exposed AudioMixer parameters set to −80 dB during takes (e.g. the game's music, replaced in the edit) |
| `setup` | `Namespace.Type.Method`, a static `void M(string arg)` (or no-arg) method the game provides; called after the scene loads |
| `input` | play-verify's ScriptedInput script (needs `Harness.Verify` installed; ignored with a warning otherwise) |
| `warmup_s` | real seconds between setup and recording (let spawns settle, camera catch up) |
| `duration_s` | recorded length per take (≤ 120 s; long takes cost disk and review time) |
| `time_scale` | `Time.timeScale` during the take (prefer `speed` in the EDL for slow motion) |
| `takes` | separate files `capture/<id>/take-01.mp4` … — capture several and pick in the edit |
| `hide` | GameObjects (by name) deactivated during the take; `cursor` hides the OS cursor |
| `camera.ortho_size` | sets `Camera.main.orthographicSize` when > 0. `cinemachine` is advisory: activate a trailer camera from the setup method |

Output: `capture/<id>/take-NN.mp4` and `capture/report.json`:
`{"shots": [{"id": "s01", "takes": [{"take": 1, "file": "…", "frames": 360, "fps": 60, "duration_s": 6.0,
"status": "ok", "errors": 0, "message": ""}]}]}`. Console lines: `[TRAILER] shot=s01 take=1 status=ok frames=360 file=…`
and `[TRAILER] done ok=<n> failed=<n> report=<path>`. A take fails if the recorder didn't start, the file is missing,
the setup method threw, or any error/exception was logged during it.

## Capture checklist
1. `com.unity.recorder` 5.x installed; `Harness.Trailer` copied to `Assets/Harness/Trailer/`; 0 compile errors.
2. Project Settings → Audio → **Default Speaker Mode: Stereo** (the Recorder captures mono/stereo only).
3. Debug UI, FPS counters, dev watermarks hidden (`hide.objects`); cursor hidden.
4. The Game View is undocked or large enough; nothing overlaps it (the Game View source records what it renders).
5. Deterministic setups: fixed seed, save state or spawn helpers, god mode where a death would ruin the take.
6. `check --shots shots.json` passes before capturing; `check --capture capture/report.json` after.
7. Review takes with contact sheets (`sheet capture/s01/take-02.mp4 --scenes`), pick the take in the EDL `sources`.

## Debug tools worth adding to the game (Derek Lieu's capture list)
Free/marketing camera (pan, zoom, follow offset, hide HUD) · save states / load any level or wave · god mode and
infinite resources · spawn enemies, items and bosses on demand · time scale and pause · fixed random seed ·
toggles for HUD, damage numbers, debug overlays · a "trailer mode" that removes tutorials and pop-ups ·
weather/time-of-day/biome switch. Expose them as static `TrailerSetups.X(string arg)` methods so shots.json can call
them; keep them in an editor-only or development-build assembly.

## Game audio with FMOD or Wwise
The Recorder's `CaptureAudio` records Unity's built-in audio only. With FMOD/Wwise: set `audio.capture` to false,
record the game mix separately (FMOD Studio/Wwise profiler capture, or a loopback recorder while the take plays) and
add it per clip in the edit as SFX entries, or rebuild the important sounds from SFX/ElevenLabs in the mix.

## Where things go (and what to commit)
Project-side, at the Unity project root (outside `Assets/`):
```
Trailer/<slug>/  brief.md beats.json shots.json edl.json cards.json cards/*.png captions/
                 audio/ (+ audio/sources.json) capture/ build/ exports/ review/ REPORT.md
```
Commit the plans (brief.md, beats.json, shots.json, edl.json, cards.json, captions/*.srt, REPORT.md). Keep media out
of git — add to the project's `.gitignore` (vcs-hygiene owns it):
```
# trailer media (re-creatable from shots.json / edl.json)
Trailer/*/capture/
Trailer/*/build/
Trailer/*/exports/
Trailer/*/review/
Trailer/*/audio/*.mp3
Trailer/*/audio/*.wav
Trailer/*/cards/*.png
Trailer/*/captions/png/
```
Use Git LFS only if the user explicitly wants media versioned.
