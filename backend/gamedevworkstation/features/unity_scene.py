"""Read-only facts from a Unity project's scene files, for framing a screenshot without the Editor.

The gallery's screenshot agent can't look at the scene when the Editor is closed (batch route), so it
reads the saved scene instead: scene list (build scenes first) and, per scene, the cameras, lights and
GameObjects with world positions and rotations, parsed straight from the text YAML (Unity's
`--- !u!<class> &<fileID>` documents). Nothing is written and nothing runs: plain file reads, capped.

What is understood: GameObject (1), Transform (4), RectTransform (224), Camera (20), Light (108) and
PrefabInstance (1001, its name / position / rotation overrides and its parent; children of the prefab
asset itself aren't expanded). Positions are composed through parents (position, rotation, scale);
rotations come out as Unity euler angles (degrees). Values are rounded for the model.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

MAX_SCENE_BYTES = 30_000_000
MAX_SCENES = 200
MAX_META_SCAN = 50_000
_DOC = re.compile(r"^--- !u!(\d+) &(-?\d+)( stripped)?[^\n]*$", re.M)
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_KV = re.compile(rf"(\w+): ({_NUM})")
_FILEID = re.compile(r"\{fileID: (-?\d+)")
CLASS = {1: "GameObject", 4: "Transform", 20: "Camera", 108: "Light", 224: "RectTransform", 1001: "PrefabInstance"}


# ------------------------------------------------------------------ math

Quat = tuple[float, float, float, float]  # x, y, z, w
Vec = tuple[float, float, float]
IDENTITY: Quat = (0.0, 0.0, 0.0, 1.0)


def q_mul(a: Quat, b: Quat) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def q_rotate(q: Quat, v: Vec) -> Vec:
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v); v' = v + w * t + cross(q.xyz, t)
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


def q_normalize(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def euler(q: Quat) -> Vec:
    """Unity euler angles (degrees, Z-X-Y order) of a quaternion, each in [0, 360)."""
    x, y, z, w = q_normalize(q)
    sx = max(-1.0, min(1.0, 2 * (w * x - y * z)))
    pitch = math.degrees(math.asin(sx))
    if abs(sx) > 0.9999:  # gimbal lock: put everything in yaw
        yaw = math.degrees(2 * math.atan2(y, w))
        roll = 0.0
    else:
        yaw = math.degrees(math.atan2(2 * (w * y + x * z), 1 - 2 * (x * x + y * y)))
        roll = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (x * x + z * z)))
    return (pitch % 360, yaw % 360, roll % 360)


def look_rotation(src: Any, dst: Any) -> list[float]:
    """Euler angles [x, y, 0] (degrees) of a camera at src looking at dst (Unity: +z forward, +y up)."""
    dx, dy, dz = (float(dst[i]) - float(src[i]) for i in range(3))
    flat = math.hypot(dx, dz)
    if flat < 1e-6 and abs(dy) < 1e-6:
        return [0.0, 0.0, 0.0]
    yaw = math.degrees(math.atan2(dx, dz)) % 360
    pitch = math.degrees(-math.atan2(dy, flat)) % 360
    return [round(pitch, 2), round(yaw, 2), 0.0]


# ------------------------------------------------------------------ scenes


def _inside(root: Path, p: Path) -> bool:
    try:
        r, q = root.resolve(), p.resolve()
    except OSError:
        return False
    return q == r or r in q.parents


def build_scenes(root: Path) -> list[dict]:
    """[{path, enabled}] from ProjectSettings/EditorBuildSettings.asset, in build order."""
    f = root / "ProjectSettings" / "EditorBuildSettings.asset"
    try:
        text = f.read_text(errors="replace")[:2_000_000]
    except OSError:
        return []
    out: list[dict] = []
    for m in re.finditer(r"-\s+enabled:\s*(\d)\s*\n\s+path:\s*(.+?)\s*\n", text):
        out.append({"path": m.group(2).strip(), "enabled": m.group(1) == "1"})
    return out


def list_scenes(root: Path | str) -> dict:
    """{"default": the first enabled build scene (what HarnessCli.Screenshot opens without -scene) or None,
    "build": [{path, enabled, exists}], "others": [Assets/... scenes not in the build list]}."""
    root = Path(root).expanduser().resolve()
    build = [{**b, "exists": (root / b["path"]).is_file()} for b in build_scenes(root)]
    listed = {b["path"] for b in build}
    others: list[str] = []
    assets = root / "Assets"
    if assets.is_dir():
        for dirpath, dirnames, filenames in os.walk(assets):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for n in sorted(filenames):
                if n.endswith(".unity"):
                    rel = (Path(dirpath) / n).relative_to(root).as_posix()
                    if rel not in listed:
                        others.append(rel)
            if len(others) >= MAX_SCENES:
                break
    default = next((b["path"] for b in build if b["enabled"] and b["exists"]), None)
    return {"default": default, "build": build, "others": others[:MAX_SCENES]}


def scene_file(root: Path | str, scene: str) -> Path:
    """The scene's file, refusing anything that isn't an Assets/...unity file inside the project."""
    root = Path(root).expanduser().resolve()
    s = str(scene or "").replace("\\", "/").strip()
    if not (s.startswith("Assets/") and s.lower().endswith(".unity")) or ".." in s.split("/"):
        raise ValueError(f"scene must be an Assets/...unity path, got {scene!r}")
    p = root / s
    if not _inside(root, p) or not p.is_file():
        raise ValueError(f"scene not found: {s}")
    return p


def _docs(text: str) -> list[tuple[int, str, bool, str]]:
    heads = list(_DOC.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((int(m.group(1)), m.group(2), bool(m.group(3)), text[m.end():end]))
    return out


def _field(body: str, name: str) -> str | None:
    m = re.search(rf"^\s*{re.escape(name)}: ?(.*)$", body, re.M)
    return m.group(1).strip() if m else None


def _vec(body: str, name: str, keys: str = "xyz") -> tuple[float, ...] | None:
    v = _field(body, name)
    if not v or not v.startswith("{"):
        return None
    d = {k: float(n) for k, n in _KV.findall(v)}
    try:
        return tuple(d[k] for k in keys)
    except KeyError:
        return None


def _fid(body: str, name: str) -> str | None:
    v = _field(body, name)
    m = _FILEID.search(v or "")
    return m.group(1) if m and m.group(1) != "0" else None


def _mods(body: str) -> list[tuple[str, str]]:
    """(propertyPath, value) of a PrefabInstance's m_Modifications."""
    out = []
    for m in re.finditer(r"propertyPath: (\S+)\s*\n\s*value: ?(.*)\n", body):
        out.append((m.group(1), m.group(2).strip()))
    return out


def _guid_paths(root: Path, guids: set[str]) -> dict[str, str]:
    """guid → Assets/... path for the prefab / model sources of prefab instances (a bounded .meta scan)."""
    found: dict[str, str] = {}
    if not guids:
        return found
    n = 0
    for dirpath, dirnames, filenames in os.walk(root / "Assets"):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if not f.endswith(".meta") or not f[:-5].lower().endswith((".prefab", ".fbx", ".obj", ".blend", ".gltf", ".glb")):
                continue
            n += 1
            if n > MAX_META_SCAN:
                return found
            try:
                with open(os.path.join(dirpath, f), "r", errors="replace") as fh:
                    head = fh.read(400)
            except OSError:
                continue
            m = re.search(r"guid: ([0-9a-f]{32})", head)
            if m and m.group(1) in guids:
                found[m.group(1)] = (Path(dirpath) / f[:-5]).relative_to(root).as_posix()
                if len(found) == len(guids):
                    return found
    return found


def read_scene(root: Path | str, scene: str, *, query: str | None = None, limit: int = 150) -> dict:
    """Cameras, lights and objects of a saved scene with world transforms. query: a case-insensitive
    substring of the hierarchy path; limit: objects returned (cameras and lights always come first)."""
    root = Path(root).expanduser().resolve()
    p = scene_file(root, scene)
    size = p.stat().st_size
    if size > MAX_SCENE_BYTES:
        raise ValueError(f"{scene} is {size // 1_000_000} MB; too big to read here")
    text = p.read_text(errors="replace")
    if not text.startswith("%YAML"):
        raise ValueError(f"{scene} isn't a text scene (Asset Serialization must be Force Text)")
    gos: dict[str, dict] = {}
    nodes: dict[str, dict] = {}       # transform fileID (or "p<prefab instance>") → node
    alias: dict[str, str] = {}        # stripped transform fileID → "p<prefab instance>"
    comps: dict[str, list[tuple[str, dict]]] = {}  # GameObject fileID → [(kind, info)]
    prefabs: list[tuple[str, str]] = []
    for cls, fid, stripped, body in _docs(text):
        if cls == 1 and not stripped:
            gos[fid] = {"name": _field(body, "m_Name") or "", "active": (_field(body, "m_IsActive") or "1") == "1"}
        elif cls in (4, 224):
            if stripped:
                if pi := _fid(body, "m_PrefabInstance"):
                    alias[fid] = "p" + pi
                continue
            nodes[fid] = {"go": _fid(body, "m_GameObject"), "pos": _vec(body, "m_LocalPosition") or (0.0, 0.0, 0.0),
                          "rot": _vec(body, "m_LocalRotation", "xyzw") or IDENTITY,
                          "scale": _vec(body, "m_LocalScale") or (1.0, 1.0, 1.0), "parent": _fid(body, "m_Father")}
        elif cls == 20 and not stripped:
            go = _fid(body, "m_GameObject")
            if go:
                fov = _field(body, "field of view")
                ortho = (_field(body, "orthographic") or "0") == "1"
                info = {"fov": round(float(fov), 2) if fov and re.fullmatch(_NUM, fov) else None, "orthographic": ortho,
                        "enabled": (_field(body, "m_Enabled") or "1") == "1"}
                if ortho and (os_ := _field(body, "orthographic size")) and re.fullmatch(_NUM, os_):
                    info["ortho_size"] = round(float(os_), 3)
                comps.setdefault(go, []).append(("camera", info))
        elif cls == 108 and not stripped:
            go = _fid(body, "m_GameObject")
            if go:
                t = _field(body, "m_Type")
                comps.setdefault(go, []).append(("light", {"type": {"0": "spot", "1": "directional", "2": "point",
                                                                     "3": "area"}.get(t or "", t)}))
        elif cls == 1001:
            prefabs.append((fid, body))
    guids: dict[str, str] = {}
    for fid, body in prefabs:
        mods = _mods(body)
        get = lambda k: next((v for pp, v in reversed(mods) if pp == k), None)  # noqa: E731

        def num(k: str, default: float) -> float:
            v = get(k)
            try:
                return float(v) if v is not None else default
            except ValueError:
                return default

        src = re.search(r"m_SourcePrefab: \{fileID: -?\d+, guid: ([0-9a-f]{32})", body)
        if src:
            guids["p" + fid] = src.group(1)
        nodes["p" + fid] = {"go": None, "name": get("m_Name"), "prefab": True,
                            "pos": (num("m_LocalPosition.x", 0), num("m_LocalPosition.y", 0), num("m_LocalPosition.z", 0)),
                            "rot": (num("m_LocalRotation.x", 0), num("m_LocalRotation.y", 0), num("m_LocalRotation.z", 0),
                                    num("m_LocalRotation.w", 1)),
                            "scale": (num("m_LocalScale.x", 1), num("m_LocalScale.y", 1), num("m_LocalScale.z", 1)),
                            "parent": _fid(body, "m_TransformParent")}
    unnamed = {guids[k] for k, n in nodes.items() if n.get("prefab") and not n.get("name") and k in guids}
    paths = _guid_paths(root, unnamed) if unnamed else {}
    for k, n in nodes.items():
        if n.get("prefab") and not n.get("name"):
            n["name"] = Path(paths[guids[k]]).stem if guids.get(k) in paths else f"(prefab {guids.get(k, '?')[:8]})"

    def resolve(tid: str | None) -> str | None:
        return alias.get(tid, tid) if tid else None

    world: dict[str, tuple[Vec, Quat, Vec, int, str]] = {}

    def wt(tid: str, depth: int = 0) -> tuple[Vec, Quat, Vec, int, str]:
        if tid in world:
            return world[tid]
        n = nodes[tid]
        name = n.get("name") or gos.get(n.get("go") or "", {}).get("name") or "?"
        par = resolve(n.get("parent"))
        if par and par in nodes and depth < 64 and par != tid:
            ppos, prot, pscale, pdepth, ppath = wt(par, depth + 1)
            sp = (n["pos"][0] * pscale[0], n["pos"][1] * pscale[1], n["pos"][2] * pscale[2])
            r = q_rotate(prot, sp)
            res = ((ppos[0] + r[0], ppos[1] + r[1], ppos[2] + r[2]), q_normalize(q_mul(prot, n["rot"])),
                   (pscale[0] * n["scale"][0], pscale[1] * n["scale"][1], pscale[2] * n["scale"][2]),
                   pdepth + 1, f"{ppath}/{name}")
        else:
            res = (tuple(n["pos"]), q_normalize(n["rot"]), tuple(n["scale"]), 0, name)  # type: ignore[assignment]
        world[tid] = res  # type: ignore[assignment]
        return res  # type: ignore[return-value]

    rnd = lambda v, d=2: [round(c, d) + 0.0 for c in v]  # noqa: E731  (+0.0 turns -0.0 into 0.0)
    items: list[dict] = []
    for tid, n in nodes.items():
        pos, rot, _scale, depth, path = wt(tid)
        go = n.get("go") or ""
        kinds = comps.get(go, [])
        e: dict[str, Any] = {"name": path.rsplit("/", 1)[-1], "path": path, "pos": rnd(pos), "rot": [round(c, 1) % 360 + 0.0 for c in euler(rot)],
                             "kind": "prefab" if n.get("prefab") else "object", "depth": depth}
        if go in gos and not gos[go]["active"]:
            e["active"] = False
        for kind, info in kinds:
            e["kind"] = kind if e["kind"] in ("object", "prefab") or kind == "camera" else e["kind"]
            e.update({k: v for k, v in info.items() if v is not None})
        items.append(e)
    order = {"camera": 0, "light": 1, "prefab": 2, "object": 2}
    items.sort(key=lambda e: (order.get(e["kind"], 3), e["depth"], e["path"].lower()))
    total = len(items)
    if query:
        ql = query.lower()
        items = [e for e in items if ql in e["path"].lower() or e["kind"] in ("camera",)]
    pts = [e["pos"] for e in items if e["kind"] not in ("light",)] or [[0.0, 0.0, 0.0]]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    limit = max(1, min(int(limit or 150), 500))
    for e in items:
        e.pop("depth", None)
    return {"scene": str(scene), "objects_total": total, "objects": items[:limit], "truncated": len(items) > limit,
            "cameras": [e["path"] for e in items if e["kind"] == "camera"],
            "bounds": {"min": rnd(lo), "max": rnd(hi), "center": rnd([(a + b) / 2 for a, b in zip(lo, hi)])}}


__all__ = ["build_scenes", "euler", "list_scenes", "look_rotation", "read_scene", "scene_file"]
