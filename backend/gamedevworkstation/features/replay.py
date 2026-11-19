"""Replay service logic shared by the `unity` tool and the /api/sessions/{sid}/replays routes.

One request flows through `run_replay_op` for both callers: validate and freeze it to request.json,
record through the live Editor (record is live-only), or replay/verify/render through the batch
PlayMode verification test; then assemble the ReplayReport v1 (contract §2) from the archive, the
run's `[HARNESS] REPLAY` lines and Decision 1's environment comparison, and write it atomically
without ever replacing a report Unity wrote. Async REST mutations return 202 {job_id, run_id,
status_url}. The archive and report formats live in replay_format.py and are never redefined here.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import platform
import re
import secrets
import subprocess
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..agent.tools import ToolOutput

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

    from ..app import AppState
    from .unity_bridge import BridgeResult

log = logging.getLogger(__name__)

# Contract §6: the frozen dispatcher ops (stop/status need only a run_id).
REPLAY_OPS = ("record", "stop", "status", "replay", "verify", "render")
_MUTATING_OPS = ("record", "replay", "verify", "render")
_CHANGE_OPS = {"record", "replay", "render"}
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
_FORMATS = ("mp4", "gif")
_CAPTURE_BACKENDS = ("auto", "recorder", "png")
_CAPTURE_KEYS = {"formats", "backend", "start_frame", "end_frame_exclusive", "width", "height", "fps"}
_CONTRACT_STATUSES = ("pass", "diverged", "incompatible", "error", "cancelled")
_STATUS_RANK = {"pass": 0, "diverged": 1, "error": 2, "incompatible": 3, "cancelled": 4}
_HARNESS_TAG = "[HARNESS] REPLAY "
_MAX_REPORT_MESSAGE = 500
_MAX_SUBJECTS = 32
_MAX_SUBJECT_CHARS = 128
_MAX_FRACTION_DEN = 1_000_000


class ReplayOpError(Exception):
    """A refused or failed replay operation, carrying the REST/tool error code and status."""

    def __init__(self, code: str, message: str, *, http_status: int = 400,
                 job_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.job_id = job_id


# --------------------------------------------------------------------------- validation


def _cfg_int(cfg: dict, key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def _project_relative(value: Any, *, field: str, suffix: str, prefix: str | None = None) -> str:
    """A project-relative POSIX path per the contract (no absolute paths, `.`, `..` or `\\`)."""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise ReplayOpError("bad_" + field, f"{field} must be a project-relative path")
    if text.startswith("/") or text.startswith("~") or re.match(r"^[A-Za-z]:", text):
        raise ReplayOpError("bad_" + field, f"{field} must be project-relative, got {text!r}")
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ReplayOpError("bad_" + field, f"{field} must not contain '.', '..' or empty segments")
    if prefix and not text.startswith(prefix):
        raise ReplayOpError("bad_" + field, f"{field} must start with {prefix!r}, got {text!r}")
    if suffix and not text.endswith(suffix):
        raise ReplayOpError("bad_" + field, f"{field} must end with {suffix!r}, got {text!r}")
    return text


def _as_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            return int(value)
        raise ReplayOpError("bad_" + field, f"{field} must be an integer, got {value!r}")
    return value


def _rational(value: Any, *, field: str = "fixed_dt") -> dict[str, int]:
    """Contract §1: a reduced positive rational in [0.001, 1.0] with den <= 1_000_000."""
    if isinstance(value, dict):
        if set(value) != {"num", "den"}:
            raise ReplayOpError("bad_" + field, f"{field} must be {{num, den}}")
        num = _as_int(value["num"], field=field)
        den = _as_int(value["den"], field=field)
        if den <= 0:
            raise ReplayOpError("bad_" + field, f"{field}.den must be positive")
        if math.gcd(abs(num), den) != 1:
            raise ReplayOpError("bad_" + field, f"{field} must be a reduced fraction, got {{num: {num}, den: {den}}}")
    elif isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ReplayOpError("bad_" + field, f"{field} must be a number")
    else:
        try:
            fraction = Fraction(str(value)).limit_denominator(_MAX_FRACTION_DEN)
        except (ValueError, ZeroDivisionError) as exc:
            raise ReplayOpError("bad_" + field, f"{field} must be a number") from exc
        num, den = fraction.numerator, fraction.denominator
    if den > _MAX_FRACTION_DEN:
        raise ReplayOpError("bad_" + field, f"{field}.den must be <= {_MAX_FRACTION_DEN}")
    if num <= 0 or not (0.001 <= num / den <= 1.0):
        raise ReplayOpError("bad_" + field, f"{field} must be between 0.001 and 1.0 seconds, got {num}/{den}")
    return {"num": num, "den": den}


def _validated_capture(capture: Any, *, replay_cfg: dict) -> dict:
    if not isinstance(capture, dict):
        raise ReplayOpError("bad_capture", "capture must be an object")
    unknown = set(capture) - _CAPTURE_KEYS
    if unknown:
        raise ReplayOpError("bad_capture", f"capture has unknown field(s): {', '.join(sorted(unknown))}")
    cap = dict(capture)

    formats = cap.get("formats")
    if not isinstance(formats, list) or not formats:
        raise ReplayOpError("bad_capture_formats", "capture.formats is required and must be non-empty")
    if any(f not in _FORMATS for f in formats):
        raise ReplayOpError("bad_capture_formats", "capture.formats may only contain 'mp4' and 'gif'")
    if len(set(formats)) != len(formats):
        raise ReplayOpError("bad_capture_formats", "capture.formats must be unique")
    cap["formats"] = list(formats)

    backend = cap.get("backend", "auto")
    if backend not in _CAPTURE_BACKENDS:
        raise ReplayOpError("bad_capture_backend",
                            f"capture.backend must be one of {', '.join(_CAPTURE_BACKENDS)}")
    cap["backend"] = backend

    start = _as_int(cap.get("start_frame", 0), field="capture.start_frame")
    if start < 0:
        raise ReplayOpError("bad_capture_range", "capture.start_frame must be >= 0")
    cap["start_frame"] = start

    if cap.get("end_frame_exclusive") is not None:
        end = _as_int(cap["end_frame_exclusive"], field="capture.end_frame_exclusive")
        if end <= start:
            raise ReplayOpError("bad_capture_range",
                                "capture.end_frame_exclusive must be greater than capture.start_frame")
        cap["end_frame_exclusive"] = end

    for key, hi in (("width", 1920), ("height", 1080)):
        value = cap.get(key, 1280 if key == "width" else 720)
        value = _as_int(value, field=f"capture.{key}")
        if not 16 <= value <= hi:
            raise ReplayOpError("bad_capture_size", f"capture.{key} must be 16-{hi}")
        if value % 2:
            raise ReplayOpError("bad_capture_size", f"capture.{key} must be even, got {value}")
        cap[key] = value

    fps = _as_int(cap.get("fps", 60), field="capture.fps")
    if not 1 <= fps <= 60:
        raise ReplayOpError("bad_capture_fps", "capture.fps must be 1-60")
    cap["fps"] = fps

    # [unity.replay] limits (L3): bound the requested export window when it is known here.
    if cap.get("end_frame_exclusive") is not None:
        duration = (int(cap["end_frame_exclusive"]) - start) / fps
        max_capture = _cfg_int(replay_cfg, "capture_max_seconds", 120)
        if max_capture > 0 and duration > max_capture:
            raise ReplayOpError("bad_capture_range",
                                f"capture range is {duration:.1f}s; [unity.replay] capture_max_seconds is {max_capture}")
        if "gif" in cap["formats"]:
            gif_max = _cfg_int(replay_cfg, "gif_max_seconds", 8)
            if gif_max > 0 and duration > gif_max:
                raise ReplayOpError("bad_capture_range",
                                    f"capture range is {duration:.1f}s; GIFs are limited to {gif_max}s "
                                    "by [unity.replay] gif_max_seconds")
    return cap


def _validated_request(op: str, args: dict, *, replay_cfg: dict | None = None) -> dict:
    """Validate and freeze a ReplayRequest v1 (contracts §1); raise ReplayOpError on bad args."""
    cfg = replay_cfg or {}
    if op not in _MUTATING_OPS:
        raise ReplayOpError("bad_op", f"unknown replay op {op!r}")
    request: dict[str, Any] = {"schema": "gdw.replay.request/1", "op": op}

    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        if op != "record":
            raise ReplayOpError("missing_run_id", "run_id is required")
        run_id = f"rr_{secrets.token_hex(8)}"
    if not _RUN_ID_RE.match(run_id):
        raise ReplayOpError("bad_run_id",
                            f"run_id must match {_RUN_ID_RE.pattern}, got {run_id!r}")
    request["run_id"] = run_id

    replay_path = str(args.get("replay_path") or "").strip()
    if op == "record":
        if replay_path:
            raise ReplayOpError("bad_replay_path", "replay_path isn't used for record")
    else:
        replay_path = replay_path or f"Logs/harness/replay/{run_id}/run.gdwreplay"
        request["replay_path"] = _project_relative(replay_path, field="replay_path", suffix=".gdwreplay")

    if args.get("scene") is not None:
        request["scene"] = _project_relative(args["scene"], field="scene", suffix=".unity", prefix="Assets/")

    seed = args.get("seed")
    if seed is not None:
        seed = _as_int(seed, field="seed")
        if not 0 <= seed <= 0xFFFFFFFF:
            raise ReplayOpError("bad_seed", f"seed must be a uint32 (0-4294967295), got {seed}")
        request["seed"] = seed

    fixed_dt = args.get("fixed_dt")
    if fixed_dt is None:
        fixed_dt = cfg.get("fixed_dt")
    request["fixed_dt"] = _rational(fixed_dt if fixed_dt is not None else 1 / 60)

    subjects = args.get("subjects")
    if subjects is not None:
        if not isinstance(subjects, list) or not all(isinstance(s, str) for s in subjects):
            raise ReplayOpError("bad_subjects", "subjects must be an array of strings")
        if len(subjects) > _MAX_SUBJECTS:
            raise ReplayOpError("bad_subjects", f"subjects may list at most {_MAX_SUBJECTS} entries")
        if any(len(s) > _MAX_SUBJECT_CHARS for s in subjects):
            raise ReplayOpError("bad_subjects", f"each subject must be at most {_MAX_SUBJECT_CHARS} characters")
        if len(set(subjects)) != len(subjects):
            raise ReplayOpError("bad_subjects", "subjects must be unique")
        request["subjects"] = list(subjects)

    capture = args.get("capture")
    if capture is None:
        if op == "render":
            raise ReplayOpError("missing_capture", "render needs capture ({formats: ['mp4'] | ['gif']})")
    else:
        request["capture"] = _validated_capture(capture, replay_cfg=cfg)
    return request


def _validated_run_id(value: Any) -> str:
    run_id = str(value or "").strip()
    if not run_id:
        raise ReplayOpError("missing_run_id", "run_id is required")
    if not _RUN_ID_RE.match(run_id):
        raise ReplayOpError("bad_run_id", f"run_id must match {_RUN_ID_RE.pattern}, got {run_id!r}")
    return run_id


# --------------------------------------------------------------------------- paths and freeze


def _replay_output_dir(root: Path, run_id: str) -> Path:
    return root / "Logs" / "harness" / "replay" / run_id


def _check_project_ownership(root: Path, session: dict) -> str | None:
    """Return an error message if the session's project doesn't contain the run root."""
    folder = session.get("folder")
    if not folder:
        return "Session has no folder"
    resolved = Path(folder).expanduser().resolve()
    try:
        if not root.resolve().is_relative_to(resolved):
            return "Replay path is outside the session's project"
    except ValueError:
        return "Replay path is outside the session's project"
    return None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _request_digest(request: dict) -> str:
    body = {k: v for k, v in request.items() if not k.startswith("_")}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _freeze_request(request: dict, root: Path) -> Path:
    """Write the frozen request.json atomically and return its path."""
    out_dir = _replay_output_dir(root, request["run_id"])
    req_path = out_dir / "request.json"
    _atomic_write(req_path, (json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())
    return req_path


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _rel_posix(root: Path, path: Path | str | None) -> str:
    if not path:
        return ""
    p = Path(path).expanduser()
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


# --------------------------------------------------------------------------- archive + environment


def _read_archive(root: Path, request: dict, replay_cfg: dict) -> tuple[Any, str | None, str]:
    """Read the request's archive. (archive, error_status, message); error_status None on success."""
    from . import replay_format

    rel = request.get("replay_path")
    if not rel:
        return None, "error", "No replay_path in the request"
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        return None, "error", f"replay_path escapes the project: {rel}"
    if not path.is_file():
        return None, "error", f"Replay archive not found: {rel}"
    limit = min(_cfg_int(replay_cfg, "max_archive_mb", 512) * 1024 * 1024, replay_format.MAX_ARCHIVE_BYTES)
    if limit <= 0:
        limit = replay_format.MAX_ARCHIVE_BYTES
    if path.stat().st_size > limit:
        return None, "incompatible", (f"Replay archive is larger than [unity.replay] max_archive_mb "
                                      f"({limit // (1024 * 1024)} MiB)")
    try:
        return replay_format.read_replay(path, max_bytes=limit), None, ""
    except replay_format.ReplayFormatError as exc:
        return None, "incompatible", f"Replay archive is unusable: {exc}"
    except OSError as exc:
        return None, "error", f"Couldn't read the replay archive: {exc}"


def _compat_error(request: dict, archive: Any) -> str | None:
    """Contract §1: a non-record request's scene/seed must equal the archive header's."""
    header = archive.header if isinstance(archive.header, dict) else {}
    scene = (header.get("scene") or {}).get("path") if isinstance(header.get("scene"), dict) else None
    if request.get("scene") and scene and request["scene"] != scene:
        return f"scene {request['scene']} doesn't match the archive's scene {scene}"
    if request.get("seed") is not None:
        try:
            recorded = int(header.get("seed"))
        except (TypeError, ValueError):
            recorded = None
        if recorded is not None and recorded != request["seed"]:
            return f"seed {request['seed']} doesn't match the archive's seed {recorded}"
    return None


def _read_text(path: Path, cap: int = 4_000_000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - cap))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _local_platform_name() -> str:
    name = platform.system()
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(name, name)


def _local_cpu_model() -> str | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=2)
            model = out.stdout.strip()
            return model or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _project_unity_version(root: Path) -> str | None:
    try:
        text = (root / "ProjectSettings" / "ProjectVersion.txt").read_text(errors="replace", encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^m_EditorVersion:\s*(\S+)", text, re.M)
    return m.group(1) if m else None


def _manifest_dependencies(root: Path) -> dict[str, str] | None:
    try:
        data = json.loads((root / "Packages" / "manifest.json").read_text(errors="replace", encoding="utf-8"))
    except (OSError, ValueError):
        return None
    deps = data.get("dependencies") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in deps.items()} if isinstance(deps, dict) else None


def _project_identifier(root: Path) -> str | None:
    try:
        text = (root / "ProjectSettings" / "ProjectSettings.asset").read_text(errors="replace", encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^\s*applicationIdentifier:\s*\n\s+[A-Za-z]+:\s*(\S+)", text, re.M)
    if not m:
        m = re.search(r"^\s*applicationIdentifier:\s*(\S+)", text, re.M)
    return m.group(1) if m else None


def _scene_guid(root: Path, scene_path: str | None) -> str | None:
    if not scene_path:
        return None
    try:
        text = (root / f"{scene_path}.meta").read_text(errors="replace", encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^guid:\s*([0-9a-fA-F]{32})\s*$", text, re.M)
    return m.group(1).lower() if m else None


def environment_diff(root: Path, header: dict | None, *, scene_hint: str | None = None) -> list[str]:
    """Decision 1: which recorded environment fields this project/machine no longer matches.

    Only fields the archive actually filled and the backend can determine without launching Unity
    are compared; an unset header field is unknown, never a difference. Environment differences
    never make a report `incompatible` (Decision 1).
    """
    header = header if isinstance(header, dict) else {}
    diff: set[str] = set()

    unity = header.get("unity") if isinstance(header.get("unity"), dict) else {}
    recorded_version = str(unity.get("version") or "")
    current_version = _project_unity_version(root)
    if recorded_version and current_version and recorded_version != current_version:
        diff.add("unity_version")

    os_info = header.get("os") if isinstance(header.get("os"), dict) else {}
    recorded_platform = str(os_info.get("platform") or "")
    current_platform = _local_platform_name()
    if recorded_platform and current_platform and current_platform.lower() not in recorded_platform.lower():
        diff.add("os")

    cpu = header.get("cpu") if isinstance(header.get("cpu"), dict) else {}
    try:
        recorded_cores = int(cpu.get("cores")) if cpu.get("cores") is not None else None
    except (TypeError, ValueError):
        recorded_cores = None
    if recorded_cores and os.cpu_count() and recorded_cores != os.cpu_count():
        diff.add("cpu")
    recorded_model = str(cpu.get("model") or "").strip()
    current_model = _local_cpu_model()
    if recorded_model and current_model and recorded_model != current_model:
        diff.add("cpu")
    recorded_arch = str(cpu.get("architecture") or "").strip()
    current_arch = platform.machine().lower()
    if recorded_arch and current_arch and recorded_arch.lower() != current_arch:
        diff.add("cpu")

    project = header.get("project") if isinstance(header.get("project"), dict) else {}
    recorded_id = str(project.get("id") or "")
    current_id = _project_identifier(root)
    if recorded_id and current_id and recorded_id != current_id:
        diff.add("project_id")

    scene = header.get("scene") if isinstance(header.get("scene"), dict) else {}
    recorded_guid = str(scene.get("guid") or "").lower()
    scene_path = str(scene.get("path") or scene_hint or "")
    current_guid = _scene_guid(root, scene_path)
    if recorded_guid and current_guid and recorded_guid != current_guid:
        diff.add("scene_guid")

    packages = header.get("packages") if isinstance(header.get("packages"), dict) else {}
    recorded_versions = packages.get("versions") if isinstance(packages.get("versions"), dict) else {}
    current_deps = _manifest_dependencies(root)
    if recorded_versions and current_deps is not None:
        for package_id, version in recorded_versions.items():
            if str(current_deps.get(str(package_id), "")) != str(version):
                diff.add("package_versions")
                break
    recorded_lock = str(packages.get("lock_sha256") or "")
    if recorded_lock:
        lock_path = root / "Packages" / "packages-lock.json"
        current_lock = _sha256_file(lock_path)
        if current_lock is None or current_lock != recorded_lock:
            diff.add("package_lock")

    return sorted(diff)


# --------------------------------------------------------------------------- report assembly


def _harness_events(text: str) -> list[dict]:
    events: list[dict] = []
    for line in (text or "").splitlines():
        idx = line.find(_HARNESS_TAG)
        if idx < 0:
            continue
        payload = line[idx + len(_HARNESS_TAG):].strip()
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _last_harness(events: list[dict]) -> dict | None:
    for event in reversed(events):
        if str(event.get("event") or "") != "progress":
            return event
    return events[-1] if events else None


def _merge_status(*statuses: str) -> str:
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, _STATUS_RANK["error"]))


def _bridge_status(result: "BridgeResult", harness: dict | None) -> str:
    if result.status == "pass":
        status = "pass"
    elif result.status == "fail":
        status = "diverged"
    elif result.status == "skipped" and "cancel" in (result.summary or "").lower():
        status = "cancelled"
    else:
        status = "error"
    if harness:
        reported = str(harness.get("status") or "")
        if reported in _CONTRACT_STATUSES:
            status = _merge_status(status, reported)
    return status


def _run_log_text(result: "BridgeResult") -> str:
    evidence = result.evidence or {}
    log_path = evidence.get("log")
    if log_path:
        text = _read_text(Path(str(log_path)))
        if text:
            return text
    return str(evidence.get("log_text") or result.report or "")


def _actual_frames(out_dir: Path) -> list[dict] | None:
    """Checkpoints a run wrote back (the Unity side may store them; absent today for verify)."""
    from . import replay_format

    for name in ("actual.gdwreplay", "replayed.gdwreplay"):
        path = out_dir / name
        if path.is_file():
            try:
                return replay_format.read_replay(path).frames
            except replay_format.ReplayFormatError:
                return None
    return None


def _utc(epoch: float | None) -> str:
    ts = float(epoch if epoch is not None else time.time())
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_existing_report(path: Path) -> dict | None:
    """A report someone else (the Unity package) already wrote is never replaced."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == "gdw.replay.report/1" else None


def _artifact_paths(root: Path, out_dir: Path, request: dict, result: "BridgeResult") -> dict:
    evidence = result.evidence or {}
    capture = out_dir / "capture"
    exports = sorted(
        _rel_posix(root, p) for p in out_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".mp4", ".gif")
    )
    return {
        "archive": request.get("replay_path") or "",
        "report": _rel_posix(root, out_dir / "report.json"),
        "results_xml": _rel_posix(root, evidence.get("xml")) if evidence.get("xml") else "",
        "editor_log": _rel_posix(root, evidence.get("log")) if evidence.get("log") else "",
        "capture_dir": _rel_posix(root, capture) if capture.is_dir() else "",
        "exports": exports,
    }


def build_replay_report(root: Path, run_id: str, op: str, request: dict, result: "BridgeResult",
                        *, archive: Any | None = None, replay_cfg: dict | None = None,
                        status_override: str | None = None) -> dict | None:
    """Assemble ReplayReport v1 (contract §2), write it atomically, and return it.

    Never writes over an existing valid report (the Unity package owns that file). Returns None
    when the op didn't run (skipped) and there is nothing to report.
    """
    from . import replay_format

    out_dir = _replay_output_dir(root, run_id)
    report_path = out_dir / "report.json"
    existing = _read_existing_report(report_path)
    if existing is not None:
        return existing
    if status_override is None and result.status == "skipped":
        return None

    cfg = replay_cfg or {}
    if archive is None and request.get("replay_path"):
        archive, _archive_error, _message = _read_archive(root, request, cfg)

    header = archive.header if archive is not None and isinstance(archive.header, dict) else {}
    manifest = archive.manifest if archive is not None and isinstance(archive.manifest, dict) else {}
    log_text = _run_log_text(result)
    events = _harness_events(log_text)
    harness = _last_harness(events)
    divergence = next((e for e in reversed(events) if str(e.get("event") or "") == "divergence"), None)

    notes: list[str] = []
    status = status_override or _bridge_status(result, harness)
    if status == "incompatible":
        notes.append("the replay can't run against this request")

    if archive is not None:
        compat = _compat_error(request, archive)
        if compat:
            status = _merge_status(status, "incompatible")
            notes.append(compat)

    # Comparison: real checkpoints when the run wrote them back, else the harness/result counts.
    comparison = None
    frames_expected = int(manifest.get("frames") or 0) if manifest else 0
    ticks_expected = int(manifest.get("ticks") or 0) if manifest else 0
    frames_compared = 0
    ticks_compared = 0
    first_divergent_frame: int | None = None
    first_divergent_tick: int | None = None
    provider_id = None
    expected_hash = None
    actual_hash = None
    missing_providers: list[str] = []
    extra_providers: list[str] = []
    nearby_markers: list[dict] = []

    actual = _actual_frames(out_dir) if archive is not None else None
    if archive is not None and actual is not None:
        try:
            comparison = replay_format.compare_checkpoints(archive.frames, actual, markers=archive.markers)
        except replay_format.ReplayFormatError as exc:
            notes.append(f"checkpoint comparison failed: {exc}")
            status = _merge_status(status, "error")
    if comparison is not None:
        frames_compared = comparison.frames_compared
        ticks_compared = comparison.ticks_compared
        first_divergent_frame = comparison.first_divergent_frame
        first_divergent_tick = comparison.first_divergent_tick
        provider_id = comparison.provider_id
        expected_hash = comparison.expected_hash
        actual_hash = comparison.actual_hash
        missing_providers = sorted(comparison.missing_provider_ids)
        extra_providers = sorted(comparison.extra_provider_ids)
        nearby_markers = list(comparison.nearby_markers)[:10]
        if comparison.first_divergent_frame is not None:
            status = _merge_status(status, "diverged")
        else:
            frames_compared = frames_compared or frames_expected
            ticks_compared = ticks_compared or ticks_expected
    else:
        try:
            frames_compared = int(harness.get("frame")) if harness and harness.get("frame") is not None else 0
        except (TypeError, ValueError):
            frames_compared = 0
        try:
            ticks_compared = int(harness.get("tick")) if harness and harness.get("tick") is not None else 0
        except (TypeError, ValueError):
            ticks_compared = 0
        if harness:
            provider_id = harness.get("provider_id") or None
            expected_hash = harness.get("expected_hash") or None
            actual_hash = harness.get("actual_hash") or None
        if divergence is not None:
            try:
                first_divergent_frame = int(divergence.get("frame"))
                first_divergent_tick = int(divergence.get("tick"))
            except (TypeError, ValueError):
                pass
        if not frames_compared and status == "pass" and archive is not None:
            frames_compared = frames_expected
            ticks_compared = ticks_expected

    console_warnings = 0
    try:
        console_warnings = int((manifest.get("console") or {}).get("warnings") or 0)
    except (TypeError, ValueError, AttributeError):
        console_warnings = 0
    console_errors = 0
    if status != "pass":
        console_errors = int(result.errors or 0)

    # `pass` needs a complete manifest, a full comparison and no console errors (contract §2).
    if status == "pass":
        if archive is None or not manifest.get("complete"):
            status = "error"
            notes.append("pass needs a complete replay archive")
        elif frames_compared != frames_expected:
            status = "error"
            notes.append(f"compared {frames_compared} of {frames_expected} frames")
        elif ticks_expected and ticks_compared < ticks_expected:
            status = "error"
            notes.append(f"compared {ticks_compared} of {ticks_expected} ticks")
        elif console_errors:
            status = "error"
            notes.append(f"{console_errors} console error(s)")

    environment: list[str] = []
    if archive is not None:
        environment = environment_diff(root, header, scene_hint=request.get("scene"))

    summary = str(result.summary or "")
    if harness and harness.get("message"):
        summary = str(harness["message"])
    message = "; ".join([n for n in notes if n] + ([summary] if summary else []))[:_MAX_REPORT_MESSAGE]

    started = result.evidence.get("started_at") if isinstance(result.evidence, dict) else None
    try:
        started_epoch = float(started) if started is not None else time.time()
    except (TypeError, ValueError):
        started_epoch = time.time()

    header_sha = ""
    if archive is not None:
        for entry in manifest.get("files") or []:
            if isinstance(entry, dict) and entry.get("name") == "header.json":
                header_sha = str(entry.get("sha256") or "")
                break

    report = {
        "schema": "gdw.replay.report/1",
        "run_id": run_id,
        "op": op,
        "request_digest": _request_digest(request),
        "replay_sha256": archive.sha256 if archive is not None else "",
        "header_sha256": header_sha,
        "log_sha256": (_sha256_file(Path(str(result.evidence["log"])))
                       if isinstance(result.evidence, dict) and result.evidence.get("log") else ""),
        "content_sha256": str((header.get("project") or {}).get("content_sha256") or "")
                          if isinstance(header.get("project"), dict) else "",
        "route": result.mode or str((result.evidence or {}).get("route") or ""),
        "status": status,
        "environment": "differs" if environment else "matched",
        "environment_diff": environment,
        "frames": {"expected": frames_expected, "compared": frames_compared},
        "ticks": {"expected": ticks_expected, "compared": ticks_compared},
        "first_divergent_frame": first_divergent_frame,
        "first_divergent_tick": first_divergent_tick,
        "provider_id": provider_id,
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "missing_provider_ids": missing_providers,
        "extra_provider_ids": extra_providers,
        "nearby_markers": nearby_markers,
        "console": {"errors": console_errors, "warnings": console_warnings},
        "artifacts": _artifact_paths(root, out_dir, request, result),
        "message": message,
        "started_utc": _utc(started_epoch),
        "ended_utc": _utc(time.time()),
    }
    _atomic_write(report_path, (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())
    return report


# --------------------------------------------------------------------------- items + evidence


def _index_artifacts(app: "AppState", session: dict, paths: list[Path]) -> None:
    """Index the frozen request, report and archive as items (outputs are indexed); best effort."""
    try:
        items = getattr(app, "items", None)
        if items is None:
            return
        for path in paths:
            if path and Path(path).is_file():
                items.add_file(path, source="replay", session_id=session["id"], provider=None, model=None)
    except Exception:  # noqa: BLE001 — indexing is best effort
        log.debug("replay: couldn't index artifacts", exc_info=True)


def _record_replay_evidence(app: "AppState", session: dict, request: dict, report: dict) -> None:
    """L3 replay_verified evidence from a verify report (ladder.py reads detail.kind)."""
    lad = app.extensions.get("ladder")
    if lad is None:
        return
    try:
        try:
            ts = datetime.strptime(report.get("started_utc") or "", "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            ts = time.time()
        frames = report.get("frames") or {}
        lad.record_evidence(
            session["folder"], "L3", "pass" if report.get("status") == "pass" else "fail",
            source=f"replay:{report.get('route') or 'batch'}", observed="tool",
            subjects=request.get("subjects") or [], session_id=session["id"],
            path=(report.get("artifacts") or {}).get("report"), ts=ts,
            detail={"kind": "replay_verified", "report": report,
                    "summary": f"replay {report.get('status')}, {frames.get('compared', 0)} frames"})
    except Exception:  # noqa: BLE001 — evidence is best effort
        log.warning("replay: couldn't record replay_verified evidence", exc_info=True)


# --------------------------------------------------------------------------- tool output


def _tool_output(op: str, run_id: str, result: "BridgeResult | None", report: dict | None) -> ToolOutput:
    status = (report or {}).get("status") or (result.status if result is not None else "error")
    summary = (report or {}).get("message") or (result.summary if result is not None else "")
    route = (result.mode if result is not None else "") or (report or {}).get("route") or ""
    head: dict[str, Any] = {"op": op, "run_id": run_id, "route": route, "status": status,
                            "summary": summary}
    if report is not None:
        head["report"] = report
    text = f"Replay {op}: {status}. {summary}\n" + json.dumps(head, default=str, indent=1)[:8000]
    is_error = bool(result is not None and result.status in ("error", "skipped")) or status in ("error", "incompatible")
    return ToolOutput(text, is_error=is_error)


# --------------------------------------------------------------------------- ops

_WATCHDOGS: set[asyncio.Task] = set()


def _arm_record_limit(app: "AppState", session: dict, run_id: str, replay_cfg: dict) -> asyncio.Task | None:
    """[unity.replay] max_seconds: stop a live recording that runs past the limit (L3)."""
    limit = _cfg_int(replay_cfg, "max_seconds", 600)
    if limit <= 0:
        return None

    async def _watch() -> None:
        await asyncio.sleep(limit)
        try:
            from .unity_bridge import get_bridge
            await get_bridge(app).replay_cancel(session, consent=_gate_consent(app, session))
            log.info("replay: recording %s stopped at [unity.replay] max_seconds=%s", run_id, limit)
        except Exception:  # noqa: BLE001 — best effort
            log.debug("replay: max_seconds stop failed", exc_info=True)

    task = asyncio.create_task(_watch())
    _WATCHDOGS.add(task)
    task.add_done_callback(_WATCHDOGS.discard)
    return task



async def _op_stop(app: "AppState", session: dict, root: Path, run_id: str, br: Any) -> ToolOutput:
    """Stop the job for this run_id and cancel any live Editor replay session."""
    stopped_job = None
    for job in app.jobs.list() or []:
        if job.get("id") and job.get("status") in ("running", "queued") \
                and (job.get("meta") or {}).get("run_id") == run_id:
            if await app.jobs.cancel(job["id"]):
                stopped_job = job["id"]
            break
    cancelled = False
    try:
        result = await br.replay_cancel(session, consent=_gate_consent(app, session))
        cancelled = result.status == "pass"
        if result.status not in ("pass", "skipped"):
            log.info("replay: Unity cancel for %s returned %s: %s", run_id, result.status, result.summary)
    except Exception:  # noqa: BLE001 — the job cancellation above already happened
        log.debug("replay: Unity cancel failed", exc_info=True)
    # A Unity session is only "ours" if this run left a directory behind; otherwise Cancel() on an
    # idle Editor must not turn a stop for an unknown run into a success.
    known = _replay_output_dir(root, run_id).is_dir() or any(
        (candidate.get("meta") or {}).get("run_id") == run_id for candidate in app.jobs.list() or [])
    if stopped_job or (cancelled and known):
        what = ", ".join(x for x in (f"job {stopped_job}" if stopped_job else "",
                                     "Unity session cancelled" if cancelled else "") if x)
        return ToolOutput(f"Replay {run_id}: stopped ({what}).")
    return ToolOutput(f"Replay {run_id}: no running replay found.")


async def _op_status(app: "AppState", session: dict, root: Path, run_id: str, br: Any) -> ToolOutput:
    """Status of a run: report, archive, job and (while one runs) the live Editor session."""
    out_dir = _replay_output_dir(root, run_id)
    parts: list[str] = []
    report_path = out_dir / "report.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(errors="replace", encoding="utf-8"))
            parts.append(f"report: {report.get('status', 'unknown')}")
            if report.get("environment") == "differs":
                parts.append("environment: differs (" + ", ".join(report.get("environment_diff") or []) + ")")
        except (OSError, ValueError):
            parts.append("report: unreadable")
    else:
        parts.append("report: none")
    archive_path = out_dir / "run.gdwreplay"
    if archive_path.is_file():
        parts.append(f"archive: {archive_path.stat().st_size} bytes")
    else:
        parts.append("archive: not found")
    job = None
    for candidate in app.jobs.list() or []:
        if (candidate.get("meta") or {}).get("run_id") == run_id:
            job = candidate
            break
    if job:
        parts.append(f"job {job['id']}: {job.get('status')}")
        if job.get("status") in ("running", "queued"):
            try:
                live = await br.replay_status(session, consent=_gate_consent(app, session))
                if live.status == "pass":
                    parts.append(f"Unity: {(live.report or live.summary).strip()[-300:]}")
            except Exception:  # noqa: BLE001 — the file/job status still answers
                log.debug("replay: live status failed", exc_info=True)
    warning = _size_warning(root, br.cfg().get("replay") or {})
    if warning:
        parts.append(warning)
    parts.append(f"dir: {_rel_posix(root, out_dir)}")
    return ToolOutput(f"Replay {run_id}: " + "; ".join(parts))


def _size_warning(root: Path, replay_cfg: dict) -> str:
    """[unity.replay] warn_total_mb: status warns when this project's replay output is too large."""
    limit_mb = _cfg_int(replay_cfg, "warn_total_mb", 2048)
    base = root / "Logs" / "harness" / "replay"
    if limit_mb <= 0 or not base.is_dir():
        return ""
    total = 0
    try:
        for path in base.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
    except OSError:
        return ""
    if total <= limit_mb * 1024 * 1024:
        return ""
    return f"warning: Logs/harness/replay/ is {total / (1024 * 1024):.0f} MiB (limit {limit_mb} MiB)"


def _gate_consent(app: "AppState", session: dict) -> dict[str, set[str]]:
    """The unity gates' preset consent for this project (shared with the unity tool)."""
    try:
        from .unity_tool import gate_consent
        return gate_consent(app, session)
    except Exception:  # noqa: BLE001 — no consent is the safe answer
        log.debug("replay: couldn't read gate consent", exc_info=True)
        return {}


async def run_replay_op(app: "AppState", session: dict, op: str, args: dict,
                        *, cancel: asyncio.Event | None = None) -> ToolOutput:
    """Validate and run one replay op for the session (the unity tool and REST share this path)."""
    from .unity_bridge import BridgeResult, get_bridge, is_unity_project

    session = app.store.get(session["id"])
    if session is None:
        return ToolOutput("The session no longer exists.", is_error=True)
    if op not in REPLAY_OPS:
        return ToolOutput(f"Unknown replay op {op!r}. ops: {', '.join(REPLAY_OPS)}", is_error=True)
    folder = session.get("folder")
    if not folder:
        return ToolOutput("Session has no folder.", is_error=True)
    root = Path(folder).expanduser().resolve()
    if not is_unity_project(root):
        return ToolOutput("This session's folder isn't a Unity project "
                          "(no ProjectSettings/ProjectVersion.txt).", is_error=True)
    if problem := _check_project_ownership(root, session):
        return ToolOutput(problem, is_error=True)
    args = dict(args or {})
    br = get_bridge(app)
    replay_cfg = br.cfg().get("replay") or {}

    try:
        if op in ("stop", "status"):
            run_id = _validated_run_id(args.get("run_id"))
        else:
            request = _validated_request(op, args, replay_cfg=replay_cfg)
            run_id = request["run_id"]
    except ReplayOpError as exc:
        return ToolOutput(f"Replay {op}: {exc}", is_error=True)

    if op in ("stop", "status"):
        if op == "stop":
            return await _op_stop(app, session, root, run_id, br)
        return await _op_status(app, session, root, run_id, br)

    mode = session.get("mode", "ask")
    capture = request.get("capture")
    if mode == "plan" and (op in _CHANGE_OPS or (op == "verify" and capture)):
        return ToolOutput(f"Plan only mode: replay {op} isn't run. Describe it instead.", is_error=True)

    request_path = _freeze_request(request, root)
    out_dir = _replay_output_dir(root, run_id)
    consent = _gate_consent(app, session)

    if op == "record":
        result = await br.run_replay(session, op, {**request, "_request_path": str(request_path)},
                                     consent=consent, cancel=cancel)
        if result.status == "pass":
            _index_artifacts(app, session, [request_path])
            _arm_record_limit(app, session, run_id, replay_cfg)
        return _tool_output(op, run_id, result, None)

    archive, precheck_status, precheck_message = _read_archive(root, request, replay_cfg)
    if archive is not None:
        compat = _compat_error(request, archive)
        if compat:
            precheck_status, precheck_message = "incompatible", compat
    if precheck_status is not None:
        synthetic = BridgeResult("error", precheck_message, "")
        report = build_replay_report(root, run_id, op, request, synthetic, archive=archive,
                                     replay_cfg=replay_cfg, status_override=precheck_status)
        _index_artifacts(app, session, [request_path, out_dir / "report.json"])
        return _tool_output(op, run_id, synthetic, report)

    result = await br.run_replay(session, op, {**request, "_request_path": str(request_path)},
                                 consent=consent, cancel=cancel)
    report = build_replay_report(root, run_id, op, request, result, archive=archive, replay_cfg=replay_cfg)
    _index_artifacts(app, session, [request_path, out_dir / "report.json", root / request["replay_path"]])
    if op == "verify" and report is not None:
        _record_replay_evidence(app, session, request, report)
    return _tool_output(op, run_id, result, report)


# --------------------------------------------------------------------------- REST routes


def register(app_: "FastAPI", api: "APIRouter", S: "AppState") -> None:
    """Register the replay REST routes.

    POST /api/sessions/{sid}/replays/record        — start a live recording
    POST /api/sessions/{sid}/replays/{run_id}/stop — stop a run
    GET  /api/sessions/{sid}/replays/{run_id}      — get status/report
    POST /api/sessions/{sid}/replays/replay        — replay a .gdwreplay
    POST /api/sessions/{sid}/replays/verify        — verify a .gdwreplay
    POST /api/sessions/{sid}/replays/render        — render a .gdwreplay to media

    Async mutations return 202 {job_id, run_id, status_url}; every job finishes done/failed/cancelled.
    """
    from fastapi import Body, HTTPException
    from fastapi.responses import JSONResponse
    from .unity_bridge import get_bridge, is_unity_project

    tasks: set[asyncio.Task] = set()

    def _session(sid: str | None) -> dict:
        s = S.store.get(sid) if sid else None
        if not s:
            raise HTTPException(404, "Session not found")
        return s

    def _root(s: dict) -> Path:
        if not s.get("folder"):
            raise HTTPException(400, "Session has no folder")
        root = Path(s["folder"]).expanduser().resolve()
        if not is_unity_project(root):
            raise HTTPException(400, "Not a Unity project")
        return root

    def _prepare(s: dict, op: str, body: dict) -> dict:
        """Validate the request now so bad args answer 400 before a job exists."""
        mode = s.get("mode", "ask")
        try:
            request = _validated_request(op, body, replay_cfg=get_bridge(S).cfg().get("replay") or {})
        except ReplayOpError as exc:
            raise HTTPException(exc.http_status, str(exc)) from exc
        if mode == "plan" and (op in _CHANGE_OPS or (op == "verify" and request.get("capture"))):
            raise HTTPException(403, f"Plan only mode: replay {op} is refused.")
        return request

    async def _dispatch(session: dict, op: str, request: dict) -> JSONResponse:
        run_id = str(request["run_id"])
        status_url = f"/api/sessions/{session['id']}/replays/{run_id}"
        # Re-validating the frozen request in run_replay_op is idempotent and keeps one code path.
        args = {k: v for k, v in request.items() if k not in ("schema", "op")}

        job_id = S.jobs.start(session["id"], "replay", f"replay {op}/{run_id}",
                              {"run_id": run_id, "op": op})

        async def _run() -> None:
            try:
                out = await run_replay_op(S, session, op, args)
                S.jobs.finish(job_id, "failed" if out.is_error else "done", run_id=run_id, op=op,
                              summary=out.text.splitlines()[0][:300] if out.text else "")
                S.bus.publish("replay.done", {"run_id": run_id, "op": op,
                                              "status": "failed" if out.is_error else "done"},
                              session["id"])
            except asyncio.CancelledError:
                S.jobs.finish(job_id, "cancelled", run_id=run_id, op=op)
                S.bus.publish("replay.done", {"run_id": run_id, "op": op, "status": "cancelled"},
                              session["id"])
                raise
            except Exception as e:  # noqa: BLE001 — a job must always finish
                log.warning("replay job %s/%s failed: %s", run_id, op, e)
                S.jobs.finish(job_id, "failed", run_id=run_id, op=op, error=str(e)[:500])
                S.bus.publish("replay.done", {"run_id": run_id, "op": op, "status": "failed",
                                              "error": str(e)[:300]}, session["id"])

        t = asyncio.create_task(_run())
        tasks.add(t)
        t.add_done_callback(tasks.discard)
        S.jobs.attach(job_id, t)

        return JSONResponse(content={"job_id": job_id, "run_id": run_id, "status_url": status_url},
                            status_code=202)

    @api.post("/api/sessions/{sid}/replays/record")
    async def record(sid: str, body: dict = Body(...)) -> dict:
        s = _session(sid)
        _root(s)
        return await _dispatch(s, "record", _prepare(s, "record", body))

    @api.post("/api/sessions/{sid}/replays/{run_id}/stop")
    async def stop(sid: str, run_id: str) -> dict:
        s = _session(sid)
        root = _root(s)
        if not _RUN_ID_RE.match(run_id):
            raise HTTPException(404, f"No such replay run: {run_id}")
        out = await run_replay_op(S, s, "stop", {"run_id": run_id})
        stopped = out.text.startswith(f"Replay {run_id}: stopped")
        if not stopped and not _replay_output_dir(root, run_id).is_dir():
            raise HTTPException(404, f"No such replay run: {run_id}")
        return {"status": "stopped" if stopped else "not_found", "run_id": run_id}

    @api.get("/api/sessions/{sid}/replays/{run_id}")
    async def status(sid: str, run_id: str) -> dict:
        s = _session(sid)
        root = _root(s)
        if not _RUN_ID_RE.match(run_id):
            raise HTTPException(404, f"No such replay run: {run_id}")
        out_dir = _replay_output_dir(root, run_id)
        if not out_dir.is_dir():
            raise HTTPException(404, f"No such replay run: {run_id}")
        await run_replay_op(S, s, "status", {"run_id": run_id})
        report: dict = {}
        report_path = out_dir / "report.json"
        if report_path.is_file():
            try:
                loaded = json.loads(report_path.read_text(errors="replace", encoding="utf-8"))
                report = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                report = {}
        replay_path = out_dir / "run.gdwreplay"
        archive_info = {}
        if replay_path.is_file():
            archive_info = {"size": replay_path.stat().st_size, "path": _rel_posix(root, replay_path)}
        warning = _size_warning(root, get_bridge(S).cfg().get("replay") or {})
        return {"run_id": run_id, "report": report, "archive": archive_info,
                "dir": _rel_posix(root, out_dir), **({"warning": warning} if warning else {})}

    @api.post("/api/sessions/{sid}/replays/replay")
    async def replay(sid: str, body: dict = Body(...)) -> dict:
        s = _session(sid)
        _root(s)
        return await _dispatch(s, "replay", _prepare(s, "replay", body))

    @api.post("/api/sessions/{sid}/replays/verify")
    async def verify(sid: str, body: dict = Body(...)) -> dict:
        s = _session(sid)
        _root(s)
        return await _dispatch(s, "verify", _prepare(s, "verify", body))

    @api.post("/api/sessions/{sid}/replays/render")
    async def render(sid: str, body: dict = Body(...)) -> dict:
        s = _session(sid)
        _root(s)
        return await _dispatch(s, "render", _prepare(s, "render", body))
