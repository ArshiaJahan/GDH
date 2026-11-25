"""Read Unity's text prefab documents and retain the spans needed for scalar edits."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import re

from .unity_scene import _DOC, _field, _fid, _NUM

SKIP_FOLDERS = {"Library", "Packages", "Temp"}
CLASS_NAMES = {
    4: "Transform", 23: "MeshRenderer", 33: "MeshFilter", 50: "Rigidbody2D",
    54: "Rigidbody", 58: "CircleCollider2D", 61: "BoxCollider2D", 65: "BoxCollider",
    82: "AudioSource", 95: "Animator", 135: "SphereCollider", 198: "ParticleSystem",
    212: "SpriteRenderer", 222: "CanvasRenderer", 224: "RectTransform",
    # More built-ins seen in real projects (class ids from Unity's YAML class ID reference).
    20: "Camera", 25: "Renderer", 56: "CapsuleCollider", 60: "PolygonCollider2D", 64: "MeshCollider",
    66: "CompositeCollider2D", 68: "EdgeCollider2D", 70: "CapsuleCollider2D", 96: "TrailRenderer", 108: "Light",
    120: "LineRenderer", 137: "SkinnedMeshRenderer", 195: "NavMeshAgent", 199: "ParticleSystemRenderer",
    210: "SortingGroup", 223: "Canvas", 225: "CanvasGroup", 320: "PlayableDirector", 331: "SpriteMask",
    483693784: "TilemapRenderer", 1839735485: "Tilemap", 19719996: "TilemapCollider2D", 156049354: "Grid",
}
FIELDS = {
    4: {"m_LocalPosition", "m_LocalRotation", "m_LocalScale"},
    224: {"m_LocalPosition", "m_LocalRotation", "m_LocalScale"},
    50: {"m_Mass", "m_LinearDamping", "m_LinearDrag", "m_GravityScale"},
    212: {"m_Color", "m_SortingOrder", "m_FlipX", "m_FlipY"},
    65: {"m_IsTrigger", "m_Size", "m_Offset", "m_Center"},
    61: {"m_IsTrigger", "m_Size", "m_Offset", "m_Center"},
    58: {"m_Radius"},
    82: {"m_Volume", "m_Pitch"},
}
BOOKKEEPING = {
    "m_ObjectHideFlags", "m_CorrespondingSourceObject", "m_PrefabInstance", "m_PrefabAsset",
    "m_GameObject", "m_Enabled", "m_EditorHideFlags", "m_Script", "m_Name",
    "m_EditorClassIdentifier", "serializedVersion",
}
BOOL_FIELDS = {"m_FlipX", "m_FlipY", "m_IsTrigger", "m_IsKinematic", "m_UseGravity", "m_Loop"}
BOOL_NAME = re.compile(r"^(?:[Ii]s|[Hh]as|[Cc]an|[Uu]se|[Ss]hould|[Aa]llow|[Ee]nable)[A-Z]")
GUID = re.compile(r"\bguid:[ \t]*([0-9a-fA-F]{32})\b")
TOP_FIELD = re.compile(r"^  (?!-[ \t])([^ \t\r\n:#][^:\r\n]*):([^\r\n]*)", re.M)
FILE_ID = re.compile(r"\{\s*fileID:\s*(-?\d+)")
PART = re.compile(rf"[ \t]*([xyzwrgba]):[ \t]*({_NUM})[ \t]*")
SCALAR = re.compile(r"""'(?:[^']|'')*'|"(?:[^"\\]|\\.)*"|[\s\S]+?(?=[ \t]+#|\Z)""")
MOD_LIST = re.compile(r"^( +)m_Modifications:([^\r\n]*)(\r?\n|$)", re.M)
MOD_ITEM = re.compile(r"^( +)- target:[ \t]*(\{[^\r\n]*\})[^\r\n]*", re.M)


@dataclass(frozen=True)
class Token:
    raw: str
    start: int
    end: int

    @property
    def value(self) -> str:
        if self.raw.startswith("'") and self.raw.endswith("'"):
            return self.raw[1:-1].replace("''", "'")
        if self.raw.startswith('"') and self.raw.endswith('"'):
            try:
                return json.loads(self.raw)
            except ValueError:
                return self.raw[1:-1]
        return self.raw


def token(text: str, start: int) -> Token:
    leading = len(text) - len(text.lstrip(" \t"))
    tail = text[leading:]
    match = SCALAR.match(tail) if not tail.startswith("#") else None
    raw = match[0].rstrip(" \t") if match else ""
    return Token(raw, start + leading, start + leading + len(raw))


@dataclass(frozen=True)
class Field:
    key: str
    token: Token
    kind: str
    parts: dict[str, Token]
    editable: bool


@dataclass(frozen=True)
class Document:
    class_id: int
    file_id: str
    stripped: bool
    body: str
    offset: int


@dataclass(frozen=True)
class Modification:
    target_file_id: str
    target_guid: str
    property_path: str
    token: Token
    object_reference: str | None
    start: int
    end: int

    def public(self) -> dict:
        return {
            "target_file_id": self.target_file_id, "target_guid": self.target_guid,
            "property_path": self.property_path, "value": self.token.value,
            "object_reference": self.object_reference,
        }


@dataclass(frozen=True)
class Prefab:
    text: str
    docs: dict[str, Document]
    instance: Document | None
    source_guid: str | None
    modifications: tuple[Modification, ...]


def modification_list(doc: Document) -> re.Match | None:
    return MOD_LIST.search(doc.body)


def modifications(doc: Document) -> tuple[Modification, ...]:
    listing = modification_list(doc)
    if not listing:
        return ()
    indent = listing[1]
    # Unity's block sequence is normally at the same indentation as the key.
    rest = doc.body[listing.end():]
    boundary = re.search(rf"^ {{0,{len(indent)}}}[^ \t\r\n#-]", rest, re.M)
    block = rest[:boundary.start()] if boundary else rest
    items = list(MOD_ITEM.finditer(block))
    offset = doc.offset + listing.end()
    result = []
    for i, item in enumerate(items):
        end = items[i + 1].start() if i + 1 < len(items) else len(block)
        entry = block[item.end():end]
        fid, guid = FILE_ID.search(item[2]), GUID.search(item[2])
        val = re.search(r"^ +value:([^\r\n]*)", entry, re.M)
        prop = _field(entry, "propertyPath")
        if not (fid and guid and prop and val):
            continue
        reference = _field(entry, "objectReference")
        ref_id = FILE_ID.search(reference or "")
        entry_end = re.search(r"^ +objectReference:[^\r\n]*(?:\r?\n|$)", entry, re.M)
        result.append(Modification(
            fid[1], guid[1].lower(), token(prop, 0).value,
            token(val[1], offset + item.end() + val.start(1)),
            reference if ref_id and ref_id[1] != "0" else None,
            offset + item.start(), offset + item.end() + entry_end.end() if entry_end else offset + end,
        ))
    return tuple(result)


def parse(text: str) -> Prefab:
    headers = list(_DOC.finditer(text))
    docs = {}
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        docs[header[2]] = Document(
            int(header[1]), header[2], bool(header[3]), text[header.end():end], header.end(),
        )
    has_root = any(
        doc.class_id in (4, 224) and not doc.stripped and not _fid(doc.body, "m_Father")
        for doc in docs.values()
    )
    if not has_root:
        for doc in docs.values():
            if doc.class_id == 1001 and not _fid(doc.body, "m_TransformParent"):
                source = GUID.search(_field(doc.body, "m_SourcePrefab") or "")
                if source:
                    return Prefab(text, docs, doc, source[1].lower(), modifications(doc))
    return Prefab(text, docs, None, None, ())


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


@lru_cache(maxsize=4096)
def _cached_prefab(path: Path, mtime: int, size: int) -> Prefab:
    return parse(_read_text(path))


@lru_cache(maxsize=16384)
def _cached_guid(path: Path, mtime: int, size: int) -> str | None:
    with path.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            if line.startswith("guid:") and (match := GUID.search(line)):
                return match[1].lower()
    return None


@lru_cache(maxsize=4096)
def _script_fields(path: Path, mtime: int, size: int) -> dict[str, str]:
    source = re.sub(r"//[^\r\n]*|/\*[\s\S]*?\*/", "", _read_text(path))
    return {
        key: kind for kind, key in re.findall(
            r"\b(bool|string|int|uint|long|ulong|short|ushort|byte|sbyte|float|double|decimal)"
            r"\s+(\w+)\s*(?=[=;,])", source,
        )
    }


def _cached(reader, path: Path):
    stat = path.stat()
    return reader(path, stat.st_mtime_ns, stat.st_size)


def _block_kind(value: str, continuation: str) -> str | None:
    lines = [line.lstrip() for line in continuation.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if value.startswith("[") or (not value and lines and lines[0].startswith("- ")):
        return "list"
    if lines or value.startswith(("|", ">")):
        return "other"
    return None


def _parts(scalar: Token) -> dict[str, Token]:
    if not (scalar.raw.startswith("{") and scalar.raw.endswith("}")):
        return {}
    offset = 1
    parts = {}
    for piece in scalar.raw[1:-1].split(","):
        match = PART.fullmatch(piece)
        if not match or match[1] in parts:
            return {}
        start = scalar.start + offset + match.start(2)
        parts[match[1]] = Token(match[2], start, start + len(match[2]))
        offset += len(piece) + 1
    keys = parts.keys()
    if keys <= set("xyzw") or keys <= set("rgba"):
        return parts
    return {}


def fields(doc: Document, declarations: dict[str, str]) -> list[Field]:
    rows = list(TOP_FIELD.finditer(doc.body))
    result = []
    after_identifier = False
    for i, row in enumerate(rows):
        key = row[1]
        if key == "m_EditorClassIdentifier":
            after_identifier = True
        if key in BOOKKEEPING:
            continue
        if doc.class_id == 114:
            if not after_identifier:
                continue
        elif doc.class_id in FIELDS and key not in FIELDS[doc.class_id]:
            continue
        scalar = token(row[2], doc.offset + row.start(2))
        end = rows[i + 1].start() if i + 1 < len(rows) else len(doc.body)
        kind = _block_kind(scalar.raw, doc.body[row.end():end])
        parts = {}
        if kind is None:
            raw = scalar.raw
            declared = declarations.get(key)
            if FILE_ID.match(raw):
                kind = "reference"
            elif parts := _parts(scalar):
                kind = "vector" if parts.keys() <= set("xyzw") else "color"
            elif raw.startswith("{"):
                kind = "other"
            elif raw.startswith(("'", '"')) or declared == "string":
                kind = "string"
            elif (declared == "bool" or key in BOOL_FIELDS or raw.lower() in {"true", "false"}
                  or (not declared and raw in {"0", "1"}
                      and BOOL_NAME.match(key.removeprefix("m_").lstrip("_")))):
                kind = "bool"
            elif re.fullmatch(_NUM, raw):
                kind = "number"
            else:
                kind = "string"
        if doc.class_id not in FIELDS and doc.class_id != 114 and kind not in {"string", "bool", "number"}:
            continue
        result.append(Field(key, scalar, kind, parts, kind not in {"reference", "list", "other"}))
    return result


def label(key: str) -> str:
    key = key.removeprefix("m_").strip("_").replace("_", " ")
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", key)
    key = " ".join(key.split())
    return key[:1].upper() + key[1:]


def _children(body: str) -> list[str]:
    match = re.search(r"^  m_Children:[^\r\n]*", body, re.M)
    if not match:
        return []
    return re.findall(r"\{fileID:[ \t]*(-?\d+)", _sequence(body[match.end():]))


def _sequence(text: str) -> str:
    match = re.match(r"(?:\r?\n {2,}- [^\r\n]*)*", text)
    return match[0]


class Project:
    """Index the safe Assets paths once for each request, sharing parsed file caches."""

    def __init__(self, root: Path, pending: dict[Path, str] | None = None):
        self.root = root
        self.pending = pending if pending is not None else {}
        self.prefabs: dict[str, str | None] = {}
        self.by_guid: dict[str, str] = {}
        self.scripts: dict[str, str] = {}
        assets = root / "Assets"
        if assets.is_symlink():
            return
        for directory, dirs, names in os.walk(assets):
            dirs[:] = sorted(d for d in dirs if self.visible_folder(d) and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                suffix = path.suffix.lower()
                if suffix not in {".prefab", ".cs"} or path.is_symlink() or not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                meta = path.with_name(name + ".meta")
                guid = None
                if not meta.is_symlink():
                    try:
                        guid = _cached(_cached_guid, meta)
                    except OSError:
                        pass
                if suffix == ".prefab":
                    self.prefabs[rel] = guid
                    if guid:
                        self.by_guid.setdefault(guid, rel)
                elif guid:
                    self.scripts.setdefault(guid, rel)

    @staticmethod
    def visible_folder(name: str) -> bool:
        return not name.startswith(".") and name not in SKIP_FOLDERS

    def read(self, path: str) -> Prefab:
        file = self.root / path
        if file in self.pending:
            return parse(self.pending[file])
        return _cached(_cached_prefab, file)

    def variant_of(self, prefab: Prefab) -> dict | None:
        if not prefab.source_guid:
            return None
        path = self.by_guid.get(prefab.source_guid)
        return {"guid": prefab.source_guid, "name": Path(path).stem if path else None, "path": path}

    def declarations(self, script: str | None) -> dict[str, str]:
        if script:
            try:
                return _cached(_script_fields, self.root / script)
            except (OSError, UnicodeError):
                pass
        return {}

    def component(self, doc: Document) -> dict:
        mono = doc.class_id == 114
        script = None
        namespace = ""
        if mono:
            guid = GUID.search(_field(doc.body, "m_Script") or "")
            script = self.scripts.get(guid[1].lower()) if guid else None
            identifier = token(_field(doc.body, "m_EditorClassIdentifier") or "", 0).value
            qualified = identifier.partition("::")[2]
            namespace, _, typename = qualified.rpartition(".")
            typename = Path(script).stem if script else typename or qualified or "MonoBehaviour"
        else:
            typename = CLASS_NAMES.get(doc.class_id, f"Component{doc.class_id}")
        return {
            "file_id": doc.file_id, "type": typename, "namespace": namespace, "builtin": not mono,
            "script_path": script, "enabled": (_field(doc.body, "m_Enabled") or "1").lower() not in {"0", "false"},
        }

    def objects(self, prefab: Prefab) -> list[dict]:
        objects = {}
        transforms = {}
        parent = {}
        children = {}
        for fid, doc in prefab.docs.items():
            if doc.stripped:
                continue
            if doc.class_id in (4, 224) and (go := _fid(doc.body, "m_GameObject")):
                transforms[fid] = go
                parent[go] = _fid(doc.body, "m_Father")
                children[go] = _children(doc.body)
            elif doc.class_id == 1:
                match = re.search(r"^  m_Component:[^\r\n]*", doc.body, re.M)
                components = FILE_ID.findall(_sequence(doc.body[match.end():])) if match else []
                objects[fid] = {
                    "file_id": fid, "name": token(_field(doc.body, "m_Name") or "", 0).value,
                    "components": [self.component(prefab.docs[c]) for c in components
                                   if c in prefab.docs and not prefab.docs[c].stripped],
                }
        order = {fid: [transforms[c] for c in children.get(fid, []) if c in transforms] for fid in objects}
        for fid, obj in objects.items():
            owner = transforms.get(parent.get(fid))
            obj["parent_file_id"] = owner if owner in objects else None
            if owner in order and fid not in order[owner]:
                order[owner].append(fid)
        seen = set()
        result = []

        roots = [fid for fid, obj in objects.items() if obj["parent_file_id"] is None]
        stack = list(reversed(objects)) + list(reversed(roots))
        while stack:
            fid = stack.pop()
            if fid in objects and fid not in seen:
                seen.add(fid)
                result.append(objects[fid])
                stack.extend(reversed(order[fid]))
        return result

    def lineage(self, path: str) -> list[tuple[str, Prefab]]:
        chain = []
        seen = set()
        while path and path not in seen:
            seen.add(path)
            prefab = self.read(path)
            chain.append((path, prefab))
            path = self.by_guid.get(prefab.source_guid)
        return chain

    def root_components(self, path: str) -> list[str]:
        prefab = self.lineage(path)[-1][1]
        objects = self.objects(prefab)
        return [comp["type"] for comp in objects[0]["components"]] if objects else []
