"""`.gdwreplay` v1 archive reader/writer, canonical state hashes and checkpoint comparison.

The frozen on-disk and byte-level contract is docs/plans/record-replay-contracts.md (§3-§4).
Reading is defensive: bounded sizes, no extraction, duplicate/traversal/symlink members and
checksum or manifest mismatches raise ReplayFormatError. Writing exists for tests and fixtures
and is atomic; production archives are written by the Unity package.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import struct
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_HEADER_BYTES = 1024 * 1024
MAX_LINE_BYTES = 8192
MAX_FRAMES = 1_000_000
MAX_MARKERS = 10_000
MAX_ENTRIES = 64
MAX_COMPRESSION_RATIO = 200
STATE_MAGIC = b"GDWSTATE"
STATE_ENCODING_VERSION = 1
HASH_ALGORITHM = "sha256"
REQUIRED_MEMBERS = ("header.json", "input.inputtrace", "frames.jsonl", "markers.jsonl", "manifest.json")

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_FRAME_KEYS = ("frame", "tick", "fixed_ticks", "input_update", "event_start", "event_count",
               "hash", "providers")
_MANIFEST_MEMBERS = ("header.json", "input.inputtrace", "frames.jsonl", "markers.jsonl")
_MAX_FRACTION_DEN = 1_000_000


class ReplayFormatError(ValueError):
    """A malformed, unsupported, incomplete or oversized replay archive; member/frame say where."""

    def __init__(self, message: str, *, member: str | None = None, frame: int | None = None) -> None:
        super().__init__(message)
        self.member = member
        self.frame = frame


@dataclass(frozen=True)
class ReplayArchive:
    """A parsed archive: header, checkpoint rows, markers, manifest and file digests."""

    path: Path
    sha256: str
    header: dict
    frames: list[dict]
    markers: list[dict]
    manifest: dict
    input_trace_size: int
    uncompressed_size: int


@dataclass(frozen=True)
class CheckpointComparison:
    """The outcome of comparing expected and actual frame checkpoints (no raising on mismatch)."""

    frames_compared: int
    ticks_compared: int
    first_divergent_frame: int | None
    first_divergent_tick: int | None
    provider_id: str | None
    expected_hash: str | None
    actual_hash: str | None
    missing_provider_ids: tuple[str, ...]
    extra_provider_ids: tuple[str, ...]
    nearby_markers: tuple[dict, ...]


# --------------------------------------------------------------------------- JSON helpers

def _reject_constant(text: str) -> Any:
    raise ValueError(f"non-finite number {text}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON field {key!r}")
        obj[key] = value
    return obj


def _loads(data: bytes, member: str, *, frame: int | None = None) -> Any:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReplayFormatError(f"{member} is not valid UTF-8", member=member, frame=frame) from exc
    try:
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates,
                          parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ReplayFormatError(f"{member} is not valid JSON: {exc}", member=member,
                                frame=frame) from exc


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical UTF-8 JSON used by the contract: sorted keys, no spaces, no NaN/Infinity."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReplayFormatError(f"value is not canonical-JSON encodable: {exc}") from exc


# --------------------------------------------------------------------------- field validation

def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int(value: Any, what: str, *, member: str, frame: int | None = None,
         minimum: int | None = None, maximum: int | None = None) -> int:
    if not _is_int(value):
        raise ReplayFormatError(f"{what} must be an integer", member=member, frame=frame)
    if minimum is not None and value < minimum:
        raise ReplayFormatError(f"{what} must be >= {minimum}", member=member, frame=frame)
    if maximum is not None and value > maximum:
        raise ReplayFormatError(f"{what} must be <= {maximum}", member=member, frame=frame)
    return value


def _str(value: Any, what: str, *, member: str, frame: int | None = None) -> str:
    if not isinstance(value, str):
        raise ReplayFormatError(f"{what} must be a string", member=member, frame=frame)
    return value


def _bool(value: Any, what: str, *, member: str, frame: int | None = None) -> bool:
    if not isinstance(value, bool):
        raise ReplayFormatError(f"{what} must be a boolean", member=member, frame=frame)
    return value


def _obj(value: Any, what: str, *, member: str, frame: int | None = None) -> dict:
    if not isinstance(value, dict):
        raise ReplayFormatError(f"{what} must be an object", member=member, frame=frame)
    return value


def _digest(value: Any, what: str, *, member: str, frame: int | None = None) -> str:
    text = _str(value, what, member=member, frame=frame)
    if not _SHA256_RE.match(text):
        raise ReplayFormatError(f"{what} must be a lowercase SHA-256 hex digest", member=member,
                                frame=frame)
    return text


def _provider_id(value: Any, what: str, *, member: str, frame: int | None = None) -> str:
    text = _str(value, what, member=member, frame=frame)
    if not _PROVIDER_ID_RE.match(text):
        raise ReplayFormatError(f"{what} is not a valid provider id", member=member, frame=frame)
    return text


def _fraction(value: Any, what: str, *, member: str) -> tuple[int, int]:
    obj = _obj(value, what, member=member)
    num = _int(obj.get("num"), f"{what}.num", member=member, minimum=1)
    den = _int(obj.get("den"), f"{what}.den", member=member, minimum=1,
               maximum=_MAX_FRACTION_DEN)
    if math.gcd(num, den) != 1:
        raise ReplayFormatError(f"{what} must be a reduced fraction", member=member)
    return num, den


def _str_list(value: Any, what: str, *, member: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReplayFormatError(f"{what} must be an array of strings", member=member)
    return value


def _relative_posix_path(value: Any, what: str, *, member: str) -> str:
    text = _str(value, what, member=member)
    if not text or text.startswith("/") or _DRIVE_RE.match(text) or "\\" in text:
        raise ReplayFormatError(f"{what} must be a project-relative POSIX path", member=member)
    if any(part in ("", ".", "..") for part in text.split("/")):
        raise ReplayFormatError(f"{what} must be a project-relative POSIX path", member=member)
    return text


def _safe_member_name(name: Any, *, member: str, frame: int | None = None) -> list[str]:
    """Parts of a safe archive/member name; rejects absolute, traversal, blank and `\\` names."""
    text = _str(name, "member name", member=member, frame=frame)
    if not text:
        raise ReplayFormatError("archive contains an empty member name", member=member, frame=frame)
    if "\x00" in text:
        raise ReplayFormatError("archive member name contains NUL", member=member, frame=frame)
    if "\\" in text:
        raise ReplayFormatError(f"archive member name uses a backslash: {text!r}", member=member,
                                frame=frame)
    if text.startswith("/") or _DRIVE_RE.match(text):
        raise ReplayFormatError(f"archive member name is absolute: {text!r}", member=member,
                                frame=frame)
    body = text[:-1] if text.endswith("/") else text
    parts = body.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ReplayFormatError(f"archive member name escapes the archive: {text!r}",
                                member=member, frame=frame)
    return parts


# --------------------------------------------------------------------------- header/frames

def _check_header(header: dict) -> tuple[dict, list[str]]:
    """Validate a v1 header; return it and its provider ids in contract order."""
    member = "header.json"
    if header.get("format") != "gdwreplay":
        raise ReplayFormatError("header.json format must be 'gdwreplay'", member=member)
    major = _int(header.get("major"), "header.major", member=member)
    if major != 1:
        raise ReplayFormatError(f"unsupported replay format major {major}; this reader supports 1",
                                member=member)
    _int(header.get("minor"), "header.minor", member=member, minimum=0)
    run_id = _str(header.get("run_id"), "header.run_id", member=member)
    if not _RUN_ID_RE.match(run_id):
        raise ReplayFormatError("header.run_id does not match the run-id pattern", member=member)
    _str(header.get("created_utc"), "header.created_utc", member=member)
    _str(header.get("tool_version"), "header.tool_version", member=member)
    _int(header.get("seed"), "header.seed", member=member, minimum=0, maximum=0xFFFFFFFF)
    _fraction(header.get("fixed_dt"), "header.fixed_dt", member=member)
    _fraction(header.get("render_dt"), "header.render_dt", member=member)

    unity = _obj(header.get("unity"), "header.unity", member=member)
    _str(unity.get("version"), "header.unity.version", member=member)
    _str(unity.get("revision"), "header.unity.revision", member=member)
    backend = _str(unity.get("scripting_backend"), "header.unity.scripting_backend", member=member)
    if backend not in ("mono", "il2cpp"):
        raise ReplayFormatError("header.unity.scripting_backend must be 'mono' or 'il2cpp'",
                                member=member)

    os_info = _obj(header.get("os"), "header.os", member=member)
    _str(os_info.get("platform"), "header.os.platform", member=member)
    _str(os_info.get("version"), "header.os.version", member=member)
    cpu = _obj(header.get("cpu"), "header.cpu", member=member)
    _str(cpu.get("model"), "header.cpu.model", member=member)
    _str(cpu.get("architecture"), "header.cpu.architecture", member=member)
    _int(cpu.get("cores"), "header.cpu.cores", member=member, minimum=1)

    project = _obj(header.get("project"), "header.project", member=member)
    _str(project.get("id"), "header.project.id", member=member)
    _str(project.get("name"), "header.project.name", member=member)
    _digest(project.get("content_sha256"), "header.project.content_sha256", member=member)
    _bool(project.get("dirty"), "header.project.dirty", member=member)

    scene = _obj(header.get("scene"), "header.scene", member=member)
    _str(scene.get("guid"), "header.scene.guid", member=member)
    _relative_posix_path(scene.get("path"), "header.scene.path", member=member)
    _digest(scene.get("content_sha256"), "header.scene.content_sha256", member=member)

    packages = _obj(header.get("packages"), "header.packages", member=member)
    versions = _obj(packages.get("versions"), "header.packages.versions", member=member)
    for package_id, version in versions.items():
        if not isinstance(package_id, str) or not isinstance(version, str):
            raise ReplayFormatError("header.packages.versions must map strings to strings",
                                    member=member)
    _digest(packages.get("lock_sha256"), "header.packages.lock_sha256", member=member)

    inputs = _obj(header.get("input"), "header.input", member=member)
    for key in ("settings_sha256", "actions_sha256", "layouts_sha256"):
        _digest(inputs.get(key), f"header.input.{key}", member=member)
    _str(inputs.get("system_version"), "header.input.system_version", member=member)

    devices = header.get("devices")
    if not isinstance(devices, list):
        raise ReplayFormatError("header.devices must be an array", member=member)
    for index, device in enumerate(devices):
        item = _obj(device, f"header.devices[{index}]", member=member)
        _str(item.get("description"), f"header.devices[{index}].description", member=member)
        _str(item.get("layout"), f"header.devices[{index}].layout", member=member)
        _digest(item.get("state_format_sha256"), f"header.devices[{index}].state_format_sha256",
                member=member)

    providers = header.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ReplayFormatError("header.providers must be a non-empty array", member=member)
    provider_ids: list[str] = []
    gameplay = False
    for index, provider in enumerate(providers):
        item = _obj(provider, f"header.providers[{index}]", member=member)
        provider_ids.append(_provider_id(item.get("id"), f"header.providers[{index}].id",
                                         member=member))
        _digest(item.get("schema_sha256"), f"header.providers[{index}].schema_sha256",
                member=member)
        gameplay = _bool(item.get("gameplay"), f"header.providers[{index}].gameplay",
                         member=member) or gameplay
    if len(set(provider_ids)) != len(provider_ids):
        raise ReplayFormatError("header.providers contains duplicate ids", member=member)
    if provider_ids != sorted(provider_ids):
        raise ReplayFormatError("header.providers must be sorted by id", member=member)
    if not gameplay:
        raise ReplayFormatError("header.providers must include at least one gameplay provider",
                                member=member)

    adapter = _obj(header.get("reset_adapter"), "header.reset_adapter", member=member)
    _str(adapter.get("id"), "header.reset_adapter.id", member=member)
    _digest(adapter.get("initial_state_sha256"), "header.reset_adapter.initial_state_sha256",
            member=member)

    state = _obj(header.get("state_hash"), "header.state_hash", member=member)
    if state.get("algorithm") != HASH_ALGORITHM:
        raise ReplayFormatError("header.state_hash.algorithm must be 'sha256'", member=member)
    if state.get("encoding") != "gdw-replay-state/1":
        raise ReplayFormatError("header.state_hash.encoding must be 'gdw-replay-state/1'",
                                member=member)

    features = _obj(header.get("features"), "header.features", member=member)
    required = _str_list(features.get("required"), "header.features.required", member=member)
    _str_list(features.get("optional"), "header.features.optional", member=member)
    if required:
        raise ReplayFormatError(f"unsupported required feature {required[0]!r}", member=member)

    coverage = _obj(header.get("coverage"), "header.coverage", member=member)
    _str_list(coverage.get("unsupported"), "header.coverage.unsupported", member=member)
    return header, provider_ids


def _parse_frames(data: bytes, provider_ids: list[str]) -> list[dict]:
    member = "frames.jsonl"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReplayFormatError("frames.jsonl is not valid UTF-8", member=member) from exc
    if not text.strip():
        raise ReplayFormatError("frames.jsonl is empty; the initial frame -1 is required",
                                member=member)
    lines = text.splitlines()
    if len(lines) > MAX_FRAMES:
        raise ReplayFormatError(f"frames.jsonl has more than {MAX_FRAMES} rows", member=member)
    expected_providers = set(provider_ids)
    rows: list[dict] = []
    for index, line in enumerate(lines):
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ReplayFormatError(f"frame row exceeds {MAX_LINE_BYTES} bytes", member=member,
                                    frame=index - 1)
        row = _loads(line.encode("utf-8"), member, frame=index - 1)
        row = _obj(row, "frame row", member=member, frame=index - 1)
        expected_frame = index - 1
        if row.get("frame") != expected_frame:
            raise ReplayFormatError(
                f"frames.jsonl must start at frame -1 and be contiguous; expected {expected_frame}",
                member=member, frame=index - 1)
        row = _check_frame_row(row, expected_frame=expected_frame, member=member,
                               required_provider_ids=expected_providers)
        rows.append(row)
    return rows


def _check_frame_row(row: dict, *, expected_frame: int | None, member: str,
                     required_provider_ids: set[str] | None = None) -> dict:
    frame = _int(row.get("frame"), "frame.frame", member=member,
                 minimum=-1 if expected_frame is None else expected_frame)
    if expected_frame is not None and frame != expected_frame:
        raise ReplayFormatError(f"expected frame {expected_frame}, found {frame}", member=member,
                                frame=frame)
    _int(row.get("tick"), "frame.tick", member=member, frame=frame, minimum=0)
    _int(row.get("fixed_ticks"), "frame.fixed_ticks", member=member, frame=frame, minimum=0)
    _bool(row.get("input_update"), "frame.input_update", member=member, frame=frame)
    _int(row.get("event_start"), "frame.event_start", member=member, frame=frame, minimum=0)
    _int(row.get("event_count"), "frame.event_count", member=member, frame=frame, minimum=0)
    _digest(row.get("hash"), "frame.hash", member=member, frame=frame)
    providers = _obj(row.get("providers"), "frame.providers", member=member, frame=frame)
    if not providers:
        raise ReplayFormatError("frame.providers must not be empty", member=member, frame=frame)
    ids: list[str] = []
    for provider_id, value in providers.items():
        ids.append(_provider_id(provider_id, "frame provider id", member=member, frame=frame))
        _digest(value, f"frame provider {provider_id!r} hash", member=member, frame=frame)
    if len(set(ids)) != len(ids):
        raise ReplayFormatError("frame.providers contains duplicate ids", member=member,
                                frame=frame)
    if required_provider_ids is not None and set(ids) != required_provider_ids:
        missing = sorted(required_provider_ids - set(ids))
        extra = sorted(set(ids) - required_provider_ids)
        detail = [f"missing {missing}"] if missing else []
        if extra:
            detail.append(f"extra {extra}")
        raise ReplayFormatError("frame.providers does not match header.providers ("
                                + ", ".join(detail) + ")", member=member, frame=frame)
    return row


def _parse_markers(data: bytes) -> list[dict]:
    member = "markers.jsonl"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReplayFormatError("markers.jsonl is not valid UTF-8", member=member) from exc
    if not text.strip():
        return []
    lines = text.splitlines()
    if len(lines) > MAX_MARKERS:
        raise ReplayFormatError(f"markers.jsonl has more than {MAX_MARKERS} rows", member=member)
    markers: list[dict] = []
    for index, line in enumerate(lines):
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise ReplayFormatError(f"marker row exceeds {MAX_LINE_BYTES} bytes", member=member,
                                    frame=index)
        marker = _loads(line.encode("utf-8"), member, frame=index)
        marker = _obj(marker, "marker row", member=member, frame=index)
        frame = _int(marker.get("frame"), "marker.frame", member=member, frame=index)
        _int(marker.get("tick"), "marker.tick", member=member, frame=frame)
        label = _str(marker.get("label"), "marker.label", member=member, frame=frame)
        if len(label) > 128:
            raise ReplayFormatError("marker label exceeds 128 characters", member=member,
                                    frame=frame)
        if "data" in marker and marker["data"] is not None:
            try:
                size = len(canonical_json_bytes(marker["data"]))
            except ReplayFormatError as exc:
                raise ReplayFormatError(f"marker data is not canonical JSON: {exc}",
                                        member=member, frame=frame) from exc
            if size > 4096:
                raise ReplayFormatError("marker data exceeds 4096 canonical bytes", member=member,
                                        frame=frame)
        markers.append(marker)
    return markers


def _parse_manifest(data: bytes, member_bytes: Mapping[str, bytes], by_name: Mapping[str, zipfile.ZipInfo],
                    zf: zipfile.ZipFile, frames: list[dict]) -> dict:
    member = "manifest.json"
    manifest = _obj(_loads(data, member), "manifest.json", member=member)
    if manifest.get("format") != "gdwreplay-manifest":
        raise ReplayFormatError("manifest.json format must be 'gdwreplay-manifest'", member=member)
    version = _int(manifest.get("version"), "manifest.version", member=member, minimum=1)
    if version != 1:
        raise ReplayFormatError(f"unsupported manifest version {version}", member=member)
    if manifest.get("complete") is not True:
        raise ReplayFormatError("incomplete replay archive: manifest.complete is not true",
                                member=member)
    console = _obj(manifest.get("console"), "manifest.console", member=member)
    _int(console.get("errors"), "manifest.console.errors", member=member, minimum=0)
    _int(console.get("warnings"), "manifest.console.warnings", member=member, minimum=0)
    for key in ("frames", "ticks", "events"):
        _int(manifest.get(key), f"manifest.{key}", member=member, minimum=0)
    _str(manifest.get("created_utc"), "manifest.created_utc", member=member)
    _str(manifest.get("tool_version"), "manifest.tool_version", member=member)
    final_hash = _digest(manifest.get("final_frame_hash"), "manifest.final_frame_hash",
                         member=member)
    if frames and frames[-1]["hash"] != final_hash:
        raise ReplayFormatError("manifest.final_frame_hash does not match the last frame hash",
                                member=member)

    files = manifest.get("files")
    if not isinstance(files, list):
        raise ReplayFormatError("manifest.files must be an array", member=member)
    listed: dict[str, dict] = {}
    for index, item in enumerate(files):
        entry = _obj(item, f"manifest.files[{index}]", member=member)
        name = _str(entry.get("name"), f"manifest.files[{index}].name", member=member)
        _safe_member_name(name, member=member)
        if name in listed:
            raise ReplayFormatError(f"manifest.files lists {name!r} twice", member=member)
        size = _int(entry.get("bytes"), f"manifest.files[{index}].bytes", member=member,
                    minimum=0)
        digest_value = _digest(entry.get("sha256"), f"manifest.files[{index}].sha256",
                               member=member)
        listed[name] = {"bytes": size, "sha256": digest_value}

    for required in _MANIFEST_MEMBERS:
        if required not in listed:
            raise ReplayFormatError(f"manifest.files does not cover {required!r}", member=member)

    for name, entry in listed.items():
        payload = member_bytes.get(name)
        if payload is None:
            info = by_name.get(name)
            if info is None or info.is_dir():
                raise ReplayFormatError(f"manifest.files lists a missing member {name!r}",
                                        member=member)
            payload = _read_member(zf, info, MAX_MEMBER_BYTES)
        if len(payload) != entry["bytes"]:
            raise ReplayFormatError(
                f"manifest byte count for {name!r} is {entry['bytes']}, actual {len(payload)}",
                member=member)
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise ReplayFormatError(f"manifest SHA-256 mismatch for {name!r}", member=member)
    return manifest


# --------------------------------------------------------------------------- ZIP reading

def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    name = info.filename
    if info.file_size > limit:
        raise ReplayFormatError(f"{name} is larger than the {limit}-byte limit", member=name)
    chunks: list[bytes] = []
    total = 0
    try:
        with zf.open(info) as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ReplayFormatError(f"{name} is larger than the {limit}-byte limit",
                                            member=name)
                chunks.append(chunk)
    except ReplayFormatError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, ValueError, zlib.error,
            NotImplementedError) as exc:
        raise ReplayFormatError(f"corrupt replay member {name!r}: {exc}", member=name) from exc
    payload = b"".join(chunks)
    if len(payload) != info.file_size:
        raise ReplayFormatError(f"{name} size does not match its ZIP header", member=name)
    return payload


def _check_zip_members(zf: zipfile.ZipFile) -> tuple[dict[str, zipfile.ZipInfo], int]:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ReplayFormatError(f"replay archive has more than {MAX_ENTRIES} entries")
    by_name: dict[str, zipfile.ZipInfo] = {}
    total_uncompressed = 0
    for info in infos:
        name = info.filename
        _safe_member_name(name, member=name or "<unnamed>")
        if info.flag_bits & 0x1:
            raise ReplayFormatError(f"encrypted replay member {name!r} is not supported",
                                    member=name)
        if info.create_system == 3:
            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise ReplayFormatError(f"symlink replay member {name!r} is not allowed",
                                        member=name)
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ReplayFormatError(f"special replay member {name!r} is not allowed",
                                        member=name)
            if file_type == stat.S_IFDIR and not name.endswith("/"):
                raise ReplayFormatError(f"directory member {name!r} lacks a trailing slash",
                                        member=name)
        if name.endswith("/") and info.file_size:
            raise ReplayFormatError(f"directory member {name!r} carries data", member=name)
        if name in by_name:
            raise ReplayFormatError(f"duplicate replay member {name!r}", member=name)
        if info.file_size > MAX_MEMBER_BYTES:
            raise ReplayFormatError(
                f"{name} is larger than the {MAX_MEMBER_BYTES}-byte member limit", member=name)
        if name == "header.json" and info.file_size > MAX_HEADER_BYTES:
            raise ReplayFormatError(
                f"header.json is larger than the {MAX_HEADER_BYTES}-byte limit", member=name)
        if info.file_size and (info.compress_size == 0
                               or info.file_size > info.compress_size * MAX_COMPRESSION_RATIO):
            raise ReplayFormatError(f"{name} exceeds the {MAX_COMPRESSION_RATIO}:1 compression "
                                    "ratio limit", member=name)
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ARCHIVE_BYTES:
            raise ReplayFormatError("replay archive uncompressed size exceeds the limit")
        by_name[name] = info
    try:
        bad_member = zf.testzip()
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, zlib.error,
            NotImplementedError) as exc:
        raise ReplayFormatError(f"corrupt ZIP central directory: {exc}") from exc
    if bad_member is not None:
        raise ReplayFormatError(f"checksum mismatch in replay member {bad_member!r}",
                                member=bad_member)
    return by_name, total_uncompressed


def _file_sha256(path: Path, limit: int) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ReplayFormatError(f"replay archive is larger than the {limit}-byte limit")
                digest.update(chunk)
    except OSError as exc:
        raise ReplayFormatError(f"cannot read replay archive {path}: {exc}") from exc
    if total == 0:
        raise ReplayFormatError("replay archive is empty")
    return digest.hexdigest()


def read_replay(path: str | Path, *, max_bytes: int = MAX_ARCHIVE_BYTES) -> ReplayArchive:
    """Read and validate a `.gdwreplay` without extracting; raise ReplayFormatError on any violation."""
    archive_path = Path(path)
    limit = min(int(max_bytes), MAX_ARCHIVE_BYTES)
    try:
        stat_result = archive_path.stat()
    except OSError as exc:
        raise ReplayFormatError(f"cannot read replay archive {archive_path}: {exc}") from exc
    if not stat.S_ISREG(stat_result.st_mode):
        raise ReplayFormatError(f"replay archive is not a regular file: {archive_path}")
    if stat_result.st_size > limit:
        raise ReplayFormatError(f"replay archive is larger than the {limit}-byte limit")
    archive_sha256 = _file_sha256(archive_path, limit)

    try:
        zf = zipfile.ZipFile(archive_path)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ReplayFormatError(f"not a valid ZIP replay archive: {exc}") from exc
    with zf:
        by_name, uncompressed_size = _check_zip_members(zf)
        for required in REQUIRED_MEMBERS:
            info = by_name.get(required)
            if info is None or info.is_dir():
                raise ReplayFormatError(f"incomplete replay archive: missing {required}",
                                        member=required)
        member_bytes = {
            "header.json": _read_member(zf, by_name["header.json"], MAX_HEADER_BYTES),
            "input.inputtrace": _read_member(zf, by_name["input.inputtrace"], MAX_MEMBER_BYTES),
            "frames.jsonl": _read_member(zf, by_name["frames.jsonl"], MAX_MEMBER_BYTES),
            "markers.jsonl": _read_member(zf, by_name["markers.jsonl"], MAX_MEMBER_BYTES),
            "manifest.json": _read_member(zf, by_name["manifest.json"], MAX_MEMBER_BYTES),
        }
        header = _obj(_loads(member_bytes["header.json"], "header.json"), "header.json",
                      member="header.json")
        header, provider_ids = _check_header(header)
        frames = _parse_frames(member_bytes["frames.jsonl"], provider_ids)
        markers = _parse_markers(member_bytes["markers.jsonl"])
        manifest = _parse_manifest(member_bytes["manifest.json"], member_bytes, by_name, zf, frames)

    return ReplayArchive(path=archive_path, sha256=archive_sha256, header=header, frames=frames,
                         markers=markers, manifest=manifest,
                         input_trace_size=len(member_bytes["input.inputtrace"]),
                         uncompressed_size=uncompressed_size)


# --------------------------------------------------------------------------- writing

def _manifest_for(members: Mapping[str, bytes], frames: list[dict], *, header: dict,
                  console: dict | None) -> dict:
    body = [row for row in frames if isinstance(row.get("frame"), int) and row["frame"] >= 0]
    ticks = 0
    events = 0
    if body:
        try:
            ticks = max(int(row.get("tick", 0)) for row in body) + 1
            events = max(int(row.get("event_start", 0)) + int(row.get("event_count", 0))
                         for row in body)
        except (TypeError, ValueError):
            ticks = events = 0
    created = header.get("created_utc")
    if not isinstance(created, str):
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tool_version = header.get("tool_version")
    if not isinstance(tool_version, str):
        tool_version = "0.1.0"
    final_hash = frames[-1].get("hash") if frames else ""
    return {
        "format": "gdwreplay-manifest",
        "version": 1,
        "complete": True,
        "frames": len(body),
        "ticks": ticks,
        "events": events,
        "console": dict(console) if console is not None else {"errors": 0, "warnings": 0},
        "final_frame_hash": final_hash,
        "created_utc": created,
        "tool_version": tool_version,
        "files": [
            {"name": name, "bytes": len(members[name]),
             "sha256": hashlib.sha256(members[name]).hexdigest()}
            for name in sorted(members)
        ],
    }


def write_replay(path: str | Path, *, header: dict, frames: Iterable[dict],
                 markers: Iterable[dict] = (), input_trace: bytes = b"",
                 console: dict | None = None, overwrite: bool = False) -> ReplayArchive:
    """Write a test archive atomically (tmp + replace), refusing an existing path unless overwrite."""
    if not isinstance(header, dict):
        raise ReplayFormatError("header must be a JSON object", member="header.json")
    if console is not None and not isinstance(console, Mapping):
        raise ReplayFormatError("console must be a mapping", member="manifest.json")
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"replay archive already exists: {target}")
    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"replay archive path is a directory: {target}")
    try:
        frame_rows = [dict(row) for row in frames]
        marker_rows = [dict(row) for row in markers]
        trace = bytes(input_trace)
    except (TypeError, ValueError) as exc:
        raise ReplayFormatError(f"replay content is not row/bytes shaped: {exc}") from exc
    try:
        header_bytes = canonical_json_bytes(header)
        frames_bytes = b"".join(canonical_json_bytes(row) + b"\n" for row in frame_rows)
        markers_bytes = b"".join(canonical_json_bytes(row) + b"\n" for row in marker_rows)
    except (TypeError, ValueError) as exc:
        raise ReplayFormatError(f"replay content is not JSON encodable: {exc}") from exc
    members = {
        "header.json": header_bytes,
        "input.inputtrace": trace,
        "frames.jsonl": frames_bytes,
        "markers.jsonl": markers_bytes,
    }
    manifest = _manifest_for(members, frame_rows, header=header, console=console)
    try:
        members["manifest.json"] = canonical_json_bytes(manifest)
    except ReplayFormatError:
        raise
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6) as zf:
                for name in ("header.json", "input.inputtrace", "frames.jsonl", "markers.jsonl",
                             "manifest.json"):
                    zf.writestr(name, members[name])
            handle.flush()
            os.fsync(handle.fileno())
        parsed = read_replay(tmp_path)
        if target.exists() and not overwrite:
            raise FileExistsError(f"replay archive already exists: {target}")
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    return replace(parsed, path=target)


# --------------------------------------------------------------------------- hashing

def _encoded_provider_id(provider_id: str) -> bytes:
    if not isinstance(provider_id, str) or not _PROVIDER_ID_RE.match(provider_id):
        raise ValueError(f"invalid provider id: {provider_id!r}")
    return provider_id.encode("utf-8")


def _payload_bytes(payload: Any) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("provider payload must be bytes-like")
    data = bytes(payload)
    if len(data) > 0xFFFFFFFF:
        raise ValueError("provider payload exceeds the 32-bit length field")
    return data


def provider_hash(provider_id: str, payload: bytes) -> str:
    """SHA-256 of one canonical provider block (`id_len|id|payload_len|payload`), lowercase hex."""
    encoded_id = _encoded_provider_id(provider_id)
    data = _payload_bytes(payload)
    block = struct.pack("<I", len(encoded_id)) + encoded_id + struct.pack("<I", len(data)) + data
    return hashlib.sha256(block).hexdigest()


def state_hash(providers: Mapping[str, bytes]) -> str:
    """SHA-256 of the canonical `gdw-replay-state/1` bytes over all provider payloads."""
    if not isinstance(providers, Mapping):
        raise TypeError("providers must be a mapping of provider id to payload")
    ids = sorted(providers)
    if len(set(ids)) != len(ids):  # a Mapping cannot, but be explicit about the contract
        raise ValueError("duplicate provider ids")
    out = [STATE_MAGIC, struct.pack("<H", STATE_ENCODING_VERSION), struct.pack("<I", len(ids))]
    for provider_id in ids:
        encoded_id = _encoded_provider_id(provider_id)
        data = _payload_bytes(providers[provider_id])
        out.append(struct.pack("<I", len(encoded_id)) + encoded_id
                   + struct.pack("<I", len(data)) + data)
    return hashlib.sha256(b"".join(out)).hexdigest()


# --------------------------------------------------------------------------- comparison

def _frame_map(rows: Iterable[dict], side: str) -> list[dict]:
    materialized = list(rows)
    if not materialized:
        raise ReplayFormatError(f"{side} checkpoint list is empty; frame -1 is required")
    validated: list[dict] = []
    for index, row in enumerate(materialized):
        row = _obj(row, f"{side} frame row", member=side, frame=index - 1)
        expected_frame = index - 1
        if row.get("frame") != expected_frame:
            raise ReplayFormatError(
                f"{side} checkpoints must start at frame -1 and be contiguous; "
                f"expected {expected_frame}", member=side, frame=index - 1)
        validated.append(_check_frame_row(dict(row), expected_frame=expected_frame, member=side))
    return validated


def _markers_near(markers: Iterable[dict], frame: int, *, member: str = "markers") -> tuple[dict, ...]:
    candidates: list[tuple[int, int, str, dict]] = []
    for index, marker in enumerate(markers):
        marker = _obj(marker, f"{member}[{index}]", member=member)
        marker_frame = _int(marker.get("frame"), "marker.frame", member=member)
        marker_tick = _int(marker.get("tick"), "marker.tick", member=member, frame=marker_frame)
        label = _str(marker.get("label"), "marker.label", member=member, frame=marker_frame)
        distance = abs(marker_frame - frame)
        if distance <= 5:
            candidates.append((distance, marker_frame,
                               f"{marker_tick:020d}:{label}", {
                                   "frame": marker_frame, "tick": marker_tick, "label": label}))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    chosen = candidates[:10]
    chosen.sort(key=lambda item: (item[1], item[2]))
    return tuple(item[3] for item in chosen)


def compare_checkpoints(expected: Iterable[dict], actual: Iterable[dict], *,
                        markers: Iterable[dict] = ()) -> CheckpointComparison:
    """Compare frame rows by frame number and hash/provider map; report the first divergence.

    Rows are archive `frames.jsonl` rows. `frames_compared` counts every examined checkpoint
    including the initial frame -1; `ticks_compared` sums `fixed_ticks` over examined
    checkpoints after the initial state. A frame present on one side only, a tick mismatch,
    a differing provider map or a differing aggregate hash is a divergence and comparison
    stops there. Only non-contiguous/duplicate rows or a schema violation raise.
    """
    expected_rows = _frame_map(expected, "expected")
    actual_rows = _frame_map(actual, "actual")
    expected_by = {row["frame"]: row for row in expected_rows}
    actual_by = {row["frame"]: row for row in actual_rows}
    marker_rows = list(markers)

    frames_compared = 0
    ticks_compared = 0
    for frame in sorted(set(expected_by) | set(actual_by)):
        expected_row = expected_by.get(frame)
        actual_row = actual_by.get(frame)
        reference = expected_row if expected_row is not None else actual_row
        assert reference is not None
        frames_compared += 1
        if frame >= 0:
            ticks_compared += reference["fixed_ticks"]

        if expected_row is None or actual_row is None:
            expected_providers = set(expected_row["providers"]) if expected_row else set()
            actual_providers = set(actual_row["providers"]) if actual_row else set()
            return CheckpointComparison(
                frames_compared=frames_compared,
                ticks_compared=ticks_compared,
                first_divergent_frame=frame,
                first_divergent_tick=reference["tick"],
                provider_id=None,
                expected_hash=expected_row["hash"] if expected_row else None,
                actual_hash=actual_row["hash"] if actual_row else None,
                missing_provider_ids=tuple(sorted(expected_providers - actual_providers)),
                extra_provider_ids=tuple(sorted(actual_providers - expected_providers)),
                nearby_markers=_markers_near(marker_rows, frame),
            )

        expected_providers = expected_row["providers"]
        actual_providers = actual_row["providers"]
        differing = sorted(
            provider for provider in set(expected_providers) | set(actual_providers)
            if expected_providers.get(provider) != actual_providers.get(provider))
        tick_differs = expected_row["tick"] != actual_row["tick"]
        if not tick_differs and not differing and expected_row["hash"] == actual_row["hash"]:
            continue
        return CheckpointComparison(
            frames_compared=frames_compared,
            ticks_compared=ticks_compared,
            first_divergent_frame=frame,
            first_divergent_tick=expected_row["tick"],
            provider_id=differing[0] if differing else None,
            expected_hash=expected_row["hash"],
            actual_hash=actual_row["hash"],
            missing_provider_ids=tuple(sorted(set(expected_providers) - set(actual_providers))),
            extra_provider_ids=tuple(sorted(set(actual_providers) - set(expected_providers))),
            nearby_markers=_markers_near(marker_rows, frame),
        )

    return CheckpointComparison(
        frames_compared=frames_compared,
        ticks_compared=ticks_compared,
        first_divergent_frame=None,
        first_divergent_tick=None,
        provider_id=None,
        expected_hash=None,
        actual_hash=None,
        missing_provider_ids=(),
        extra_provider_ids=(),
        nearby_markers=(),
    )
