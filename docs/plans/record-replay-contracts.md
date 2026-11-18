# Record/replay frozen contracts v1

Design: `record-replay.md` (Decisions win). UTC RFC 3339; lowercase SHA-256 hex digests; canonical UTF-8 JSON (no NaN/Infinity); project-relative POSIX paths only.

## 1. ReplayRequest v1 (`gdw.replay.request/1`)

Stored as `request.json`; `request_digest` = SHA-256 of canonical JSON.

| field | contract |
|---|---|
| `schema` | const `gdw.replay.request/1` |
| `op` | `record`\|`replay`\|`verify`\|`render`; tool `replay_verify`→verify, `replay_render`→render |
| `run_id` | `^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$`; record default `rr_<16 hex>`, required otherwise |
| `replay_path` | project-relative `.gdwreplay`; default `Logs/harness/replay/<run_id>/run.gdwreplay`; not for record |
| `scene` | project-relative `Assets/...unity`; record default build index 0; others must equal `header.scene.path` |
| `seed` | uint32, record default 0; elsewhere optional, must equal `header.seed` else `incompatible` |
| `fixed_dt` | `{num:int,den:int}`, positive, default `{1,60}`, reduced, `den≤1000000`, `0.001≤value≤1.0`; render fps never changes it |
| `subjects` | string[], ≤32, each ≤128 chars, unique |
| `capture` | object\|null; required for render, optional otherwise |

`capture`: `formats` required, non-empty unique subset `mp4|gif`; `backend` `auto|recorder|png` default `auto` (=png, Decision 4); `start_frame` ≥0 default 0; `end_frame_exclusive` > start, default archive length; `width`/`height` 16–1920/16–1080 even, defaults 1280/720; `fps` 1–60 default 60.

## 2. ReplayReport v1 (`gdw.replay.report/1`)

| field | contract |
|---|---|
| `schema` | const `gdw.replay.report/1` |
| `run_id` | request |
| `request_digest`,`replay_sha256`,`header_sha256`,`log_sha256`,`content_sha256` | request, archive, header, editor log, project content |
| `route` | `mcp`\|`cli_live`\|`cli_batch`\|`raw_batch` |
| `status` | `pass`\|`diverged`\|`incompatible`\|`error`\|`cancelled` |
| `environment` | `matched`\|`differs` (Decision 1) |
| `environment_diff` | sorted unique subset: `unity_version`, `os`, `cpu`, `scripting_backend`, `project_id`, `project_content`, `scene_guid`, `scene_content`, `package_versions`, `package_lock`, `input_settings`, `action_assets`, `layout_digests`, `device_layouts`; `[]` when matched |
| `frames`,`ticks` | `{expected:int,compared:int}` |
| `first_divergent_frame`,`first_divergent_tick` | int\|null; `-1` = initial state, null = none |
| `provider_id` | string\|null |
| `expected_hash`,`actual_hash` | aggregate hashes at divergence, string\|null |
| `missing_provider_ids`,`extra_provider_ids` | sorted string[] |
| `nearby_markers` | `{frame,tick,label}[]`, ≤10, within ±5 frames |
| `console` | `{errors,warnings}`; `pass` needs zero errors |
| `artifacts` | `{archive,report,results_xml,editor_log,capture_dir,exports[]}` |
| `message` | ≤500 chars; timestamps `started_utc`,`ended_utc` |

Precedence `cancelled > incompatible > error > diverged > pass`. `pass` needs a complete manifest, contiguous full frames/ticks, identical provider sets, equal hashes, matching trace and zero console errors. `diverged` = complete replay with a mismatch; `error` = transport/timeout/protocol/truncation/console errors; `incompatible` only for format/major/required-feature/missing-trace. Environment differences never cause `incompatible`; hashes are compared.

## 3. `.gdwreplay` v1 members

ZIP; ≤64 entries; duplicate names, traversal, symlinks rejected; ≤512 MiB uncompressed, ≤256 MiB/member, header ≤1 MiB, ratio >200:1 rejected. Required: `header.json`, `input.inputtrace`, `frames.jsonl`, `markers.jsonl`, `manifest.json`; missing manifest = incomplete.

| `header.json` field | contract |
|---|---|
| `format`,`major`,`minor` | `gdwreplay`, 1, 0; major≠1 incompatible; later minors ignore unknown fields |
| `run_id`,`created_utc`,`tool_version` | version `0.1.0` |
| `unity` | `{version:"6000.3.21f1",revision,scripting_backend:"mono"|"il2cpp"}` |
| `os`,`cpu` | `{platform,version}`; `{model,architecture,cores}` |
| `project` | `{id,name,content_sha256,dirty}` |
| `scene` | `{guid,path,content_sha256}` |
| `seed` | uint32 |
| `fixed_dt`,`render_dt` | `{num,den}`, positive, reduced |
| `packages` | `{versions:{id:version},lock_sha256}` |
| `input` | `{settings_sha256,actions_sha256,layouts_sha256,system_version:"1.20.1"}` |
| `devices` | `[{description,layout,state_format_sha256}]`, trace order |
| `providers` | `[{id,schema_sha256,gameplay:bool}]`, sorted; ≥1 gameplay |
| `reset_adapter` | `{id,initial_state_sha256}`; v1 `scene-reset` unless snapshot |
| `state_hash` | `{algorithm:"sha256",encoding:"gdw-replay-state/1"}` |
| `features` | `{required:[],optional:[]}`; unknown required = incompatible |
| `coverage` | `{unsupported:[],notes}` |

`frames.jsonl`: `frame:-1` first, then contiguous 0-based. Line: `frame`, `tick`, `fixed_ticks`≥0, `input_update`, `event_start`, `event_count`≥0, `hash`, `providers:{id:hash}`; ≤8 KiB; event ordinals index the trace.

`markers.jsonl`: `{frame,tick,label,data}`; label ≤128 chars, canonical `data` ≤4 KiB, ≤10000; diagnostics only, never executed.

`manifest.json`: `{format:"gdwreplay-manifest",version:1,complete:true,frames,ticks,events,console:{errors,warnings},final_frame_hash,created_utc,tool_version,files:[{name,bytes,sha256}]}`; `files` covers the other four members.

`input.inputtrace`: Input System `InputEventTrace` binary, `recordFrameMarkers=true`, version equal to `header.input.system_version`.

## 4. Canonical state hash (`gdw-replay-state/1`)

Integers little-endian two's complement; duplicate field names error. Provider payload = `FIELD_COUNT:u32`, then fields sorted by name (ASCII ordinal): `NAME_LEN:u16` + UTF-8 name + `TAG:u8` + value. Tags: `0x01` BOOL(u8 0/1), `0x02` I32, `0x03` U32 (4), `0x04` I64, `0x05` U64 (8), `0x06` F32 (binary32 raw bits), `0x07` F64 (binary64 raw bits), `0x08` STRING (`LEN:u32`+UTF-8), `0x09` BLOB (`LEN:u32`+bytes), `0x0A` VEC3 (3×F32), `0x0B` QUAT (4×F32 x,y,z,w). Bits preserved (−0≠+0); **NaN rejected** by writers; ±Inf hashed. Names `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`; provider IDs `^[a-z][a-z0-9_.-]{0,63}$`; `unity.` is framework-reserved.

Provider block = `ID_LEN:u32` + id + `PAYLOAD_LEN:u32` + payload. Canonical = `"GDWSTATE"` + `VERSION:u16=1` + `COUNT:u32` + blocks in ID order. `state_hash=SHA-256(canonical)`; `provider_hash=SHA-256(block)`. Frames carry the initial provider set.

Framework providers (`<sid>` = identity, sorted): `unity.transforms` `count:U32`, `<sid>.position:VEC3`, `.rotation:QUAT`, `.scale:VEC3`, `.active:BOOL`; `unity.physics` `count:U32`, `<sid>.position:VEC3`, `.rotation:QUAT`, `.linear_velocity:VEC3`, `.angular_velocity:VEC3`, `.sleeping:BOOL`; `unity.physics2d` `count:U32`, `<sid>.position:VEC3` (z=0), `.rotation:F32`, `.linear_velocity:VEC3` (z=0), `.angular_velocity:F32`, `.sleeping:BOOL`; `unity.rng` `seed:U32`, `stream.<name>.state:U32`, `stream.<name>.draws:U64`; `unity.scene` `guid:STRING`, `path:STRING`, `loaded:U32`; `unity.input` `events:U64`, `frames:U64`, `trace_sha256:STRING`; `unity.snapshot` `adapter_id:STRING` plus game fields prefixed `snapshot.` when registered.

```python
import hashlib, struct
def u32(n): return struct.pack("<I", n)
def payload(f):                       # f: name -> (tag, value bytes)
    out=[u32(len(f))]
    for n in sorted(f):
        t,v=f[n]; b=n.encode(); out+=[struct.pack("<H",len(b)),b,bytes([t]),v]
    return b"".join(out)
def state_hash(p):                    # p: provider id -> payload
    ids=sorted(p); out=[b"GDWSTATE",struct.pack("<H",1),u32(len(ids))]
    for i in ids:
        b=i.encode(); out+=[u32(len(b)),b,u32(len(p[i])),p[i]]
    return hashlib.sha256(b"".join(out)).hexdigest()
```

*V1* `game.hp`: `alive:BOOL=true`, `hp:I32=100`. Canonical hex `47445753544154450100010000000700000067616d652e687016000000020000000500616c6976650101020068700264000000`; **hash `542d2da118d9b08e78cfa33f4a7e426ad5c742bfda979db68f7bb082282b2dfb`** (provider `dcc1e59d...`).
*V2* `game.state`: `blob:BLOB=00 ff 10`, `delta:I64=-2`, `f32:F32=1.5`, `f64:F64=3.25`, `name:STRING="héllo"`, `pos:VEC3=(1,-2.5,0)`, `q:QUAT=(0,0,0,1)`, `ticks:U64=2^64−1`. **hash `7d362c286a4b10523b3940a4c812363b8299c490579bdd0d4796e8ec833bc211`**.
*V3* `game.inventory`: `count:U32=2`, `negzero:F32=-0.0`, `slot.0:STRING="sword"`, `slot.1:STRING="potion"`; `unity.rng`: `seed:U32=12345`, `stream.combat.draws:U64=0`, `stream.combat.state:U32=0x6E624EB7`, `stream.loot.draws:U64=3`, `stream.loot.state:U32=0xDEADBEEF`. **hash `7903c8fb91600773d718253be4deb42c43887c8b8080560b53aa31133b568e1f`**.

## 5. `[HARNESS] REPLAY` line

`[HARNESS] REPLAY ` + one-line canonical JSON ≤8 KiB, newline, UTF-8. Required `v:1`, `run_id`, `event` (`start|progress|divergence|done`), `status` (`recording|replaying|pass|diverged|incompatible|error|cancelled`). Optional `frame:int`, `report:path`, `message:≤300 chars`. `start` once; `progress` ≤1/s and every 600th frame; `divergence` at first mismatch; `done` once with report status. A different `run_id` is a protocol failure; then `[HARNESS] REPORT <path>` and `RESULT: OK|FAIL`.

## 6. Python interfaces

`features/replay_format.py`

```python
class ReplayFormatError(ValueError):  # malformed/unsupported/incomplete/oversized; names member/frame
    def __init__(self, message: str, *, member: str | None = None, frame: int | None = None) -> None: ...
@dataclass(frozen=True) class ReplayArchive:
    path: Path; sha256: str; header: dict; frames: list[dict]; markers: list[dict]
    manifest: dict; input_trace_size: int; uncompressed_size: int
@dataclass(frozen=True) class CheckpointComparison:
    frames_compared: int; ticks_compared: int; first_divergent_frame: int | None
    first_divergent_tick: int | None; provider_id: str | None; expected_hash: str | None
    actual_hash: str | None; missing_provider_ids: tuple[str, ...]
    extra_provider_ids: tuple[str, ...]; nearby_markers: tuple[dict, ...]
def read_replay(path: str | Path, *, max_bytes: int = MAX_ARCHIVE_BYTES) -> ReplayArchive: ...
def write_replay(path: str | Path, *, header: dict, frames: Iterable[dict],
                 markers: Iterable[dict] = (), input_trace: bytes = b"",
                 console: dict | None = None, overwrite: bool = False) -> ReplayArchive: ...
def compare_checkpoints(expected: Iterable[dict], actual: Iterable[dict], *,
                        markers: Iterable[dict] = ()) -> CheckpointComparison: ...
def provider_hash(provider_id: str, payload: bytes) -> str: ...
def state_hash(providers: Mapping[str, bytes]) -> str: ...
MAX_ARCHIVE_BYTES=512*1024*1024; MAX_MEMBER_BYTES=256*1024*1024; MAX_HEADER_BYTES=1024*1024
MAX_LINE_BYTES=8192; MAX_FRAMES=1_000_000; MAX_MARKERS=10_000; MAX_ENTRIES=64
MAX_COMPRESSION_RATIO=200; STATE_MAGIC=b"GDWSTATE"; STATE_ENCODING_VERSION=1
HASH_ALGORITHM="sha256"
```

`read_replay` raises `ReplayFormatError` on any §3 violation. `write_replay` (tests) is atomic and refuses an existing path unless `overwrite=True`. `compare_checkpoints` returns mismatches; it raises only for non-contiguous/duplicate frames or schema mismatch.

`features/replay.py`

```python
REPLAY_OPS = ("record", "stop", "status", "replay", "verify", "render")
class ReplayOpError(Exception):  # code, message, http_status, job_id
    def __init__(self, code: str, message: str, *, http_status: int = 400,
                 job_id: str | None = None) -> None: ...
async def run_replay_op(app: "AppState", session: dict, op: str, args: dict,
                        *, cancel: asyncio.Event | None = None) -> "ToolOutput": ...
def register(app_: "FastAPI", api: "APIRouter", S: "AppState") -> None: ...  # no-op in W0
```

Codes: `bad_request`, `forbidden`, `not_found`, `conflict`, `unsupported`, `install_required`, `job_failed`. Validates args, session roots, ownership and permissions; returns `ToolOutput.data={job_id,run_id,status,status_url?,report?,artifacts?}`; mutations are 202. `register()` is a no-op until E wires `/api/sessions/{sid}/replays/...`.

`features/replay_install.py`

```python
PACKAGE_NAME="com.gdw.replay"; PACKAGE_VERSION="0.1.0"; PACKAGE_DIR="Packages/com.gdw.replay"
def install_replay_package(project: str | Path, *, allow_upgrade: bool = False,
                           dry_run: bool = False) -> dict: ...
def replay_package_status(project: str | Path) -> dict: ...
```

Returns `{ok,status,written,message,package}`; status `installed|upgraded|up_to_date|modified|needs_upgrade_consent|error`; never overwrites edited files or downgrades dependencies; `dry_run` only plans; raises `ValueError` for a non-Unity project.

`features/replay_media.py`

```python
class ReplayMediaError(ValueError): ...
@dataclass(frozen=True) class ExportPlan:
    frames_dir: Path; out_dir: Path; steps: tuple[tuple[str, ...], ...]
    outputs: tuple[Path, ...]; trims: tuple[dict, ...]; fps: int; gif_fps: int
def build_export_steps(frames_dir: str | Path, out_dir: str | Path, capture: Mapping[str, Any], *,
                       ffmpeg: str | None = None, ffprobe: str | None = None,
                       caps: Mapping[str, Any] | None = None) -> ExportPlan: ...
def doctor(ffmpeg: str | None = None) -> dict: ...
```

`build_export_steps` emits shell-free MP4-then-GIF argv, validates ranges/dimensions/fps, and reuses `_trailer_common` ffmpeg/caps/probe plus the palette helper. `doctor` returns `{ok,ffmpeg,ffprobe,missing,caps}`.

## 7. `unity` tool additions

`OPS` gains `replay_install`, `record`, `replay`, `replay_verify`, `replay_render`; `action=start|stop|status` stays for `play`. Merge into `SCHEMA`:

```json
{"run_id":{"type":"string","pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$"},
 "replay_path":{"type":"string"},
 "seed":{"type":"integer","minimum":0,"maximum":4294967295},
 "fixed_dt":{"type":"number","exclusiveMinimum":0,"maximum":1},
 "subjects":{"type":"array","items":{"type":"string"},"maxItems":32},
 "capture":{"type":"object","additionalProperties":false,"required":["formats"],
  "properties":{"formats":{"type":"array","items":{"type":"string","enum":["mp4","gif"]},"minItems":1},
   "backend":{"type":"string","enum":["auto","recorder","png"],"default":"auto"},
   "start_frame":{"type":"integer","minimum":0},"end_frame_exclusive":{"type":"integer","minimum":1},
   "width":{"type":"integer","minimum":16,"maximum":1920},
   "height":{"type":"integer","minimum":16,"maximum":1080},
   "fps":{"type":"integer","minimum":1,"maximum":60}}}}
```

Permissions: install needs setup consent; record is live-only; verify follows test consent when capture is absent; render needs change permission; no caller-controlled executable/method paths.

## 8. C# `com.gdw.replay` 0.1.0 public API

Namespace `Gdw.Replay` (tests `Gdw.Replay.Tests`); assemblies `Gdw.Replay.{Runtime,InputSystem,Editor}` plus test asmdefs. All public.

```csharp
interface IReplayStateProvider { string Id { get; } void WriteState(StateWriter writer); }
interface IReplaySnapshot { void Capture(StateWriter writer); void Restore(); }

sealed class StateWriter {
  int FieldCount { get; }
  void WriteBool(string name, bool value); void WriteInt32(string name, int value);
  void WriteUInt32(string name, uint value); void WriteInt64(string name, long value);
  void WriteUInt64(string name, ulong value);
  void WriteFloat(string name, float value); void WriteDouble(string name, double value);
  void WriteString(string name, string value);
  void WriteBytes(string name, ReadOnlySpan<byte> value);
  void WriteVector3(string name, Vector3 value); void WriteQuaternion(string name, Quaternion value);
  byte[] ToBytes();
}
readonly struct ReplayHashes { string Aggregate { get; } IReadOnlyDictionary<string,string> Providers { get; } }
sealed class ReplayRegistry {
  static ReplayRegistry Instance { get; }
  void Register(string id, IReplayStateProvider provider); void Unregister(string id);
  bool IsRegistered(string id); IReadOnlyList<string> Ids { get; }
  string ComputeHash(string id); ReplayHashes ComputeAll();  // aggregate + per-provider map
  void RegisterSnapshot(string id, IReplaySnapshot snapshot); bool RestoreSnapshot(string id);
}
static class ReplayIdentity {                       // "authored.<guid>", "spawn.<id>"
  static string Authored(Guid guid); static string Spawn(string spawnId);
}
sealed class GdwRandomStream {                      // mirrors SeededRng's public methods
  uint State { get; } ulong Draws { get; } SeededRng Rng { get; }
}
static class GdwRandom {
  static uint Seed { get; } static IReadOnlyList<string> StreamNames { get; }
  static void Reset(uint seed);
  static GdwRandomStream Stream(string name);       // cached; seed ^ FNV1a(name)
  static GdwRandomState ExportStates(); static void ImportStates(GdwRandomState state);
}
[Serializable] sealed class GdwRandomState { uint Seed; string[] Names; uint[] States; ulong[] Draws; }

[Serializable] sealed class ReplayOptions { uint Seed; float FixedDeltaTime = 1f/60f; string ScenePath, RunId; bool Strict = true; }
sealed class ReplaySession : MonoBehaviour {
  static ReplaySession Current { get; } string State { get; }
  ReplayOptions Options { get; } event Action<ReplayResult> Finished;
  static ReplaySession BeginRecord(ReplayOptions options);
  static ReplaySession BeginReplay(string path);
  void Mark(string label, string dataJson = null); void Stop();
}
static class ReplayClock {
  static double Tick { get; } static float Delta { get; }
  static double UnscaledTime { get; } static float FixedDelta { get; }
}
sealed class InputTraceAdapter : IDisposable, IReplayStateProvider {
  InputTraceAdapter(string runDirectory, int maxTraceMb = 256);
  string Id { get; }
  long EventCount { get; } bool Overflowed { get; }
  void StartCapture(); void StartReplay();
  void WriteState(StateWriter writer); void Dispose();
}
sealed class ReplayArchive {
  static void Write(string path, ReplayHeader header, IEnumerable<ReplayFrame> frames,
                    IEnumerable<ReplayMarker> markers, byte[] inputTrace, ReplayManifest manifest);
  static ReplayArchive Read(string path, int maxBytes = 536870912);
}
static class ReplayContracts {                      // DTOs, invariant JSON
  static ReplayRequest ReadRequest(string path); static ReplayReport ReadReport(string path);
}
sealed class ReplayCompatibilityException : Exception { }
sealed class ReplayStateException : Exception { }

namespace Gdw.Replay.Editor {
  static class ReplayCommands {
    static string Start(string requestPath); static string Status();
    static string Cancel(); static void RunFromCli();
  }
}
```

`ReplayLoop` (internal): PlayerLoop hooks, one input update per replay frame, fixed-tick script-mode physics, post-LateUpdate checkpoint; restores time/input/physics/loop settings on every exit. `Editor/ReplayCapture.cs` belongs to F.

## 9. Ownership (path corrections applied)

| Task / files |
|---|
| A `backend/gamedevworkstation/features/replay_format.py`, `skills/replay/references/*`, `tests/test_replay_format.py`, `tests/fixtures/replay/*` |
| B package `{package.json,Runtime/*,Tests/EditMode/*}` + asmdefs |
| C package `InputSystem/*`, `Tests/InputSystem/*` + asmdefs |
| D package `Editor/*` except `ReplayCapture.cs`, `Tests/PlayMode/*`; `tests/fixtures/unity/replay/*` |
| E `features/{replay,replay_install}.py`, `unity_tool.py`, `unity_bridge.py`, `unity_cli.py`, `routes.py`, `config.py`, `default_config.toml`; `tests/test_replay_{tool,routes,install}.py` |
| F `features/replay_media.py`, `Editor/ReplayCapture.cs`, trailer-maker scripts/templates, replay scripts; `tests/test_replay_media.py` |
| G `features/ladder.py`; `tests/test_replay_ladder.py` |
| H `skills/replay/SKILL.md`, unity-router/play-verify/trailer-maker SKILL.md, README/GUIDE |

Dependencies: A←§1–4; B←A; C←A,B; D←A–C; E←A,D; F←A,B,D; G←A,E; H←A–G.

Corrections: `items.py`, `config.py` and `default_config.toml` live under `backend/gamedevworkstation/`; A's fixtures are `tests/fixtures/replay/` (D's Unity fixture separate); P is `skills/replay/templates/com.gdw.replay/`.

## 10. File layouts

P: `package.json`, `README.md`; `Runtime/{GdwRandom,SeededRng,ReplaySession,ReplayClock,ReplayLoop,ReplayRegistry,ReplayIdentity,StateWriter,ReplayArchive,ReplayContracts}.cs` + `Gdw.Replay.Runtime.asmdef`; `InputSystem/{InputTraceAdapter.cs,Gdw.Replay.InputSystem.asmdef}`; `Editor/{ReplayCommands.cs,ReplayCapture.cs,Gdw.Replay.Editor.asmdef}`; `Tests/{EditMode,InputSystem,PlayMode}/`, PlayMode holding `ReplayVerificationTests.cs`.

Fixture: `Packages/{manifest.json,packages-lock.json}`; `ProjectSettings/{ProjectVersion.txt,ProjectSettings.asset,EditorBuildSettings.asset,InputManager.asset,TimeManager.asset,Physics2DSettings.asset}`; `Assets/ReplayFixture/{Bootstrap.cs,SeededSpawner.cs,HpProvider.cs,ReplayFixture.asmdef,Generated.unity}` + metas; `Assets/Tests/PlayMode/{ReplayFixtureTests.cs,*.asmdef}`. Temporary copies only.
