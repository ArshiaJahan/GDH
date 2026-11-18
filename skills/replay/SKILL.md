---
name: replay
description: Records and replays instrumented Unity sessions deterministically, verifies frame-by-frame checkpoint hashes, and exports gameplay GIF/MP4 on request. Use for "record this run", "reproduce inputs", "verify replay", "GIF/video of this run".
---

# replay

Record an instrumented Unity session, replay it, verify frame-by-frame
checkpoint hashes, and export gameplay GIF or MP4 on request. The guarantee is
same-environment repeatability, checked against the state you register. It is
not cross-machine determinism. Input System only.

Pinned: Unity 6000.3.21f1, Input System 1.20.1, Test Framework 1.6.0.
`<skills>` = the folder holding these skills.

## When to use / not to use

- Use to record a bug-to-test, reproduce inputs deterministically, prove
  repeatability (L3 `replay_verified` evidence), or make a GIF/video of a run.
- Use after a play-verify run whose acceptance criteria need stronger
  repeatability evidence.
- Not for visual regression (no pixel comparison yet), softlock diagnosis,
  cross-platform lockstep, legacy Input Manager projects, or trailers
  (trailer-maker owns the creative edit; replay's capture is for evidence).

## Inputs

- A Unity project with `com.gdw.replay` installed.
- For replay: a `.gdwreplay` archive from a previous record run.
- Optionally: `run_id` (record picks `rr_<16 hex>` when omitted), `replay_path`
  (project-relative `.gdwreplay`, default
  `Logs/harness/replay/<run_id>/run.gdwreplay`), `scene` (`Assets/...unity`),
  `seed` (uint32), `fixed_dt` (seconds, 0.001 to 1.0, default `1/60`),
  `subjects` (up to 32 provider ids or scene paths), and `capture`
  (`formats`, `backend`, `start_frame`, `end_frame_exclusive`, `width`,
  `height`, `fps`).
- `record` takes no `replay_path`. `replay_stop` and `replay_status` take only
  `run_id`. `replay_render` requires `capture`.

## One-time setup

1. `unity op=replay_install` installs the `com.gdw.replay` package
   (`Packages/com.gdw.replay`, version `0.1.0`). It needs setup consent. It
   refuses to install when a shipped file was edited in the project. An older
   package is updated in place. It adds any missing `com.unity.test-framework`,
   `com.unity.inputsystem` and physics module entries to
   `Packages/manifest.json` (existing pins are kept) and adds the package to
   `testables`. The package provides GdwRandom, InputTraceAdapter,
   ReplaySession, and the state-hash framework providers.

2. Route gameplay randomness through `GdwRandom.Stream("combat")` etc. The
   package ships `SeededRng` (xorshift32 with FNV stream derivation) and
   `GdwRandom.Reset(seed)`.

3. Register state providers (`IReplayStateProvider`) with
   `ReplayRegistry.Instance.Register("game.hp", provider)` for any state that
   should be checkpointed: HP, inventory, objectives, timers. At least one
   gameplay provider is required.

4. Verify readiness: compile-fix-loop (0 errors), then `unity op=status` shows
   the route. Routes differ by op:
   - `record`, `replay_stop` and `replay_status` are live-only. They need the
     open Editor through MCP or the CLI live route.
   - `replay`, `replay_verify` and `replay_render` run in a batch Editor (CLI
     batch or `unity.sh`). On any other route they return `skipped: replay
     needs a batch route`.

## Procedure

1. **Readiness audit.** Check the project compiles, the replay package is
   installed, and at least one gameplay provider is registered. Gameplay code
   that reads the legacy Input Manager (`Input.GetAxis` etc.) is not
   supported: the Editor scans for it when a run starts and refuses to record
   or replay, naming the files and calls (status `error` in the report).

2. **Record.** `unity op=record [seed=42] [fixed_dt=0.016666667]
   [subjects=["game.hp","game.inventory"]]`. The session resets to the build
   scene, seeds RNG, loads the scene, and records input + checkpoint hashes at
   every frame. Recording is live-Editor only and needs change permission (the
   code is shown first). The call returns once recording has started. Stop it
   with `unity op=replay_stop run_id=...`; it also stops by itself after
   `[unity.replay] max_seconds` (default 600). Output: `<project>/Logs/harness/
   replay/<run_id>/run.gdwreplay`.

3. **Replay.** `unity op=replay run_id=...` replays a recorded archive on the
   same project (batch route, change permission). The session resets, loads
   the scene, and replays every input frame, comparing checkpoint hashes
   throughout. Divergence at the first mismatch produces a report with
   `first_divergent_frame`, `provider_id`, and expected/actual hashes. If you
   pass `scene` or `seed` and they differ from the archive's, the report is
   `incompatible`.

4. **Verify.** `unity op=replay_verify run_id=...` replays and requires a
   passing result with clean console and complete frame and tick comparison.
   This is the L3 `replay_verified` evidence path. It follows test consent, and
   it runs in Plan only mode. With `capture` it writes files, so it needs
   change permission instead.

5. **Render (GIF/MP4).** `unity op=replay_render run_id=...
   capture={formats:["mp4","gif"], backend:png, width:1280, height:720,
   fps:60}` replays with per-frame PNG capture, then exports MP4 and GIF via
   ffmpeg. It needs change permission. `backend` is `auto`, `png` or
   `recorder`; `auto` means `png`. MP4 output is silent. `backend:recorder`
   uses the Unity Recorder only when `com.unity.recorder` is already
   installed (never installed automatically). Divergence during replay labels
   the output unverified. After a successful export, that export's own
   `capture/frames/` PNGs are deleted.
   Capture limits: width and height are even, 16 to 1920 by 16 to 1080
   (default 1280x720); fps is 1 to 60 (default 60); a known frame range may
   not exceed `capture_max_seconds` (120), and a GIF range may not exceed
   `gif_max_seconds` (8). The export trims MP4 to 1920x1080, 60 fps and 120 s,
   and GIF to 480 wide, 15 fps and 8 s, and reports each trim.

   Or use the CLI script from the project root:
   ```
   python3 <skills>/replay/scripts/replay_media.py doctor
   python3 <skills>/replay/scripts/replay_media.py plan <capture.json>
   python3 <skills>/replay/scripts/replay_media.py export <capture.json> <frames_dir> <out_dir>
   ```

6. **Report.** Each op returns a `ReplayReport`:
   - `status`: `pass | diverged | incompatible | error | cancelled`
   - `environment`: `matched | differs`, with `environment_diff` listing the
     fields that differ (`unity_version`, `os`, `cpu`, `project_id`,
     `scene_guid`, `package_versions`, `package_lock`). Only fields the
     archive recorded and the backend can read are compared.
   - `frames` / `ticks`: expected vs compared counts
   - `first_divergent_frame` / `first_divergent_tick`: null when pass
   - `provider_id` / `expected_hash` / `actual_hash`: at divergence
   - `console`: error/warning counts (pass needs zero errors)
   - `artifacts`: paths to archive, report, results XML, editor log, exports

   Status precedence: `cancelled > incompatible > error > diverged > pass`.
   Replay never refuses on an environment mismatch. It always runs and the
   report records what differed. `incompatible` means the archive is unusable
   (bad format, major version, missing or oversized archive) or `scene`/`seed`
   don't match it. A missing `replay_path` file is `error`.

7. **L3 evidence.** When a headless AC in BACKLOG.md names
   `ReplayVerificationTests.LogMatchesCheckpoints`, the quality ladder
   accepts `replay_verified` evidence rows (kind=`replay_verified`,
   observed=`tool`, status=`pass`, full frame comparison, zero console errors,
   immutable log/replay digests). Run `unity op=replay_verify
   subjects=["M1-S02-AC1"]` to scope the verification to that AC.

## Rules

- The guarantee is same-environment repeatability, checked against the state
  you register through providers. State you don't register is not checked.
  Environment differences (Unity version, OS, CPU, packages, content) never
  block a replay. They show up as `environment: differs` in the report, and a
  `diverged` result on a differing environment may be that difference.
- Input System only. The legacy Input Manager is not supported.
- Recording is live-Editor only. Replay, verify and render run in batch.
- The PNG-per-frame capture path is the default backend (`auto` = png). The
  Unity Recorder is used only when `backend:recorder` is explicitly requested
  and `com.unity.recorder` is already present (never installed automatically).
- MP4 output is silent. Audio is not captured.
- Timer-based Input System interactions (Hold, Tap with custom timing) and
  runtime `timeScale` changes are not guaranteed to replay identically.
- Permissions: `replay_install` needs setup consent. `record`, `replay`,
  `replay_render`, `replay_stop` and verify-with-capture need change
  permission and don't run in Plan only mode. `replay_verify` without
  `capture` follows test consent. `replay_status` is read-only.
- `.gdwreplay` archives are never extracted. The reader validates every member:
  bounded sizes, CRC, no traversal/symlinks, no decompression bombs,
  `manifest.complete == true`. Defaults: `max_archive_mb` 512,
  `max_trace_mb` 256, `max_seconds` 600.
- Recordings and reports are kept under `<project>/Logs/harness/replay/<run_id>/`.
  After a successful export, that export's own intermediate `capture/frames/`
  PNGs are deleted. Nothing else is deleted automatically. `replay_status` and
  an export result warn when `Logs/harness/replay/` is over
  `[unity.replay] warn_total_mb` (default 2048 MiB).
- REST: `POST /api/sessions/{sid}/replays/{record|replay|verify|render}` return
  202 with `{job_id, run_id, status_url}`; `POST .../replays/{run_id}/stop` and
  `GET .../replays/{run_id}` stop a run and read its status.

## References

- references/format.md: `.gdwreplay` v1 archive format and canonical state
  hashes (golden vectors).
- references/determinism.md: what is deterministic, what isn't, and how to
  route randomness and physics.
- references/troubleshooting.md: common failures, divergence causes, and how
  to fix them.

## Verify

- `unity op=status` shows a route and no readiness errors.
- `unity op=record [seed=0]` creates `<run_id>/run.gdwreplay` with a
  complete manifest and contiguous frames.
- `unity op=replay run_id=...` returns `status: pass` with
  `frames.expected == frames.compared` and `console.errors == 0`.
- `unity op=replay_verify run_id=...` returns `status: pass` with complete
  frame comparison and a clean console. Check `environment` too: `differs`
  means the pass came from a different environment than the recording.
- `replay_media.py doctor` exits 0 with `RESULT: OK` when ffmpeg is ready.
