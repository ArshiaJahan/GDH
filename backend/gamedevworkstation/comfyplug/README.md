# ComfyPlug

ComfyPlug drives ComfyUI like an API: one command (or one Python call) per image, image edit, 3D model or sound,
plus `workflow` for any other ComfyUI workflow (video included). Images and edits: Qwen Image 2.1. Models: a Qwen
reference image, then TRELLIS.2. Sound: Stable Audio 3 medium. It needs ComfyUI running (default
`http://127.0.0.1:8188`), comfy-cli (`comfy` on PATH, in `~/.local/bin`, or `COMFY_CLI=<path>`) and, for sound,
`ffmpeg` on PATH.

From another machine (for example a Mac on the same network or Tailscale): set `COMFY_URL=http://<pc-ip>:8188`;
see `REMOTE_MAC.md`. From Python, `comfyplug.configure(url=..., cli=...)` does the same.

Run it from the folder that contains `comfyplug/` as `python -m comfyplug <command> ...`, or anywhere as
`python path/to/comfyplug <command> ...`. Paths are relative to where you run it. Python 3, no extra packages
(sound post-processing needs numpy). GameDevWorkstation (GDH) bundles ComfyPlug: there it is the agent's
`comfyplug` tool and `gdw comfyplug <command> ...`.

## Commands

```
python -m comfyplug check

python -m comfyplug image --prompt "<prompt>" --out Recordings/<topic>/<name>.png
        [--seed 11] [--aspect "1:1 (Square)"] [--steps 25] [--megapixels 1.0] [--transparent]

python -m comfyplug edit --image <in.png> --prompt "<instruction>" --out <out.png>
        [--seed 11] [--steps 25] [--width W --height H]   # default: the input's size, capped near 1 MP

python -m comfyplug model --prompt "<object>" --out Recordings/models_raw/<game>/<name>.glb
        [--seed 1] [--image-seed N] [--view "three-quarter front view"] [--faces 12000] [--texture 1024]
        [--ref-out <ref.png>] [--ref-only] [--from-image <ref.png>]

python -m comfyplug sound --prompt "<sound>" --out <name>.wav
        [--seconds 2] [--seed 1] [--category SFX] [--raw-out <raw>] [--no-trim] [--sample-rate 44100]
        [--variants N]            # writes <stem>_1.wav .. <stem>_N.wav with seed+i

python -m comfyplug workflow <workflow.json> --out-dir <dir>
        [--slot NODE.INPUT=VALUE ...] [--ext .mp4 ...] [--prefix name] [--timeout 1800]
        # any workflow: VALUE is JSON when it parses (7, true, "text"), else a plain string;
        # keeps every image/video/audio/3D output (or only --ext ones)

python -m comfyplug batch <file.json> [name ...] [--force]

# sound post-processing (postaudio.py; needs numpy + ffmpeg, 16-bit PCM wav)
python -m comfyplug loop <raw.wav> <out.wav> [--seconds 4] [--crossfade 0.5] [--lufs -22] [--skip 0.3]
python -m comfyplug normalize --target -16 a.wav b.wav [--backup <dir>] [--dry-run]
python -m comfyplug normalize --rules <rules.json> [--toy id ...] [--backup <dir>] [--report <md>] [--dry-run]
python -m comfyplug measure a.wav b.wav [--loop]
```

Aspect labels: `"1:1 (Square)"`, `"9:16 (Portrait Widescreen)"`, `"16:9 (Widescreen)"`, `"21:9 (Ultrawide)"`.

`--transparent` wraps the prompt so Qwen returns an RGBA image. `--sample-rate 22050` suits short fidget clips.
`--no-trim` keeps the clip as generated (no silence cut, fade or normalise).

**Model in two steps.** Run `model --ref-only` first: it writes `<name>_ref.png` and stops. Look at the image. If it
is good, run `model --from-image <ref.png>` (same `--out`, `--seed`); if not, change the prompt or `--image-seed`.
A full run is about 3 to 10 minutes. Use `--view "straight front view"` when the model must face a known axis.

## Sound post-processing

- **`loop`** turns a raw (`--no-trim`) sound into a seamless loop: removes DC and rumble (30 Hz high-pass), picks the
  steadiest stretch of the source (smallest spread of the 100 ms loudness envelope; skips `--skip` s at both ends),
  crossfades its tail into its head (the loop end is picked up to 160 ms early where the tail best matches the head;
  linear fade when the waveforms correlate, equal-power otherwise), normalises to `--lufs` by gain (capped so the peak
  stays under -1.2 dB), writes 16-bit mono at the source rate and prints a JSON report including `join`: wrap step vs
  the file's normal sample steps, first/last 10 ms RMS and coarse spectrum, `ok`. Generate sources 6 to 8 s long
  (`"trim": false`, several seeds), run `loop` on each, keep the one with `join.ok`, the lowest `level_wobble_db` and
  `peak_limited` false. Loops are 2 to 4 s: the shorter the target, the steadier a stretch it finds.
- **`normalize`** is gain only (never clips, keeps rate and channels). `--target` takes files; `--rules` takes a
  json (`root`, `backup`, `ceiling_db`, `classes` {name: LUFS}, per toy `main` patterns, `offset_main`, and ordered
  `rules` [[glob, class or LUFS]]; the first matching rule wins; `main` files get `offset_main` dB lower target and
  peak ceiling so the most frequent sound is quieter).  Originals
  are copied to `--backup` first (never overwriting an earlier backup). Where a clip is too spiky to reach its LUFS
  without clipping, the gain stops at the peak ceiling and the row is marked `lim`.
- **`measure`** prints integrated LUFS (ffmpeg ebur128), true peak, sample peak and RMS as JSON lines. Clips under
  1.2 s are tiled back to back first, so their LUFS is the energy mean over the clip (a plain ebur128 run reads -70
  below 400 ms). `--loop` adds the join check.
- Python: `from comfyplug import postaudio` (`make_loop`, `verify_loop`, `measure`, `fit_gain`, `normalize_file`,
  `normalize_rules`, `fit_clip` for trimming a picked one-shot with a fade-out).

## Batch format

A JSON list of objects. `kind`, `out` and `prompt` are required; every other key is an option of that kind (same
names as the CLI flags, with underscores). `name` is optional and defaults to the file stem of `out`; it is what
the name filter matches.

```json
[
  {"kind": "image", "out": "Recordings/t/duck.png", "prompt": "...", "seed": 7, "aspect": "1:1 (Square)", "transparent": false},
  {"kind": "model", "out": "Recordings/models_raw/g/duck.glb", "prompt": "...", "seed": 1, "view": "straight front view", "faces": 12000},
  {"kind": "model", "out": "Recordings/models_raw/g/duck.glb", "prompt": "...", "ref_only": true},
  {"kind": "sound", "out": "Recordings/t/click.wav", "prompt": "...", "seconds": 1, "seed": 3, "sample_rate": 22050, "variants": 3}
]
```

The runner skips an item whose output file(s) exist (use `--force` to redo), prints one line per item
(`<kind> <name> ok|skipped|FAILED ...`), keeps going after a failure, and exits 1 if anything failed.

From Python: `from comfyplug import generate_image, edit_image, generate_model, generate_sound, generate_variants,
run_any` (put the folder that contains `comfyplug/` on `sys.path`).

## Rules

- No brand, franchise, film or show names in any prompt. Describe the style instead.
- Look at every output (Read the PNG, check the sound, render the model) before using it, and look at the model
  reference image before spending minutes on TRELLIS.
- ComfyUI runs one job at a time. Run batches in sequence (not several comfyplug processes at once); they queue.
- Fixed behaviour you should not undo: the Qwen prompt is set on slot `459/452` of the "direct" workflow with the
  re-prompter off (`459.switch=false`); Stable Audio's re-prompter is off (`52.use_reprompt=false`); TRELLIS uses
  `316.value=true` (TRELLIS.2, not Pixal3D) and `248.switch=true` (background removal); the run saves several
  GLBs and the textured one is kept.
- The bundled workflow JSONs live in `workflows/`.
