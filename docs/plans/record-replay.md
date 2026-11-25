# Deterministic record/replay implementation plan

Scope: reproduce instrumented sessions on the same Unity build, platform and project content; export real gameplay GIF/video on request. This is checkpoint-verified repeatability, not cross-platform lockstep or automatic serialization of arbitrary games. Bug-to-test, visual regression and softlock diagnosis remain later work. Never access the user's other projects. Local Unity runs require the user's OK and a disposable fixture.

## Reuse and delivery boundary

Based on `.agent-runs/rr/inventory_codex.md`, README and GUIDE, and the five relevant skills' instructions, references and templates:

| Existing implementation | Planned reuse |
|---|---|
| `skills/architecture-patterns/templates/Runtime/Roguelike/SeededRng.cs:14` | Preserve RNG algorithm and golden vectors; cache named streams in the new facade. |
| `skills/play-verify/templates/Harness.Verify/{Runtime,InputSystem,Tests/PlayMode}` | Probe/reset conventions, queued virtual input, scene-loading tests; do not run ScriptedInput concurrently with replay. |
| `skills/trailer-maker/templates/Harness.Trailer/Editor/TrailerCapture.cs:432` and `scripts/trailer_edl.py:1166` | Recorder settings/lifecycle and palette GIF exporter; extract small shared helpers instead of duplicating trailer orchestration. |
| `backend/gamedevworkstation/features/{unity_tool,unity_bridge,unity_cli}.py` | Existing tool, route selection, permissions, project mutex, jobs, timeout and cancellation. |
| `features/{media_out,gallery,ladder}.py`, `items.py:221` | Artifact/media indexing and gallery; explicitly extend L3 evaluation. |

All backend paths below are under `backend/gamedevworkstation/`; `P` means `skills/replay/templates/com.gdw.replay/`. This change adds no model calls; any future narration uses the existing provider/effort gate. Keep `skills/delegation/SKILL.md` byte-identical.

## Unity package and determinism contract

Ship embedded package `com.gdw.replay` version `0.1.0`, Unity minimum `6000.3`, Input System dependency `1.20.1`; record resolved patch versions. Install on request into `<project>/Packages/com.gdw.replay`, using `features/replay_install.py::install_replay_package()` modeled on `unity_harness.install_harness`: inventory hashes, fixed meta GUIDs, preview, refuse modified targets or dependency downgrades. Package resolution/install changes require existing setup consent. Tests require Test Framework `1.6.0` and package `testables`; Recorder `5.1.x` is optional and version-defined in a separate Editor assembly.

Namespace `Gdw.Replay`; asmdefs `Gdw.Replay.Runtime`, `Gdw.Replay.InputSystem`, `Gdw.Replay.Editor`, and separate test assemblies; release-player recording is disabled unless explicitly opted in.

| Files/classes in P | Responsibilities |
|---|---|
| `Runtime/GdwRandom.cs`, `SeededRng.cs` | `GdwRandom.Reset(uint seed)`, `Stream(string name)`, `ExportStates()`; reuse xorshift32/FNV stream derivation and count draws. |
| `Runtime/ReplaySession.cs`, `ReplayClock.cs`, `ReplayLoop.cs` | `BeginRecord(ReplayOptions)`, `BeginReplay(string path)`, `Stop()`, `Mark(string label)`; bootstrap, tick phases, teardown. |
| `InputSystem/InputTraceAdapter.cs` | `StartCapture()`, `StartReplay()`, `Dispose()`; trace persistence, isolation, device/action pairing. |
| `Runtime/ReplayRegistry.cs`, `ReplayIdentity.cs`, `StateWriter.cs` | `Register(string id, IReplayStateProvider provider)`; provider `WriteState(StateWriter writer)`; canonical state hashes. |
| `Runtime/ReplayArchive.cs`, `ReplayContracts.cs` | Versioned archive writer/reader and request/report DTOs. |
| `Editor/ReplayCommands.cs`, `Tests/PlayMode/ReplayVerificationTests.cs` | Live commands and generic replay test. |

Route gameplay randomness explicitly to cached `GdwRandom.Stream("combat")` etc. Audit `UnityEngine.Random`, aliases and `new System.Random`; never silently rewrite third-party code. Transitional Unity random support calls `Random.InitState(seed)` before scene initialization and checkpoints `Random.state`, with exact-version limitations. Seeded System.Random still depends on runtime/call order; replace or provide an explicit state adapter. Unrouted sources fail strict readiness. Cosmetic RNG uses separate streams.

Record and replay use the same test-mode bootstrap before target-scene Awake: reset statics (`SubsystemRegistration`), establish isolated initial save/config state, seed RNG, load scene, wait for explicit readiness, write initial checkpoint. V1 starts from scene reset; reject mid-session recording without a game-supplied snapshot/reset adapter. Loading must not allow gameplay to advance before readiness.

`ReplayLoop` installs/restores explicit PlayerLoop hooks: frame boundary/manual input update → Unity FixedUpdate callbacks and physics → Update/LateUpdate → post-LateUpdate checkpoint → optional capture. Set `Time.fixedDeltaTime` and `Time.captureDeltaTime` to the configured dt (default `1/60f`) in both modes; `captureFramerate=60` is the reciprocal alternative, not another clock. Record actual fixed-tick counts per frame and assert the schedule. Preserve/restore prior time, input, physics and loop settings on success, error, cancellation, reload and PlayMode exit. [captureDeltaTime does not fix unscaledTime](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Time-captureDeltaTime.html).

Use `Physics.simulationMode=SimulationMode.Script` and `Physics2D.simulationMode=SimulationMode2D.Script`; simulate each loaded physics scene once per scheduled fixed tick, after gameplay FixedUpdate, with fixed dt. Avoid double simulation. [Simulate does not invoke FixedUpdate](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Physics.Simulate.html); [2D simulation mode](https://docs.unity3d.com/6000.3/Documentation/ScriptReference/Physics2D-simulationMode.html) needs equivalent handling. Stable creation/callback order matters; PhysX/Box2D floats offer no cross-CPU/version guarantee. Unsupported custom physics loops fail readiness.

Timers, HitStop's real-time waits, unscaled effects, asynchronous loads/network, task/job completion, unordered iteration and coroutine resume order can diverge despite fixed dt. Provide `ReplayClock.Tick/Delta/UnscaledTime` for opted-in code; buffer external results at recorded tick barriers or reject them. Do not promise deterministic arbitrary MonoBehaviour ordering. V1 rejects runtime timeScale changes without a tick-aware adapter. Perf measurements require normal clocks in a separate perf-pass run.

### Input and hashes

Use [InputEventTrace](https://docs.unity3d.com/Packages/com.unity.inputsystem@1.20/api/UnityEngine.InputSystem.LowLevel.InputEventTrace.html), `recordFrameMarkers=true`, device filtering, `Enable/Disable`, `WriteTo/LoadFrom`; learn from Unity's [InputRecorder sample](https://github.com/Unity-Technologies/InputSystem/tree/develop/Assets/Samples/InputRecorder), without importing sample UI. Bound memory and stop before buffer wrap; overflow invalidates verification.

Replay with `trace.Replay().WithAllDevicesMappedToNewInstances().PlayAllFramesOneByOne()`; [ReplayController feeds one recorded frame per input update](https://docs.unity3d.com/Packages/com.unity.inputsystem@1.20/api/UnityEngine.InputSystem.LowLevel.InputEventTrace.ReplayController.html). Set manual input processing and issue exactly one controlled update per replay frame in both modes; filter Editor/BeforeRender updates. Restore settings and dispose traces/controllers/devices. Reset devices and capture initial states, pair PlayerInput/InputUser with virtual devices, suppress physical gameplay input, validate layouts/bindings. No legacy Input Manager fallback: fail explicitly, including mixed projects whose gameplay reads legacy input. Timer-based interactions need tick-aware adapters because replay retimestamps events; reject unsupported Hold/Tap/custom timeout interactions in strict v1. Exact update ordering, focus behavior and pairing require fixture validation on pinned `1.20.1`.

Hash every frame plus initial state: registered transforms (position/quaternion/scale, active state), rigidbody pose/linear/angular velocity/sleep state, scene IDs, RNG streams/draw counts and user providers (HP, inventory, objectives, timers). Require at least one gameplay provider. Stable authored GUIDs and deterministic spawn IDs replace instance IDs. Sort IDs ordinally; hash length-prefixed UTF-8 IDs and canonical little-endian typed bytes using SHA-256; preserve IEEE float bits, reject NaNs, never use GetHashCode or locale JSON. Store aggregate and per-provider hashes. Missing/extra providers, frames or ticks fail; unregistered state and pixels are outside coverage.

## `.gdwreplay` v1 format

ZIP container, UTF-8 JSON/JSONL plus native input trace; staged in a unique run directory, finalized atomically, never overwrite a baseline.

| Member | Required fields |
|---|---|
| `header.json` | `format:"gdwreplay", major:1, minor:0, run_id, created_utc`; Unity version, OS/CPU/scripting backend; project ID/name/content SHA-256 (including dirty inputs), scene GUID/path/content digest, uint seed, rational `fixed_dt:{num:1,den:60}`, render dt, package versions/lock digest, input settings/action/layout digests, device descriptions/layout/state formats, provider schemas, reset-adapter ID/initial-state digest, hash algorithm, coverage/unsupported features. |
| `input.inputtrace` | InputEventTrace binary, ordered events and update markers; require matching Input System version/native trace format. |
| `frames.jsonl` | Initial `frame:-1`, then contiguous zero-based frames: `tick`, `fixed_ticks`, `input_update`, `event_start`, `event_count`, `hash`, `providers:{id:hash}`. Event ordinals refer to the native trace. |
| `markers.jsonl` | `frame,tick,label,data` (bounded JSON); diagnostic markers never execute code. |
| `manifest.json` | Payload byte counts/SHA-256, total frames/ticks/events, `complete:true`, console counts. Missing final manifest means incomplete. |

Unknown major/required features fail; minor optional fields may be ignored. Strict verification rejects environment/content mismatches as `incompatible`, not gameplay divergence. Readers reject traversal/symlinks, duplicate members, oversized entries, checksum failures and decompression bombs without general extraction. At 100 events/s × 64–256 bytes: roughly 0.4–1.5 MB/min input; ten provider hashes plus aggregate roughly 3–5 MB/min checkpoints before compression. High-rate mouse/device streams scale upward; measure actual sizes.

## Execution, backend and evidence

`ReplayVerificationTests.LogMatchesCheckpoints` is one `[UnityTest]`: read `request.json`, validate compatibility, bootstrap/load scene, replay to recorded end, compare every checkpoint, assert zero unexpected console errors, always restore state. `Editor/ReplayCommands.Start(string requestPath)`, `Status()`, `Cancel()` persist job identity through domain reload; MCP uses fixed `execute_code`, CLI live uses existing eval approval (or discovered Pipeline command). Poll structured status/report, not chat text.

Default batch verification reuses `UnityBridge.run_tests`/CLI argv builders, with a per-job request passed through a new validated `-gdwReplayRequest` argument:

`unity test <fixture> --mode PlayMode --filter Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints --output <run>/results.xml --timeout 900 --format json -- -gdwReplayRequest <run>/request.json`

Raw fallback: `Unity -batchmode -projectPath <fixture> -runTests -testPlatform PlayMode -testFilter Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints -testResults <run>/results.xml -gdwReplayRequest <run>/request.json -logFile <run>/editor.log`; watchdog, never `-quit`. Existing wrappers deliberately omit `-nographics` for PlayMode: preserve that default. An independently validated logic-only raw runner may add it; capture always requires graphics. Never launch batch against an editor-held project or close somebody's Editor automatically.

Extend existing `unity` tool with ops `replay_install`, `record`, `replay`, `replay_verify`, `replay_render`; keep `action=start|stop|status`, add typed `run_id`, `replay_path`, `seed`, `fixed_dt`, `capture` (formats/backend/range/size/fps), `subjects`. `features/replay.py::run_replay_op()` shares service logic with REST: `POST /api/sessions/{sid}/replays/record`, `POST .../{run_id}/stop`, `GET .../{run_id}`, `POST .../replays/{replay|verify|render}`. Register module in `routes.py`; asynchronous mutations return `202 {job_id,run_id,status_url}`. Enforce session roots, bounded args and project/job ownership; no caller-controlled executable/method paths. Recording is live only. Record/replay/render obey change permissions and Plan-only refusal; verify follows existing test consent only when capture is absent.

Freeze `ReplayRequest` v1: `op`, optional `run_id/replay_path/scene`, uint32 `seed`, positive rational `fixed_dt`, string-array `subjects`, nullable `capture:{formats:[mp4|gif],backend:auto|recorder|png,start_frame:int,end_frame_exclusive:int,width:int,height:int,fps:int}`. Paths are project-relative; render fps cannot change simulation dt. Resolve requests to immutable JSON before launch; live tests discover that job's request through ReplayCommands, batch through the CLI flag.

`features/replay_format.py::read_replay()/compare_checkpoints()` returns `report.json`: schema version, run/log/content digests, route, status (`pass|diverged|incompatible|error|cancelled`), frames compared, console counts, `first_divergent_frame/tick`, `provider_id`, expected/actual hashes, missing IDs, nearby markers and artifact paths. Transport failure or truncated input never passes. Index archive/report via `items.add_file(kind="artifact")`; media separately.

Protocol: `[HARNESS] REPLAY {single-line JSON: v,run_id,event,status,frame,report}` for start/progress/divergence/done, followed by existing `[HARNESS] REPORT <path>` and script `RESULT: OK|FAIL`. Validate matching job, files, digests and NUnit XML; printed PASS alone is insufficient.

L3: retain `headless` AC type with `test:Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints`; extend `ladder.py::_test_candidates/_ac_level/_l3` to require scoped `detail.kind="replay_verified"` for that test, matching immutable log/report digests, fresh content, complete frames and clean console. Record through `record_evidence(... observed="tool", subjects=...)`. Passing only proves the stated repeatability AC; retain existing screenshot requirements for visual stories. Custom evidence rows currently do not satisfy L3 automatically.

Add `[unity.replay]` defaults in `config.py`/`default_config.toml`: `fixed_dt=0.016666667`, `max_seconds=600`, `max_trace_mb=256`, `max_archive_mb=512`, `capture_max_seconds=120`, `gif_max_seconds=8`, `gif_fps=15`, `gif_width=480`; use existing Unity timeout keys. Canonicalize default dt to 1/60; record overrides exactly.

## GIF/video on request

“Make a GIF of this run” resolves the session's selected/latest complete recording to `unity(op="replay_render", run_id=..., capture={formats:["mp4","gif"]})`; multiple ambiguous runs require selection. `replay` can take the same capture object. Replay from reset through the requested range, comparing hashes throughout; divergence labels the output unverified and retains diagnostics.

Preferred GUI backend: extract `TrailerRecorderSession` from TrailerCapture's existing Recorder lifecycle into its Editor template; `P/Editor/ReplayCapture.cs` calls it by reflection (no mandatory trailer assembly dependency). Offer missing helper installation through the same setup flow. Coordinate start at replay frame zero and stop after the last requested frame, without trailer warmup or scene reload. [RecorderController](https://docs.unity3d.com/Packages/com.unity.recorder@5.1/api/UnityEditor.Recorder.RecorderController.html) requires PrepareRecording then StartRecording in PlayMode. Keep constant simulation rate; downsample exports afterward. [Recorder cannot capture in batchmode; URP 2D requires Game View or RenderTexture](https://docs.unity3d.com/Packages/com.unity.recorder@5.1/manual/KnownIssues.html).

Fallback: per-frame PNGs via ScreenCapture in GUI/player, or explicit camera RenderTexture rendering in graphics-enabled batch (reuse HarnessCli screenshot/SRP pattern). Do not depend on batch WaitForEndOfFrame/Game View; overlay UI is unavailable on the camera path. Validate actual frame count and black frames. PNG path is silent; Recorder audio is optional Unity audio only, with existing FMOD/Wwise limitation.

Files: `<project>/Logs/harness/replay/<run_id>/{run.gdwreplay,request.json,report.json,capture/frames/,exports/<export_id>/run.mp4,run.gif,poster.png}`. Unique export IDs prevent overwrites; preserve intermediates on failure, no automatic deletion. Freeze simulation while synchronous frame writes finish; bounded async writers must backpressure, never drop frames.

`features/replay_media.py::build_export_steps()` reuses trailer `_trailer_common.find_ffmpeg/ffmpeg_caps/probe` and extracts its existing palette command helper. MP4: `ffmpeg -n -framerate 60 -i frame-%06d.png -c:v libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart run.mp4`. GIF: `ffmpeg -n -t 8 -i run.mp4 -filter_complex "fps=15,scale=480:-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" -loop 0 run.gif`. Enforce even dimensions, ≤1920×1080/60 fps/120 s video and ≤480 wide/15 fps/8 s GIF; report trimming. Execute argv without shell; doctor missing encoders first, verify with ffprobe.

Index completed media directly (the media_out observer currently watches run_command only), with run/log digest, range, capture route and verification status metadata. MP4 is media/video; GIF media/image, MIME image/gif. Reuse gallery's item queries/events and viewer; scripts also announce `ARTIFACT:`/`TRAILER_OUTPUT:` for manual invocation with existing deduplication. No new gallery UI required.

## Skill and verification

New `skills/replay/SKILL.md`: triggers “record this run”, “reproduce inputs”, “verify replay”, “GIF/video of this run”; outline readiness audit → consented install → reset/record → stop/index → verify → optional render → report/cleanup. Add format, determinism and troubleshooting references; script `scripts/replay_media.py` exposes `doctor|plan|export`. Unity-router links replay, play-verify retains acceptance evaluation, trailer-maker retains creative editing. Installation/reference edits belong to the implementation, not this planning task.

CI without Unity: golden archive parsing/version/limits/corruption; first divergence/provider/missing-frame comparisons; deterministic canonical-byte vectors shared with C#; ffmpeg argv/ranges; schemas, permissions, route/job fakes; install modified-file refusal; media/gallery deduplication; L3 stale/forged/unscoped evidence rejection. Follow `tests/conftest.py`: temporary GDW_HOME, GDW_NO_KEYCHAIN=1, disabled CLI search, fake processes/providers; never real app data/Keychain.

Create `tests/fixtures/unity/replay/` (not future `bench/project/`): minimal pinned manifest/ProjectSettings, bootstrap and generated primitive scene, keyboard-driven kinematic actor, seeded spawns, HP provider and PlayMode tests. Run copies under temporary directories only. Record 600 frames, reset and replay twice with identical hashes; new-process replay, no-input frames, held buttons/device pairing, reload-off reset, 2D/3D physics and failure teardown. Deliberately write a wall-clock value into a provider and inject a controlled frame-120 perturbation: comparator must catch both, with exact frame/provider for the controlled case. Graphics smoke: PNG and Recorder paths produce expected frame counts, playable MP4/GIF and gallery items. No Unity validation has been performed for this plan.

## Parallel implementation ownership

Freeze request/archive/report contracts first. D scaffolds the fixture immediately afterward; its final integration waits for B/C. Paths are disjoint. Commands below are future done checks; `U` means user OK required before any local Unity run.

| Task / owned files | Dependencies | Done check |
|---|---|---|
| A: `features/replay_format.py`, `skills/replay/references/*`, `tests/test_replay_format.py`, `tests/fixtures/replay/*` | Format/report contract above | `uv run pytest tests/test_replay_format.py` |
| B: P `package.json`, Runtime/*, Tests/EditMode/* and their asmdefs | A byte/schema vectors | U: `skills/headless-ops/scripts/unity.sh test editmode --project <scratch-fixture> --filter Gdw.Replay.Tests.RandomAndHashTests` |
| C: P InputSystem/*, Tests/InputSystem/* and their asmdefs | A, B tick contract | U: `skills/headless-ops/scripts/unity.sh test playmode --project <scratch-fixture> --filter Gdw.Replay.Tests.InputTraceTests` |
| D: P Editor/* except ReplayCapture.cs; P Tests/PlayMode/*; `tests/fixtures/unity/replay/*` | A–C; owns bootstrap/testables | U: `skills/headless-ops/scripts/unity.sh test playmode --project <scratch-fixture> --category Replay` |
| E: `features/replay.py`, `replay_install.py`, unity_tool/bridge/cli, routes.py, config.py, default_config.toml; `tests/test_replay_tool.py`, `test_replay_routes.py`, `test_replay_install.py` | A DTOs, D commands | `uv run pytest tests/test_replay_tool.py tests/test_replay_routes.py tests/test_replay_install.py` |
| F: `features/replay_media.py`, P Editor/ReplayCapture.cs, trailer-maker scripts/templates, replay scripts; `tests/test_replay_media.py` | A reports, B clock, D job lifecycle | `uv run pytest tests/test_replay_media.py tests/test_trailer_maker.py`; U: capture smoke |
| G: features/ladder.py; `tests/test_replay_ladder.py` | A report, E observed jobs | `uv run pytest tests/test_replay_ladder.py tests/test_ladder.py` |
| H: replay SKILL.md; unity-router/play-verify/trailer-maker SKILL.md; README/GUIDE | Frozen APIs A–G | `uv run pytest tests/test_unity_pack_scripts.py`; review tool examples |

Integration: `uv run pytest` after ownership merges; approved fixture smoke first, report results before broader runs. No commits, real-project migrations, process termination or destructive cleanup without separate authorization.

## Open decisions

1. **Guarantee:** recommend same environment/content plus registered-state repeatability; cross-platform deterministic physics would require another simulation architecture.
2. **Initial state and compatibility:** recommend scene-reset-only, Input System-only strict v1; adapters for saves, timed interactions, HitStop and legacy input are explicit follow-up work.
3. **Local validation:** approve disposable fixture runs on Unity 6000.3.21f1/CLI beta.13? Recommend the small logic smoke first, then graphics/Recorder after reporting results.
4. **Capture dependency/audio:** recommend optional Recorder GUI capture, silent PNG fallback and no automatic Recorder installation; preserve middleware-audio limitations.
5. **Retention/size:** recommend the stated bounded defaults and immutable outputs; defer pruning until a reviewed retention policy exists, because media can dominate disk usage.

## Decisions (final, 2026-11-18; these override "Open decisions" above)

1. **Guarantee:** never refuse on environment mismatch. Always replay and compare; when Unity version, OS/CPU, package or content digests differ, the report status keeps its gameplay meaning (`pass|diverged|error|cancelled`) and adds `environment: "matched"|"differs"` plus the list of differing fields. `incompatible` is only for format/major-version or missing-trace problems that make replay impossible.
2. **Scope v1:** Input System only; projects whose gameplay reads the legacy Input Manager get a clear readiness error naming the files/calls. Hold/Tap and other timed interactions are in v1 if the fixture proves they replay identically when the replay preserves recorded event timing; if not, strict v1 rejects them (as originally planned). Start point: scene reset/load, plus an `IReplaySnapshot` interface (capture/restore) a game may implement later; v1 ships the interface and uses it only if registered.
3. **Local validation:** approved. Run the full fixture suite (logic + capture) on Unity 6000.3.21f1 against copies of `tests/fixtures/unity/replay/` in temporary directories, before the release. Never touch the user's other projects.
4. **Capture:** the PNG-per-frame path is the default backend (`auto` = png); Unity Recorder is used only when `backend:"recorder"` is requested and the project already has `com.unity.recorder` (never installed automatically). MP4 is silent in v1.
5. **Retention:** keep `.gdwreplay`, reports and exports. After a successful export, delete only that export's own intermediate `capture/frames/` PNGs (files this feature created in its own run folder). `[unity.replay] warn_total_mb = 2048`: status/Settings warn when a project's `Logs/harness/replay/` exceeds it. No other automatic deletion.
