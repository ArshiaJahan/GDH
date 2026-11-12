---
name: trailer-maker
description: Plans, captures and cuts a game trailer for a Unity 6 project - creative brief, beat sheet per trailer type (Steam gameplay, announce/teaser, launch, festival/demo, social cutdown), shot list captured in Play Mode with Unity Recorder, deterministic ffmpeg edit from a JSON EDL, ElevenLabs music/VO/SFX cut to the beat sheet, trailer review, and platform exports (Steam, YouTube, X, Shorts/TikTok vertical). Use for "make a trailer", teaser, launch/announce video, Steam trailer, Next Fest video, gameplay capture, social clip, vertical cutdown.
---

# trailer-maker

Make a trailer from the real game: brief → beat sheet → shot list → scripted capture → deterministic edit → music/VO
→ independent review → platform exports. The engine captures repeatable shots, a JSON edit list renders the cut, and
the user approves the brief and the final cut.

Pinned: Unity 6000.3, Unity Recorder 5.1 (`com.unity.recorder`), MCP for Unity 10.3, URP 17.3 2D, ffmpeg ≥ 6
(Homebrew `ffmpeg`, external program, never bundled). Tools are MCP for Unity tools (your client may prefix them).
`<skills>` = the folder holding these skills; `<slug>` = `<type>-<yyyymmdd>` (e.g. `steam-gameplay-20261112`);
`T` = `Trailer/<slug>` at the Unity project root (outside `Assets/`). Run the scripts from the project root.

## When to use / not to use
- Use for a Steam/announce/launch/festival/social trailer, gameplay capture for marketing, b-roll, vertical cuts,
  press-kit loops, or re-cutting an existing capture to music.
- Not for: generated "gameplay" footage (never), store screenshots (play-verify screenshots), in-game cutscenes
  (Timeline work), or fixing the game feel itself (game-feel-pass first: a trailer can't hide a flat game).

## Inputs
- The brief, filled with the user from `templates/brief.template.md` → `T/brief.md`: type, one-sentence core
  message, length, platforms, CTA and date, pillars, player fantasy, don'ts/spoilers, audio middleware, pass score.
- `TASTE.md` (three words), the GDD's pillars, `PROJECT.md`; fonts/logo asset paths for cards.
- Defaults unless the brief says otherwise: exports **Steam master 1080p + YouTube + vertical 9:16** (X optional),
  review pass score **7/10** with **2 rounds max**, Unity built-in audio.

## One-time setup
1. `python3 <skills>/trailer-maker/scripts/trailer_edl.py doctor` → `RESULT: OK` (else `brew install ffmpeg`;
   text and captions are PNG overlays, so the slim formula is enough).
2. `manage_packages` → install `com.unity.recorder` (5.x). Copy `<skills>/trailer-maker/templates/Harness.Trailer/`
   to `Assets/Harness/Trailer/`; run compile-fix-loop until 0 errors (the code compiles before and after the Recorder
   is installed). Copy play-verify's `Harness.Verify` too if shots use scripted `input`.
3. Project Settings → Audio → Default Speaker Mode **Stereo**. If the game uses **FMOD or Wwise, the Recorder does not
   capture its audio**: record game audio separately or rebuild it in the mix (references/audio.md).
4. Add the media paths to the project's `.gitignore` (references/shot-list.md lists them): captures, renders,
   exports, review sheets and generated audio stay out of git; brief.md, beats.json, shots.json, edl.json, cards.json,
   captions and REPORT.md are committed.

## Procedure (the `trailer` workflow: one phase per step)
1. **Brief.** Interview the user (grill-me style, few questions at a time) and write `T/brief.md`. Freeze the pass
   score. The user approves the brief before anything is captured.
2. **Beat sheet.** Pick the type's template (references/beat-sheets.md), write `T/beats.json`; the hook lands by
   10 s. `python3 <skills>/trailer-maker/scripts/trailer_edl.py check --beats T/beats.json` → `RESULT: OK`.
3. **Shot list.** Every beat gets 2–4 candidate shots in `T/shots.json` (references/shot-list.md): scene, a static
   setup method the game provides (save state, spawn, seed, god mode), optional scripted input, takes. Add missing
   `TrailerSetups` methods to the game (architecture-patterns, compile-fix-loop).
   `trailer_edl.py check --beats T/beats.json --shots T/shots.json` → OK.
4. **Capture** (editor open; the Recorder doesn't run in `-batchmode`). Precheck like play-verify (instance set, ready,
   not playing, 0 compile errors). `execute_code`: `return Harness.Trailer.TrailerCapture.Start("T/shots.json", "");`
   Play Mode starts and the MCP connection drops during the domain reload: wait 5 s, then poll
   `return Harness.Trailer.TrailerCapture.Status();` every 5–10 s until `done ok=<n> failed=<m> ...`. Read `[TRAILER]`
   lines with `read_console`. Without MCP: the GUI editor from the CLI,
   `Unity -projectPath . -executeMethod Harness.Trailer.TrailerCapture.RunFromCli -trailerShots T/shots.json`
   (needs a logged-in display; never in CI/SSH). Then `check --shots T/shots.json --capture T/capture/report.json` → OK.
   Look at each take: `trailer_edl.py sheet T/capture/<shot>/take-NN.mp4 --scenes` and `view_image` the sheet; for
   many long takes, give shot logging to read-only subagents (one per shot, sheets + scene list → best take and
   in/out points). Recapture failed or weak shots with `Start(..., "s03,s07")`.
5. **Rough cut.** Render cards: write `T/cards.json` from `templates/cards.template.json` and run
   `return Harness.Trailer.TrailerCards.Render("T/cards.json");` (edit mode). Write `T/edl.json`
   (references/edl-schema.md; picks from the takes, beats as labels). `check T/edl.json --beats T/beats.json`, then
   `trailer_edl.py render T/edl.json --proxy` (fast preview, `build/proxy.mp4`), iterate, then
   `render T/edl.json` → `T/build/master.mov`.
6. **Music, VO and SFX** (references/audio.md). Estimate credits and say them. Music from a composition plan whose
   sections match the beat sheet, VO via `tts`, SFX via `sound_effect`; copy files to `T/audio/`, record items in
   `T/audio/sources.json`. `python3 <skills>/trailer-maker/scripts/beat_grid.py T/audio/music.mp3 --sections
   T/audio/composition_plan.json --out T/audio/beats_grid.json` → OK; `check T/edl.json --grid
   T/audio/beats_grid.json`, fix off-grid cuts; captions with `trailer_edl.py srt`; `render T/edl.json` again.
7. **Trailer review.** `sheet T/build/master.mov --first5`, `sheet T/build/master.mov`, and a QC pass on a test export
   (`export T/edl.json --platform steam`, `qc T/exports --edl T/edl.json --beats T/beats.json`). Spawn the three
   reviewers from references/reviewers.md with the same evidence pack; save their JSON to `T/review/<name>.json`;
   `python3 <skills>/trailer-maker/scripts/trailer_review.py "T/review/*.json" --pass-score 7 --round 1`.
   PASS → step 8. REFINE → fix the evidenced issues (re-cut, recapture, re-mix), re-render, re-review with `--round 2`.
   ESCALATE (spread > 3, or round 2 failed) → show the user the sheets, reviews and minimum score: Accept as is /
   Revise with my notes / Park.
8. **Exports.** `trailer_edl.py export T/edl.json --all` (the EDL's `exports`; `--x-720` for X at 1280×720),
   `poster T/edl.json`, then the final QC with `python3 <skills>/trailer-maker/scripts/trailer_qc.py T/exports --edl
   T/edl.json --beats T/beats.json` → `RESULT: OK` (the same checks as `trailer_edl.py qc`; the workflow's Exports
   phase waits for this script's RESULT). Write `T/REPORT.md`: deliverables and their
   qc rows, sources (takes used), music/VO/SFX items with prompts, seeds and credits, AI-generated content (for the
   Steam content survey), caption status, review decision. The user watches the cut with sound and muted and approves.

Each script prints `RESULT: OK|FAIL ...` last; `TRAILER_OUTPUT: <path>` lines make the app index the video, audio and
image files as items, so the cut plays inline in the session.

## Rules
- Real gameplay only. Never generate footage that pretends to be the game. Generated music/VO/SFX are fine; list them
  in REPORT.md.
- First frame is gameplay in motion; genre within 2 shots; **hook ≤ 10 s (hard fail > 15 s)**; no studio logo or
  rating card before the hook (a small rating bug overlay instead, unless the rating board requires full screen).
- Must read muted: every beat understandable without audio; cards ≤ 7 words, on screen ≥ 0.5 s + 0.33 s/word.
- First Steam trailer = Gameplay category, HUD visible, gameplay-dense end to end (the microtrailer samples it).
- End slate 3–6 s (social 2–3 s): logo + platform(s) + CTA + date if known.
- Capture at 60 fps constant rate; never edit variable-frame-rate sources; pixel art uses `scale_filter: neighbor`.
- No more than 3 flashes per second over large areas (`qc` warns); captions block-style, ≤ 42 chars/line, ≤ 2 lines.
- Spend: estimate ElevenLabs credits before generating; reuse items.
- Never write captures, cards or exports under `Assets/` (import churn, quality-ladder visual gate); never save the
  user's scenes for a capture (setups run at runtime; TrailerCards uses a temporary scene).
- The review pass score is frozen in the brief before the first review; 2 rounds max, then the user decides.

## Failure handling
- **Recorder never starts:** batchmode (use the GUI editor), compile errors, Game View hidden/too small, or the
  Recorder package missing (`Start` returns `error: install com.unity.recorder`). URP 2D can't use Targeted Camera:
  the template records the Game View.
- **No audio in takes:** Default Speaker Mode not Stereo, `audio.capture` false, or FMOD/Wwise (record separately).
- **A take fails** (`status=failed`): read its `message` in report.json and `[TRAILER]` lines; fix the setup method or
  the scripted input; recapture only that shot.
- **MCP drops for good during capture:** the job continues in the editor; poll `Status()` after reconnecting, or read
  `T/capture/report.json`.
- **ffmpeg missing** (exit 3): `brew install ffmpeg`. **render fails:** re-run `check`; `plan` shows the exact command.
- **qc fails:** loudness → check gains and re-render; black start → first clip `in` later; dims/fps → EDL `fps`/canvas.
- **TrailerCards PNG has no transparency** under the project's pipeline [UNVERIFIED for every URP setup]: use opaque
  `bg` cards and keep alpha only for overlays; check with `check` (overlays must be RGBA).

## References
- references/craft.md: read for the brief, beat sheet, card copy, and when judging a cut (Derek Lieu, Steam rules).
- references/beat-sheets.md: read when writing beats.json (per-type timing tables, what `check --beats` enforces).
- references/shot-list.md: read when writing shots.json, adding trailer setups to the game, capturing, or setting up `.gitignore`.
- references/edl-schema.md: read when writing or debugging edl.json, render and the build outputs.
- references/audio.md: read before generating music/VO/SFX, for captions, ducking and loudness.
- references/platform-specs.md: read when choosing deliverables, before export, and when qc fails.
- references/reviewers.md: read for step 7 (reviewer briefs, JSON contract, aggregation).

## Verify
- `check --beats`, `check --shots`, `check --capture`, `check T/edl.json` each ended with `RESULT: OK`.
- `beat_grid.py` ended with `RESULT: OK` (or `--bpm` was given) and off-grid cuts were fixed or accepted.
- `trailer_review.py` printed `TRAILER_REVIEW: PASS` with `RESULT: OK`, or the user accepted an ESCALATE.
- `qc T/exports --edl T/edl.json` ended with `RESULT: OK` for every export; `T/exports/poster.png` exists for Steam.
- `T/REPORT.md` lists deliverables, sources, AI-generated audio with item ids and credits, and the review decision;
  the user approved the final cut.
