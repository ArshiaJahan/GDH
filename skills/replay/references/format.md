# `.gdwreplay` v1 format and canonical state hashes

Frozen source of truth: `docs/plans/record-replay-contracts.md` §3–§4 and the final decisions in
`docs/plans/record-replay.md`. This page is the implementation reference for the Python reader,
writer and comparator in `backend/gamedevworkstation/features/replay_format.py`.

All JSON is canonical UTF-8: keys sorted, no insignificant whitespace, no `NaN`/`Infinity`,
no duplicate field names. Digests are lowercase SHA-256 hex. Paths inside the archive are
project-relative POSIX paths.

## Archive layout

A `.gdwreplay` is a ZIP file (never extracted). Required members:

| member | contents |
|---|---|
| `header.json` | one header object (§3) |
| `input.inputtrace` | Input System `InputEventTrace` binary, `recordFrameMarkers=true` |
| `frames.jsonl` | one checkpoint per line, `frame:-1` first then contiguous frames from 0 |
| `markers.jsonl` | zero or more `{frame,tick,label,data}` diagnostic rows |
| `manifest.json` | completeness, counts, console counts and the digests of the four others |

The reader accepts extra members, but every member is bounded and CRC-checked. Directory
entries are allowed only with a trailing `/` and zero bytes.

### Reader limits (reject with `ReplayFormatError`)

* archive file ≤ 512 MiB (`max_bytes` may lower it), uncompressed total ≤ 512 MiB
* ≤ 64 ZIP entries, ≤ 256 MiB per member, `header.json` ≤ 1 MiB, frames line ≤ 8 KiB
* compression ratio ≤ 200:1 per member; compressed size 0 with non-zero size is rejected
* no absolute names, `..`/`.`/empty path segments, backslashes, NUL, duplicates, symlinks or
  other special Unix file types
* required members missing, `manifest.complete` not `true`, or `manifest.json` absent =
  **incomplete**
* `header.major` other than 1, or a non-empty `header.features.required` = **incompatible**
* the backend also checks size and replay-time rules (`max_archive_mb`, and `scene`/`seed`
  matching the header) and reports those as `incompatible` in the report; a missing file is `error`
* manifest `files[]` byte counts and SHA-256 digests must match the members; the manifest's
  `final_frame_hash` must match the last frame row
* every frame's provider map must equal `header.providers[].id`; frame numbers are contiguous
* malformed/duplicate JSON fields, non-finite numbers, oversized marker `data` (> 4096 canonical
  bytes) and labels (> 128 chars) are rejected

Environment differences are deliberately **not** a read-time error. The reader never compares
the host with `header.os`/`header.cpu`/`header.unity`; replay and comparison proceed, and the
report records `environment: matched|differs` plus `environment_diff` (Decision 1). The
backend compares `unity_version`, `os`, `cpu`, `project_id`, `scene_guid`, `package_versions`
and `package_lock`, and only when the header filled the field. `differs` never changes the
status.

## `frames.jsonl`

Each line is a checkpoint:

```json
{"event_count":0,"event_start":0,"fixed_ticks":1,"frame":0,"hash":"<sha256>",
 "input_update":false,"providers":{"game.hp":"<sha256>"},"tick":1}
```

`hash` is the aggregate state hash; `providers` maps each header provider id to its per-provider
block hash. `event_start`/`event_count` are ordinals into `input.inputtrace`. `fixed_ticks` is
the number of fixed ticks advanced since the previous checkpoint. The first row is `frame:-1`
(the initial state). Frames are not compressed or embedded elsewhere.

## `markers.jsonl`

Diagnostics only, never executed. `label` ≤ 128 characters; `data` is canonical JSON ≤ 4 KiB
(or `null`/absent); at most 10 000 rows. Markers are reported within ±5 frames of a divergence.

## `manifest.json`

```json
{"format":"gdwreplay-manifest","version":1,"complete":true,
 "frames":2,"ticks":3,"events":0,
 "console":{"errors":0,"warnings":0},
 "final_frame_hash":"<sha256>","created_utc":"2026-01-02T03:04:05Z","tool_version":"0.1.0",
 "files":[{"name":"frames.jsonl","bytes":123,"sha256":"<sha256>"}, ...]}
```

`files` covers `header.json`, `input.inputtrace`, `frames.jsonl` and `markers.jsonl` (not the
manifest itself). The Python writer sets `frames` to the number of rows after the initial state,
`ticks` to the last tick + 1, and `events` to the largest `event_start + event_count`.

## Canonical state hash (`gdw-replay-state/1`)

Provider payload = `FIELD_COUNT:u32`, then fields sorted by name:

```
NAME_LEN:u16 | name (UTF-8) | TAG:u8 | value
```

All integers are little-endian. Tags: `0x01` BOOL(u8), `0x02` I32, `0x03` U32, `0x04` I64,
`0x05` U64, `0x06` F32 (raw binary32), `0x07` F64 (raw binary64), `0x08` STRING(u32 len + UTF-8),
`0x09` BLOB(u32 len + bytes), `0x0A` VEC3 (3×F32), `0x0B` QUAT (4×F32, x y z w).
Raw bits are preserved (`-0.0` and `+0.0` differ); writers reject NaN, ±Inf is hashed.
Field names: `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`; provider ids: `^[a-z][a-z0-9_.-]{0,63}$`;
`unity.` is reserved for framework providers.

Provider block = `ID_LEN:u32 | id | PAYLOAD_LEN:u32 | payload`.
Aggregate = `b"GDWSTATE" | VERSION:u16=1 | COUNT:u32 | blocks in id order`.
`provider_hash = SHA-256(block)`; `state_hash = SHA-256(aggregate)`.

Golden vectors (must match on every implementation, C# included):

| provider | canonical payload hex | aggregate hash |
|---|---|---|
| `game.hp` (`alive=true`, `hp=100`) | `020000000500616c6976650101020068700264000000` | `542d2da118d9b08e78cfa33f4a7e426ad5c742bfda979db68f7bb082282b2dfb` |
| `game.state` (blob `00ff10`, I64 −2, F32 1.5, F64 3.25, STRING `héllo`, VEC3 `(1,-2.5,0)`, QUAT `(0,0,0,1)`, U64 2⁶⁴−1) | — | `7d362c286a4b10523b3940a4c812363b8299c490579bdd0d4796e8ec833bc211` |
| `game.inventory` + `unity.rng` (V3 in the contracts) | — | `7903c8fb91600773d718253be4deb42c43887c8b8080560b53aa31133b568e1f` |

The V1 `game.hp` provider block hash starts `dcc1e59d`.

## Python surface

```python
read_replay(path, *, max_bytes=MAX_ARCHIVE_BYTES) -> ReplayArchive
write_replay(path, *, header, frames, markers=(), input_trace=b"", console=None,
             overwrite=False) -> ReplayArchive
compare_checkpoints(expected, actual, *, markers=()) -> CheckpointComparison
provider_hash(provider_id, payload) -> str
state_hash(providers) -> str
```

`write_replay` is test/fixture tooling: it builds the manifest, writes to a temporary file in the
target directory, validates the result with `read_replay`, then `os.replace`s it. It refuses an
existing path unless `overwrite=True`. Production archives are written by the Unity package.

`compare_checkpoints` compares rows by frame number, short-circuiting at the first divergence.
It reports the frame/tick, the earliest sorted differing provider id, the two aggregate hashes,
and the provider ids missing/extra at that frame. A frame present on only one side, a tick
mismatch, a provider-map difference or an aggregate-hash difference is a divergence;
`expected_hash`/`actual_hash` are `null` for the absent side, so a missing/extra frame surfaces
as the first divergence (the frozen `CheckpointComparison` has no separate frame lists).
It raises `ReplayFormatError` only for non-contiguous/duplicate frame rows or schema violations.
`frames_compared` counts the examined checkpoints including frame −1; `ticks_compared` sums
`fixed_ticks` over examined checkpoints after the initial state.

Report assembly (`ReplayReport v1`, status precedence, `environment_diff`) belongs to
`features/replay.py`; the comparator intentionally carries no environment or status fields
because those depend on the request and host, not the checkpoint rows.
