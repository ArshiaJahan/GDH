"""Contract tests for the `.gdwreplay` v1 reader/writer, canonical hashes and comparison.

Covers the byte-level golden vectors from docs/plans/record-replay-contracts.md §4, archive
round-trips, every structural rejection case in §3, the reader's size/ratio limits, and the
checkpoint comparator's report-relevant fields.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import stat
import struct
import warnings
import zipfile
from pathlib import Path

import pytest

from gamedevworkstation.features import replay_format as RF
from gamedevworkstation.features.replay_format import (
    ReplayFormatError, compare_checkpoints, provider_hash, read_replay, state_hash, write_replay,
)

FIXTURES = Path(__file__).parent / "fixtures" / "replay"
GOLDEN = FIXTURES / "golden_v1.gdwreplay"


def _digest(*parts: bytes) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
    return h.hexdigest()


def _u32(n: int) -> bytes:
    return struct.pack("<I", n)


def _payload(fields: dict[str, tuple[int, bytes]]) -> bytes:
    out = [_u32(len(fields))]
    for name in sorted(fields):
        tag, value = fields[name]
        encoded = name.encode("utf-8")
        out += [struct.pack("<H", len(encoded)), encoded, bytes([tag]), value]
    return b"".join(out)


def _string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return _u32(len(encoded)) + encoded


def _hp_payload(hp: int = 100) -> bytes:
    return _payload({"alive": (0x01, b"\x01"), "hp": (0x02, struct.pack("<i", hp))})


PH100 = provider_hash("game.hp", _hp_payload(100))
PH99 = provider_hash("game.hp", _hp_payload(99))
H100 = state_hash({"game.hp": _hp_payload(100)})
H99 = state_hash({"game.hp": _hp_payload(99)})
EMPTY_SHA = hashlib.sha256(b"").hexdigest()

HEADER = {
    "format": "gdwreplay", "major": 1, "minor": 0,
    "run_id": "rr_0123456789abcdef", "created_utc": "2026-01-02T03:04:05Z",
    "tool_version": "0.1.0",
    "unity": {"version": "6000.3.21f1", "revision": "abc123", "scripting_backend": "mono"},
    "os": {"platform": "macOS", "version": "15.0"},
    "cpu": {"model": "Apple M3", "architecture": "arm64", "cores": 8},
    "project": {"id": "fixture", "name": "ReplayFixture", "content_sha256": "0" * 64,
                "dirty": False},
    "scene": {"guid": "1" * 32, "path": "Assets/ReplayFixture/Generated.unity",
              "content_sha256": "2" * 64},
    "seed": 0,
    "fixed_dt": {"num": 1, "den": 60},
    "render_dt": {"num": 1, "den": 60},
    "packages": {"versions": {}, "lock_sha256": "3" * 64},
    "input": {"settings_sha256": "4" * 64, "actions_sha256": "5" * 64,
              "layouts_sha256": "6" * 64, "system_version": "1.20.1"},
    "devices": [{"description": "Keyboard", "layout": "Keyboard",
                 "state_format_sha256": "7" * 64}],
    "providers": [{"id": "game.hp", "schema_sha256": "8" * 64, "gameplay": True}],
    "reset_adapter": {"id": "scene-reset", "initial_state_sha256": H100},
    "state_hash": {"algorithm": "sha256", "encoding": "gdw-replay-state/1"},
    "features": {"required": [], "optional": []},
    "coverage": {"unsupported": [], "notes": ""},
}

TRACE = b"GDW input trace fixture"


def _header(**overrides) -> dict:
    header = json.loads(json.dumps(HEADER))
    header.update(overrides)
    return header


def _row(frame: int, *, tick: int | None = None, state: str = H100, provider: str = PH100,
         fixed_ticks: int = 1, providers: dict[str, str] | None = None,
         event_count: int = 0) -> dict:
    if frame < 0:
        tick = 0 if tick is None else tick
        fixed_ticks = 0
    return {
        "frame": frame,
        "tick": (frame + 1 if frame >= 0 else 0) if tick is None else tick,
        "fixed_ticks": fixed_ticks,
        "input_update": False,
        "event_start": 0,
        "event_count": event_count,
        "hash": state,
        "providers": {"game.hp": provider} if providers is None else providers,
    }


FRAMES = [
    _row(-1, state=H100, provider=PH100),
    _row(0, state=H100, provider=PH100),
    _row(1, state=H99, provider=PH99),
]
MARKERS = [
    {"frame": 0, "tick": 1, "label": "combat-start", "data": {"enemy": "slime"}},
]


# --------------------------------------------------------------------------- zip helpers

def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {info.filename: zf.read(info) for info in zf.infolist()}


def _write_zip(path: Path, entries, *, compression=zipfile.ZIP_DEFLATED) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w", compression=compression) as zf:
            for name, data in entries:
                zf.writestr(name, data)
    return path


def _valid_archive(tmp_path: Path) -> Path:
    path = tmp_path / "valid.gdwreplay"
    write_replay(path, header=_header(), frames=FRAMES, markers=MARKERS, input_trace=TRACE)
    return path


def _valid_members(tmp_path: Path) -> dict[str, bytes]:
    return _members(_valid_archive(tmp_path))


def _rewrite_member(members: dict[str, bytes], name: str, mutate) -> dict[str, bytes]:
    value = json.loads(members[name])
    mutate(value)
    members[name] = RF.canonical_json_bytes(value)
    return members


# --------------------------------------------------------------------------- golden vectors

def test_state_hash_golden_vector_v1():
    payload = _hp_payload(100)
    assert payload.hex() == ("020000000500616c6976650101020068700264000000")
    assert state_hash({"game.hp": payload}) == (
        "542d2da118d9b08e78cfa33f4a7e426ad5c742bfda979db68f7bb082282b2dfb")
    assert provider_hash("game.hp", payload).startswith("dcc1e59d")


def test_state_hash_golden_vector_v2():
    payload = _payload({
        "blob": (0x09, _u32(3) + bytes([0x00, 0xFF, 0x10])),
        "delta": (0x04, struct.pack("<q", -2)),
        "f32": (0x06, struct.pack("<f", 1.5)),
        "f64": (0x07, struct.pack("<d", 3.25)),
        "name": (0x08, _string("héllo")),
        "pos": (0x0A, struct.pack("<3f", 1, -2.5, 0)),
        "q": (0x0B, struct.pack("<4f", 0, 0, 0, 1)),
        "ticks": (0x05, struct.pack("<Q", 2**64 - 1)),
    })
    assert state_hash({"game.state": payload}) == (
        "7d362c286a4b10523b3940a4c812363b8299c490579bdd0d4796e8ec833bc211")


def test_state_hash_golden_vector_v3_negative_zero_and_rng():
    inventory = _payload({
        "count": (0x03, _u32(2)),
        "negzero": (0x06, struct.pack("<f", -0.0)),
        "slot.0": (0x08, _string("sword")),
        "slot.1": (0x08, _string("potion")),
    })
    rng = _payload({
        "seed": (0x03, _u32(12345)),
        "stream.combat.draws": (0x05, struct.pack("<Q", 0)),
        "stream.combat.state": (0x03, _u32(0x6E624EB7)),
        "stream.loot.draws": (0x05, struct.pack("<Q", 3)),
        "stream.loot.state": (0x03, _u32(0xDEADBEEF)),
    })
    assert state_hash({"game.inventory": inventory, "unity.rng": rng}) == (
        "7903c8fb91600773d718253be4deb42c43887c8b8080560b53aa31133b568e1f")


def test_state_hash_is_id_order_independent_and_provider_block_is_canonical():
    a = _payload({"hp": (0x02, struct.pack("<i", 100))})
    b = _payload({"state": (0x08, _string("idle"))})
    assert state_hash({"game.a": a, "game.b": b}) == state_hash({"game.b": b, "game.a": a})
    block = _u32(6) + b"game.a" + _u32(len(a)) + a
    assert provider_hash("game.a", a) == hashlib.sha256(block).hexdigest()


def test_state_hash_rejects_invalid_provider_id():
    with pytest.raises(ValueError):
        state_hash({"Game.Hp": b""})
    with pytest.raises(ValueError):
        provider_hash("", b"")


# --------------------------------------------------------------------------- round-trip

def test_write_and_read_round_trip(tmp_path):
    path = tmp_path / "nested" / "run.gdwreplay"
    archive = write_replay(path, header=_header(), frames=FRAMES, markers=MARKERS,
                           input_trace=TRACE, console={"errors": 0, "warnings": 2})
    assert archive.path == path
    assert path.is_file()
    assert archive.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert archive.header == HEADER
    assert archive.frames == FRAMES
    assert archive.markers == MARKERS
    assert archive.input_trace_size == len(TRACE)
    assert archive.uncompressed_size == sum(
        info.file_size for info in zipfile.ZipFile(path).infolist())
    manifest = archive.manifest
    assert manifest["format"] == "gdwreplay-manifest"
    assert manifest["version"] == 1 and manifest["complete"] is True
    assert manifest["console"] == {"errors": 0, "warnings": 2}
    assert manifest["final_frame_hash"] == H99
    assert {entry["name"] for entry in manifest["files"]} == {
        "header.json", "input.inputtrace", "frames.jsonl", "markers.jsonl"}
    for entry in manifest["files"]:
        payload = _members(path)[entry["name"]]
        assert entry["bytes"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()


def test_writer_is_atomic_and_refuses_existing_paths(tmp_path):
    path = tmp_path / "run.gdwreplay"
    write_replay(path, header=_header(), frames=FRAMES, input_trace=TRACE)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_replay(path, header=_header(), frames=FRAMES, input_trace=b"other")
    assert path.read_bytes() == original
    write_replay(path, header=_header(), frames=FRAMES, input_trace=b"other", overwrite=True)
    assert path.read_bytes() != original
    assert [item.name for item in tmp_path.iterdir()] == ["run.gdwreplay"]


def test_writer_validates_before_replacing(tmp_path):
    path = tmp_path / "run.gdwreplay"
    with pytest.raises(ReplayFormatError):
        write_replay(path, header=_header(major=2), frames=FRAMES)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_empty_marker_file_is_valid(tmp_path):
    path = tmp_path / "run.gdwreplay"
    write_replay(path, header=_header(), frames=FRAMES)
    archive = read_replay(path)
    assert archive.markers == []


def test_unknown_minor_and_fields_are_ignored(tmp_path):
    header = _header(minor=1, future_field={"anything": [1, 2, 3]})
    archive = write_replay(tmp_path / "run.gdwreplay", header=header, frames=FRAMES,
                           markers=MARKERS, input_trace=TRACE)
    assert archive.header["minor"] == 1
    assert archive.header["future_field"] == {"anything": [1, 2, 3]}


def test_committed_golden_fixture(tmp_path):
    archive = read_replay(GOLDEN)
    assert archive.header["run_id"] == "rr_0123456789abcdef"
    assert archive.frames == FRAMES
    assert archive.markers == MARKERS
    assert archive.input_trace_size == len(TRACE)
    assert archive.manifest["final_frame_hash"] == H99


# --------------------------------------------------------------------------- rejection cases

def test_rejects_non_zip_and_truncated_archives(tmp_path):
    plain = tmp_path / "plain.gdwreplay"
    plain.write_bytes(b"not a zip")
    with pytest.raises(ReplayFormatError):
        read_replay(plain)
    valid = _valid_archive(tmp_path)
    truncated = tmp_path / "truncated.gdwreplay"
    truncated.write_bytes(valid.read_bytes()[: valid.stat().st_size // 2])
    with pytest.raises(ReplayFormatError):
        read_replay(truncated)


def test_rejects_archive_over_max_bytes(tmp_path):
    path = _valid_archive(tmp_path)
    with pytest.raises(ReplayFormatError):
        read_replay(path, max_bytes=64)


@pytest.mark.parametrize("name", ["../evil.txt", "/tmp/evil.txt", "C:/evil.txt",
                                  "a\\b.txt", "a/../../b.txt"])
def test_rejects_traversal_and_absolute_members(tmp_path, name):
    members = _valid_members(tmp_path)
    path = _write_zip(tmp_path / "bad.gdwreplay", [(key, value) for key, value in members.items()]
                      + [(name, b"evil")])
    with pytest.raises(ReplayFormatError):
        read_replay(path)


def test_rejects_symlink_member(tmp_path):
    members = _valid_members(tmp_path)
    info = zipfile.ZipInfo("link.txt")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    path = _write_zip(tmp_path / "bad.gdwreplay",
                      [(key, value) for key, value in members.items()] + [(info, b"target")])
    with pytest.raises(ReplayFormatError, match="symlink"):
        read_replay(path)


def test_rejects_duplicate_member(tmp_path):
    members = _valid_members(tmp_path)
    entries = list(members.items()) + [("markers.jsonl", members["markers.jsonl"])]
    path = _write_zip(tmp_path / "bad.gdwreplay", entries)
    with pytest.raises(ReplayFormatError, match="duplicate"):
        read_replay(path)


def test_rejects_compression_bomb_ratio(tmp_path):
    members = _valid_members(tmp_path)
    path = _write_zip(tmp_path / "bad.gdwreplay",
                      [(key, value) for key, value in members.items()]
                      + [("bomb.bin", b"\0" * (2 * 1024 * 1024))])
    with pytest.raises(ReplayFormatError, match="compression ratio"):
        read_replay(path)


def test_rejects_oversized_member(tmp_path, monkeypatch):
    members = _valid_members(tmp_path)
    monkeypatch.setattr(RF, "MAX_MEMBER_BYTES", 2048)
    path = _write_zip(tmp_path / "bad.gdwreplay",
                      [(key, value) for key, value in members.items()]
                      + [("extra.bin", bytes(range(256)) * 16)])
    with pytest.raises(ReplayFormatError, match="member limit"):
        read_replay(path)


def test_rejects_oversized_header(tmp_path, monkeypatch):
    path = _valid_archive(tmp_path)
    monkeypatch.setattr(RF, "MAX_HEADER_BYTES", 64)
    with pytest.raises(ReplayFormatError, match="header.json"):
        read_replay(path)


def test_rejects_total_uncompressed_size(tmp_path, monkeypatch):
    members = _valid_members(tmp_path)
    path = _write_zip(tmp_path / "bad.gdwreplay",
                      [(key, value) for key, value in members.items()]
                      + [("bulk.bin", bytes(range(256)) * 40)])
    monkeypatch.setattr(RF, "MAX_ARCHIVE_BYTES", 8000)
    assert path.stat().st_size < 8000
    with pytest.raises(ReplayFormatError, match="uncompressed"):
        read_replay(path)


def test_rejects_too_many_entries(tmp_path, monkeypatch):
    path = _valid_archive(tmp_path)
    monkeypatch.setattr(RF, "MAX_ENTRIES", 4)
    with pytest.raises(ReplayFormatError, match="entries"):
        read_replay(path)


@pytest.mark.parametrize("missing", ["manifest.json", "frames.jsonl", "markers.jsonl",
                                     "input.inputtrace", "header.json"])
def test_rejects_missing_required_members(tmp_path, missing):
    members = _valid_members(tmp_path)
    del members[missing]
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="incomplete"):
        read_replay(path)


def test_rejects_unknown_major(tmp_path):
    members = _rewrite_member(_valid_members(tmp_path), "header.json",
                              lambda header: header.__setitem__("major", 2))
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="unsupported replay format major"):
        read_replay(path)


def test_rejects_unknown_required_feature(tmp_path):
    members = _rewrite_member(_valid_members(tmp_path), "header.json",
                              lambda header: header["features"].__setitem__("required", ["x"]))
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="required feature"):
        read_replay(path)


def test_rejects_member_crc_mismatch(tmp_path):
    members = _valid_members(tmp_path)
    path = _write_zip(tmp_path / "bad.gdwreplay",
                      [(key, value) for key, value in members.items()]
                      + [("extra.txt", b"checksum-me")],
                      compression=zipfile.ZIP_STORED)
    data = bytearray(path.read_bytes())
    name = b"extra.txt"
    name_pos = data.find(name)
    header_start = name_pos - 30
    extra_len = int.from_bytes(data[header_start + 28:header_start + 30], "little")
    data[name_pos + len(name) + extra_len] ^= 0xFF
    path.write_bytes(data)
    with pytest.raises(ReplayFormatError, match="checksum mismatch"):
        read_replay(path)


def test_rejects_bad_manifest_digest(tmp_path):
    def corrupt(manifest):
        for entry in manifest["files"]:
            if entry["name"] == "frames.jsonl":
                entry["sha256"] = "0" * 64

    members = _rewrite_member(_valid_members(tmp_path), "manifest.json", corrupt)
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="SHA-256 mismatch"):
        read_replay(path)


def test_rejects_bad_manifest_byte_count(tmp_path):
    def corrupt(manifest):
        manifest["files"][0]["bytes"] += 1

    members = _rewrite_member(_valid_members(tmp_path), "manifest.json", corrupt)
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError):
        read_replay(path)


def test_rejects_incomplete_manifest(tmp_path):
    members = _rewrite_member(_valid_members(tmp_path), "manifest.json",
                              lambda manifest: manifest.__setitem__("complete", False))
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="incomplete"):
        read_replay(path)


def test_rejects_manifest_not_covering_all_members(tmp_path):
    def corrupt(manifest):
        manifest["files"] = [entry for entry in manifest["files"]
                             if entry["name"] != "markers.jsonl"]

    members = _rewrite_member(_valid_members(tmp_path), "manifest.json", corrupt)
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="does not cover"):
        read_replay(path)


def test_rejects_non_finite_json(tmp_path):
    members = _valid_members(tmp_path)
    members["header.json"] = members["header.json"].replace(b'"seed":0', b'"seed":NaN')
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="JSON"):
        read_replay(path)


@pytest.mark.parametrize("mutate", [
    lambda rows: rows.__setitem__(0, _row(0)),
    lambda rows: rows.__setitem__(1, _row(1)),
    lambda rows: rows.append(_row(3)),
    lambda rows: rows.append(_row(1)),
])
def test_rejects_non_contiguous_or_duplicate_frames(tmp_path, mutate):
    members = _valid_members(tmp_path)
    rows = [json.loads(line) for line in members["frames.jsonl"].splitlines()]
    mutate(rows)
    members["frames.jsonl"] = b"".join(RF.canonical_json_bytes(row) + b"\n" for row in rows)
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="frame"):
        read_replay(path)


def test_rejects_frame_provider_set_mismatch(tmp_path):
    members = _valid_members(tmp_path)
    rows = [json.loads(line) for line in members["frames.jsonl"].splitlines()]
    rows[1]["providers"]["game.extra"] = _digest(b"extra")
    members["frames.jsonl"] = b"".join(RF.canonical_json_bytes(row) + b"\n" for row in rows)
    path = _write_zip(tmp_path / "bad.gdwreplay", list(members.items()))
    with pytest.raises(ReplayFormatError, match="header.providers"):
        read_replay(path)


# --------------------------------------------------------------------------- comparison

def test_identical_checkpoints_compare_clean():
    result = compare_checkpoints(FRAMES, FRAMES, markers=MARKERS)
    assert result.first_divergent_frame is None
    assert result.first_divergent_tick is None
    assert result.provider_id is None
    assert result.expected_hash is None and result.actual_hash is None
    assert result.missing_provider_ids == ()
    assert result.extra_provider_ids == ()
    assert result.nearby_markers == ()
    assert result.frames_compared == 3  # includes the initial frame -1
    assert result.ticks_compared == 2


def test_divergence_at_known_frame_and_provider():
    actual = [dict(row) for row in FRAMES]
    actual[2] = _row(1, state=H99, provider=_digest(b"other-provider-state"))
    actual[2]["tick"] = 2
    result = compare_checkpoints(FRAMES, actual, markers=MARKERS)
    assert result.first_divergent_frame == 1
    assert result.first_divergent_tick == 2
    assert result.provider_id == "game.hp"
    assert result.expected_hash == H99
    assert result.actual_hash == H99
    assert result.frames_compared == 3
    assert result.missing_provider_ids == () and result.extra_provider_ids == ()


def test_divergence_on_aggregate_hash_with_equal_providers():
    actual = [dict(row) for row in FRAMES]
    actual[1] = _row(0, state=_digest(b"aggregate"), provider=PH100)
    result = compare_checkpoints(FRAMES, actual)
    assert result.first_divergent_frame == 0
    assert result.provider_id is None
    assert result.expected_hash == H100
    assert result.actual_hash == _digest(b"aggregate")


def test_divergence_on_tick():
    actual = [dict(row) for row in FRAMES]
    actual[1] = _row(0, tick=7, state=H100, provider=PH100)
    result = compare_checkpoints(FRAMES, actual)
    assert result.first_divergent_frame == 0
    assert result.first_divergent_tick == 1
    assert result.provider_id is None


def test_missing_frame_is_reported_as_divergence():
    result = compare_checkpoints(FRAMES, FRAMES[:2], markers=MARKERS)
    assert result.first_divergent_frame == 1
    assert result.first_divergent_tick == 2
    assert result.expected_hash == H99
    assert result.actual_hash is None
    assert result.frames_compared == 3


def test_extra_provider_is_reported():
    actual = [dict(row) for row in FRAMES]
    actual[1] = _row(0, state=H100, provider=PH100,
                     providers={"game.hp": PH100, "game.extra": _digest(b"extra")})
    result = compare_checkpoints(FRAMES, actual)
    assert result.first_divergent_frame == 0
    assert result.provider_id == "game.extra"
    assert result.extra_provider_ids == ("game.extra",)
    assert result.missing_provider_ids == ()


def test_missing_provider_is_reported():
    actual = [dict(row) for row in FRAMES]
    actual[1] = _row(0, state=H100, provider=PH100, providers={"unity.rng": _digest(b"rng")})
    result = compare_checkpoints(FRAMES, actual)
    assert result.first_divergent_frame == 0
    assert result.provider_id == "game.hp"  # earliest sorted differing provider
    assert result.missing_provider_ids == ("game.hp",)
    assert result.extra_provider_ids == ("unity.rng",)


def test_nearby_markers_are_bounded_to_ten_and_five_frames():
    markers = [{"frame": frame, "tick": frame, "label": f"m{frame}", "data": None}
               for frame in range(-5, 15)]
    actual = [dict(row) for row in FRAMES]
    actual[1] = _row(0, state=_digest(b"x"))
    result = compare_checkpoints(FRAMES, actual, markers=markers)
    assert result.first_divergent_frame == 0
    assert len(result.nearby_markers) == 10
    assert all(abs(marker["frame"]) <= 5 for marker in result.nearby_markers)
    assert set(result.nearby_markers[0]) == {"frame", "tick", "label"}
    assert [marker["frame"] for marker in result.nearby_markers] == sorted(
        marker["frame"] for marker in result.nearby_markers)


@pytest.mark.parametrize("rows", [
    [_row(0), _row(1)],
    [_row(-1), _row(-1)],
    [_row(-1), _row(1)],
    [],
])
def test_comparator_raises_for_non_contiguous_duplicate_or_empty_rows(rows):
    with pytest.raises(ReplayFormatError):
        compare_checkpoints(rows, FRAMES)


def test_comparator_raises_for_schema_mismatch():
    broken = [dict(row) for row in FRAMES]
    del broken[1]["hash"]
    with pytest.raises(ReplayFormatError):
        compare_checkpoints(broken, FRAMES)


def test_comparison_fields_cover_report_v1_needs():
    fields = [field.name for field in dataclasses.fields(RF.CheckpointComparison)]
    assert fields == [
        "frames_compared", "ticks_compared", "first_divergent_frame", "first_divergent_tick",
        "provider_id", "expected_hash", "actual_hash", "missing_provider_ids",
        "extra_provider_ids", "nearby_markers",
    ]


def test_contract_constants():
    assert RF.MAX_ARCHIVE_BYTES == 512 * 1024 * 1024
    assert RF.MAX_MEMBER_BYTES == 256 * 1024 * 1024
    assert RF.MAX_HEADER_BYTES == 1024 * 1024
    assert RF.MAX_LINE_BYTES == 8192
    assert RF.MAX_FRAMES == 1_000_000
    assert RF.MAX_MARKERS == 10_000
    assert RF.MAX_ENTRIES == 64
    assert RF.MAX_COMPRESSION_RATIO == 200
    assert RF.STATE_MAGIC == b"GDWSTATE"
    assert RF.STATE_ENCODING_VERSION == 1
    assert RF.HASH_ALGORITHM == "sha256"
