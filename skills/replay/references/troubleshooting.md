# Record/replay troubleshooting

Common failures, what they mean, and how to fix them.

## Installation failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `install_required` error | `com.gdw.replay` package not installed | `unity op=replay_install` (needs setup consent) |
| Install skipped | Setup consent was not given | Approve the `replay_install` card; an older package is updated in place |
| `Not installing: ... was changed in this project` | Package files were edited by hand | Merge by hand or move the edited files away, then install again |
| `isn't a Unity project` | The session folder has no `ProjectSettings/ProjectVersion.txt` | Open the session in the Unity project root |

## Record failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Run refused: legacy `Input.GetAxis` calls named | Gameplay code reads the legacy Input Manager, which replay doesn't support | Migrate those call sites to the Input System |
| `replay record needs the open Editor` / `skipped` | Record is live-Editor only and the route is batch or unavailable | Open the Editor and use the MCP or CLI live route |
| `skipped` with an approval refusal | No change permission for live recording (or the session is in Plan only mode) | Approve the card, or leave Plan only mode |
| `bad_run_id`, `bad_capture_range`, `bad_capture_size` and other `bad_*` codes | A request field failed validation | Fix the field named in the message; `run_id` is 8-64 chars of letters, digits, `_` and `-` |
| Later divergence in code using `timeScale`, Hold or Tap | Timer-based interactions and `timeScale` changes are not guaranteed to replay identically | Avoid them in recorded paths |
| Trace `Overflowed == true` | Input event trace exceeded `max_trace_mb` (default 256 MB) | Increase limit or reduce recording duration |
| No `.gdwreplay` produced | Recording never started, or was stopped before the archive was written | Check `replay_status`, `max_seconds` (default 600) and the Unity log |

## Replay failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `status: incompatible` | Archive format or major version unusable, missing input trace, archive over `max_archive_mb`, or `scene`/`seed` doesn't match the archive | Record with the current replay package version; drop or fix `scene`/`seed` |
| `status: error`, `Replay archive not found` | `replay_path` or `run_id` points at no file | Check the path (default `Logs/harness/replay/<run_id>/run.gdwreplay`) |
| `status: diverged` at frame 0 (initial state) | Scene content, seed or project content differs from record time | Use the same commit, same seed, same scene; `environment_diff` lists the fields |
| `status: diverged` at frame N > 0 | Gameplay divergence: RNG draws differ, provider state doesn't match | Check `provider_id` and `expected_hash`/`actual_hash` in the report; add missing providers or route unseeded RNG through `GdwRandom` |
| `status: diverged` with `first_divergent_tick` mismatch | Fixed-tick schedule differs | The same frame ran a different number of fixed ticks; check `FixedUpdate` order and script-mode physics |
| `status: diverged`, `missing_provider_ids` non-empty | A provider registered at record time was not registered at replay | Register the same set of providers before replay |
| `status: diverged`, `extra_provider_ids` non-empty | An extra provider registered at replay | Remove the extra registration |
| `status: error` with console errors | A `Debug.LogError` or exception during replay | Read the editor log; the game code may rely on non-deterministic state |
| `ReplayStateException` | Provider `WriteState` threw or wrote NaN | Fix the provider implementation |
| `environment: differs`, `unity_version`, `package_versions` or `package_lock` in `environment_diff` | Unity or packages changed since the recording | Replay still ran. Re-record on the current setup, or restore the old one |
| `environment: differs`, `scene_guid` or `project_id` | The scene or project is not the one recorded | Replay still ran. Restore the content or re-record |
| `environment: differs`, `os` or `cpu` | Recorded on a different machine or OS | Replay still ran, but the guarantee is same-environment. Replay on the recording machine |
| No markers found near divergence | Markers not written by game code | Add `ReplaySession.Mark("event", dataJson)` at key moments for diagnostic context |

## Capture/render failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `replay_media.py doctor` exits 3 | ffmpeg not found | `brew install ffmpeg`, or set `TRAILER_FFMPEG` environment variable |
| `MISSING: libx264` | ffmpeg without x264 encoder | `brew install ffmpeg` (the standard formula includes it) |
| Render produces black frames | No graphics device in the batch Editor | Use a graphics-enabled batch run (not `-nographics`) |
| Render skips frames or freezes | Async frame-write can't keep up at 60 fps | Reduce fps, dimensions, or recording length |
| Recorder not available | `backend:recorder` requested but `com.unity.recorder` not installed | Use `backend:png` (the default) or install the Recorder yourself (never automatic) |
| `bad_capture_size` | Width or height is odd, under 16 or over 1920/1080 | Use even values (e.g. 1280×720) |
| `bad_capture_range` | Range longer than `capture_max_seconds` (120), or a GIF longer than `gif_max_seconds` (8) | Shorten the range |
| Output smaller or shorter than asked | Export trims video to 1920×1080, 60 fps, 120 s and GIF to 480 wide, 15 fps, 8 s | The trims are reported; reduce the request to avoid them |
| Output labelled unverified | Divergence detected during render replay | The replay produced different hashes; the output is kept for diagnostics but not verified |
| Frames missing from `capture/frames/` after an export | They are deleted after a successful export | Expected. A failed export keeps them |

## L3 evidence failures

| Symptom | Likely cause | Fix |
|---|---|---|
| No replay-verified candidate for AC | Evidence row has wrong `kind`, not `tool`-observed, or not scoped to the AC | Use `subjects=["M1-S02-AC1"]` on the verify op |
| Report status is not `pass` | Replay diverged or had console errors | Check the report for the divergence cause and fix it |
| `frames.expected != frames.compared` | Replay stopped before consuming all recorded frames; the report is `error` | Check the Unity log for early termination |
| `log_sha256` or `replay_sha256` missing | Evidence row missing immutable digests | Re-run the verify op and ensure it completes fully |
| `console.errors > 0` | Game logged errors during replay | Fix the errors or suppress expected ones |

## General

| Symptom | Likely cause | Fix |
|---|---|---|
| `ReplayFormatError` on read | Corrupted archive, CRC mismatch, or decompression bomb | Re-record the run; archives are never modified after writing |
| Archive too large | Archive over `[unity.replay] max_archive_mb` (512; the reader also caps it at 512 MiB) | Reduce recording duration |
| `warning: Logs/harness/replay/ is N MiB` | Output exceeds `warn_total_mb` (2048). Shown by `replay_status` and in an export result | Delete old runs yourself; nothing is deleted automatically |
| Package doesn't compile | Unity version < 6000.3, or an older Input System pin | Upgrade to the pinned versions (existing manifest pins are not changed by install) |
