"""Prefab edits, atomic file replacement, and the project-local undo journal."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from fastapi import HTTPException

from .prefab_yaml import Field, Modification, Prefab, Project, Token, fields, label, modification_list, token
from .unity_scene import _NUM

HISTORY = "prefab-history.json"
LIMIT = 500


def metadata_path(root: Path, *parts: str) -> Path:
    path = root
    for part in (".gdw", *parts):
        path /= part
        if path.is_symlink():
            raise HTTPException(400, "Prefab metadata cannot use symbolic links")
    return path


def prefab_path(project: Project, path: str) -> Path:
    bits = path.split("/")
    if (len(bits) < 2 or bits[0] != "Assets" or not bits[-1].lower().endswith(".prefab")
            or any(bit in {"", ".", ".."} for bit in bits) or "\\" in path or "\x00" in path):
        raise HTTPException(400, "Expected an Assets-relative .prefab path")
    if path not in project.prefabs:
        raise HTTPException(404, "Unknown prefab")
    file = project.root / path
    if file.resolve() != file:
        raise HTTPException(400, "Prefab paths cannot use symbolic links")
    return file


def load_history(root: Path) -> dict:
    try:
        return json.loads(metadata_path(root, HISTORY).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"position": 0, "steps": []}


def _atomic_write(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".prefab-", delete=False) as file:
        staged = Path(file.name)
    try:
        staged.write_bytes(text.encode("utf-8"))
        if mode is not None:
            staged.chmod(mode)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    _atomic_write(path, json.dumps(data, indent=2) + "\n")


def _active(history: dict) -> list[dict]:
    return history["steps"][:history["position"]]


def _value(state: str | dict) -> str:
    return state["value"] if isinstance(state, dict) else state


def _encoding(state: str | dict) -> dict:
    return state if isinstance(state, dict) else {"value": state, "raw": state}


def _state(value: str, raw: str, **layout) -> str | dict:
    # The journal retains the YAML spelling or list layout when replay needs it.
    if value == raw and not layout:
        return value
    return {"value": value, "raw": raw, **layout}


def public_history(history: dict) -> dict:
    position = history["position"]
    steps = []
    for index in range(len(history["steps"]) - 1, -1, -1):
        step = history["steps"][index]
        edits = [{**edit, "before": _value(edit["before"]), "after": _value(edit["after"])}
                 for edit in step["edits"]]
        steps.append({**step, "edits": edits, "undone": index >= position})
    return {"position": position, "steps": steps}


def edit_counts(history: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in _active(history):
        for path in {e["path"] for e in step["edits"]}:
            counts[path] = counts.get(path, 0) + 1
    return counts


@dataclass(frozen=True)
class Inspector:
    project: Project
    chain: list[tuple[str, Prefab]]

    @property
    def prefab(self) -> Prefab:
        return self.chain[0][1]

    @property
    def base(self) -> Prefab:
        return self.chain[-1][1]

    def find_modification(self, level: int, file_id: str, prop: str) -> Modification | None:
        prefab = self.chain[level][1]
        guids = [p.source_guid for _, p in self.chain[level:]]
        return next((
            mod for guid in guids if guid
            for mod in reversed(prefab.modifications)
            if mod.target_guid == guid and mod.target_file_id == file_id and mod.property_path == prop
        ), None)

    def resolve(self, file_id: str, prop: str, fallback: Token, start: int = 0) -> Token:
        for level in range(start, len(self.chain) - 1):
            if mod := self.find_modification(level, file_id, prop):
                return mod.token
        return fallback

    def fields(self, component: dict) -> list[Field]:
        return fields(self.base.docs[component["file_id"]], self.project.declarations(component["script_path"]))

    def objects(self) -> list[dict]:
        objects = self.project.objects(self.base)
        for obj in objects:
            fid = obj["file_id"]
            obj["name"] = self.resolve(fid, "m_Name", Token(json.dumps(obj["name"]), 0, 0)).value
            for comp in obj["components"]:
                fid = comp["file_id"]
                comp["enabled"] = self.resolve(
                    fid, "m_Enabled", Token("1" if comp["enabled"] else "0", 0, 0),
                ).value.lower() not in {"0", "false"}
        return objects


def inspect(project: Project, path: str) -> Inspector:
    prefab_path(project, path)
    try:
        return Inspector(project, project.lineage(path))
    except (OSError, UnicodeError) as exc:
        raise HTTPException(400, "Could not read text prefab") from exc


def detail(project: Project, path: str, history: dict) -> dict:
    inspector = inspect(project, path)
    edited = {}
    for step in _active(history):
        changes = {}
        for edit in step["edits"]:
            if edit["path"] == path:
                changes.setdefault(
                    (edit["file_id"], edit["key"]), {"was": _value(edit["before"]), "step": step["id"]},
                )
        edited.update(changes)
    objects = inspector.objects()
    for obj in objects:
        for component in obj["components"]:
            fid = component["file_id"]
            output = []
            for field in inspector.fields(component):
                resolved = inspector.resolve(fid, field.key, field.token)
                overridden = inspector.find_modification(0, fid, field.key) if inspector.prefab.instance else None
                shown = {
                    "key": field.key, "label": label(field.key), "value": resolved.value,
                    "kind": field.kind, "editable": field.editable,
                    "edited": edited.get((fid, field.key)),
                }
                if field.kind == "reference":
                    for level in range(len(inspector.chain) - 1):
                        if mod := inspector.find_modification(level, fid, field.key):
                            shown["value"] = mod.object_reference or "{fileID: 0}"
                            break
                if field.parts:
                    parts = {part: inspector.resolve(fid, f"{field.key}.{part}", base).value
                             for part, base in field.parts.items()}
                    # Apply from right to left using the base inline map's original offsets.
                    if parts != {key: base.value for key, base in field.parts.items()}:
                        raw = field.token.raw
                        for part, base in reversed(field.parts.items()):
                            start = base.start - field.token.start
                            raw = raw[:start] + parts[part] + raw[start + len(base.raw):]
                        shown["value"] = raw
                    shown["parts"] = parts
                    if inspector.prefab.instance and not overridden:
                        overridden = any(
                            inspector.find_modification(0, fid, f"{field.key}.{part}") for part in parts
                        )
                if inspector.prefab.instance:
                    shown["override" if overridden else "inherited"] = True
                output.append(shown)
            component["fields"] = output
    return {
        "path": path, "name": Path(path).stem, "guid": project.prefabs[path],
        "variant_of": project.variant_of(inspector.prefab), "objects": objects,
        "overrides": [mod.public() for mod in inspector.prefab.modifications],
    }


@dataclass(frozen=True)
class Slot:
    inspector: Inspector
    file_id: str
    field: Field
    prop: str
    base: Token
    modification: Modification | None

    @property
    def value_token(self) -> Token:
        return self.inspector.resolve(self.file_id, self.prop, self.base)


def _slot(project: Project, path: str, file_id: str, key: str, part: str | None) -> Slot:
    inspector = inspect(project, path)
    found = next((comp for obj in inspector.objects() for comp in obj["components"]
                  if comp["file_id"] == file_id), None)
    if not found:
        raise HTTPException(404, "Unknown component file id")
    field = next((field for field in inspector.fields(found) if field.key == key), None)
    if not field:
        raise HTTPException(404, "Unknown prefab field")
    if not field.editable or (part is None and field.parts) or (part is not None and part not in field.parts):
        raise HTTPException(400, "Field or part is not editable")
    prop = f"{key}.{part}" if part is not None else key
    mod = inspector.find_modification(0, file_id, prop) if inspector.prefab.instance else None
    return Slot(inspector, file_id, field, prop, field.parts[part] if part is not None else field.token, mod)


def _replacement(slot: Slot, value: str) -> str:
    kind = slot.field.kind
    if kind in {"number", "vector", "color"}:
        if not re.fullmatch(_NUM, value) or not math.isfinite(float(value)):
            raise HTTPException(400, "Expected a finite number")
        return value
    if kind == "bool":
        if value.lower() not in {"0", "1", "true", "false"}:
            raise HTTPException(400, "Expected 0, 1, true or false")
        return "1" if value.lower() in {"1", "true"} else "0"
    if any(ord(ch) < 32 and ch != "\t" or 0xD800 <= ord(ch) <= 0xDFFF or ch in "\x85\u2028\u2029"
           for ch in value):
        raise HTTPException(400, "Expected a single-line string")
    original = slot.value_token.raw
    if original.startswith('"'):
        return json.dumps(value, ensure_ascii=False)
    if (original.startswith("'") or not value or value != value.strip()
            or value[0] in "!&*{}[],#|>@%\x60\"'" or re.match(r"^(?:[-?:](?:\s|$)|---|\.\.\.)", value)
            or re.search(r":(?:\s|$)|\s#", value) or "\t" in value
            or re.fullmatch(r"[+-]?(?:\d.*|\.\d.*)|true|false|yes|no|on|off|null|~", value, re.I)):
        return "'" + value.replace("'", "''") + "'"
    return value


def _splice(text: str, start: int, end: int, replacement: str) -> str:
    return text[:start] + replacement + text[end:]


def _listing(prefab: Prefab) -> tuple[str, Token, int, int, str]:
    doc = prefab.instance
    listing = modification_list(doc)
    if not listing:
        raise HTTPException(400, "Variant has no modification list")
    line_end = listing[3]
    if not line_end:
        raise HTTPException(400, "Variant modification list has no block")
    value_start = doc.offset + listing.start(2)
    return listing[1], token(listing[2], value_start), value_start, doc.offset + listing.end(), line_end


def _insert(slot: Slot, raw: str) -> tuple[str, dict]:
    prefab = slot.inspector.prefab
    indent, marker, value_start, insert_at, eol = _listing(prefab)
    if prefab.modifications:
        first, last = prefab.modifications[0], prefab.modifications[-1]
        indent = prefab.text[first.start:prefab.text.index("-", first.start)]
        insert_at = last.end
    prefix = "" if prefab.text[insert_at - 1] == "\n" else eol
    suffix = eol if not prefix else ""
    inserted = eol.join((
        f"{indent}- target: {{fileID: {slot.file_id}, guid: {prefab.source_guid}, type: 3}}",
        f"{indent}  propertyPath: {slot.prop}",
        f"{indent}  value: {raw}",
        f"{indent}  objectReference: {{fileID: 0}}",
    ))
    text = _splice(prefab.text, insert_at, insert_at, prefix + inserted + suffix)
    if marker.raw == "[]":
        text = _splice(text, marker.start, marker.end, "")
    inline_offset = marker.start - value_start if marker.raw == "[]" else None
    return text, {"missing": True, "inline_offset": inline_offset, "prefix": prefix}


def _remove(slot: Slot, desired: dict) -> str:
    prefab = slot.inspector.prefab
    mod = slot.modification
    if not mod:
        return prefab.text
    start = mod.start
    prefix = desired.get("prefix", "")
    if prefix and mod.end == len(prefab.text) and prefab.text[start - len(prefix):start] == prefix:
        start -= len(prefix)
    text = _splice(prefab.text, start, mod.end, "")
    if desired.get("inline_offset") is not None and len(prefab.modifications) == 1:
        _, _, value_start, _, _ = _listing(prefab)
        insert_at = value_start + desired["inline_offset"]
        text = _splice(text, insert_at, insert_at, "[]")
    return text


def _replace(slot: Slot, raw: str, remove_padding: tuple[str, str] = ("", "")) -> tuple[str, tuple[str, str]]:
    scalar = slot.value_token
    text = slot.inspector.prefab.text
    start, end = scalar.start, scalar.end
    left = " " if raw and text[start - 1:start] == ":" else ""
    right = " " if raw and text[end:end + 1] == "#" else ""
    if remove_padding[0] and text[start - 1:start] == " ":
        start -= 1
    if remove_padding[1] and text[end:end + 1] == " ":
        end += 1
    return _splice(text, start, end, left + raw + right), (left, right)


def _commit(project: Project, originals: dict[Path, str], history: dict) -> None:
    root = project.root
    journal = metadata_path(root, HISTORY)
    ignore = metadata_path(root, ".gitignore")
    for path, text in originals.items():
        if path.resolve() != path or path.read_bytes() != text.encode("utf-8"):
            raise HTTPException(409, "Prefab changed during editing")
    journal.parent.mkdir(exist_ok=True)
    try:
        ignored = ignore.read_bytes().decode("utf-8")
    except FileNotFoundError:
        ignored = ""
    if HISTORY not in ignored.splitlines():
        separator = "\n" if ignored and not ignored.endswith("\n") else ""
        _atomic_write(ignore, ignored + separator + HISTORY + "\n")

    applied = []
    try:
        for path, text in project.pending.items():
            if text != originals[path]:
                _atomic_write(path, text)
                applied.append(path)
        write_json(journal, history)
    except OSError:
        for path in reversed(applied):
            _atomic_write(path, originals[path])
        raise


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def edit_many(project: Project, edits: list[dict], summary: str | None, by: str = "tab") -> tuple[int, dict]:
    history = load_history(project.root)
    steps = history["steps"]
    step_id = steps[-1]["id"] + 1 if steps else 1
    originals = {}
    records = []
    for edit in edits:
        prefab_path(project, edit["path"])
    # Bases before their variants: a variant that inherits the field then sees the base's new value and needs no
    # override of its own (a bulk edit of a base and its variants keeps the variants inheriting).
    for edit in sorted(edits, key=lambda e: len(project.lineage(e["path"]))):
        path, fid, key, part = (edit[k] for k in ("path", "file_id", "key", "part"))
        slot = _slot(project, path, fid, key, part)
        file = prefab_path(project, path)
        originals.setdefault(file, slot.inspector.prefab.text)
        raw = _replacement(slot, edit["value"])
        current = slot.value_token
        variant = slot.inspector.prefab.instance is not None
        if variant and slot.modification is None and _same(current.value, token(raw, 0).value):
            continue  # already inherits this value
        layout = {}
        if variant and slot.modification is None:
            text, layout = _insert(slot, raw)
        else:
            text, padding = _replace(slot, raw)
            if any(padding):
                layout["padding"] = padding
        project.pending[file] = text
        records.append({
            "path": path, "file_id": fid, "key": key, "part": part, "variant": variant,
            "before": _state(current.value, current.raw, **layout),
            "after": _state(token(raw, 0).value, raw),
        })
    if not records:
        raise HTTPException(400, "Nothing to change: every prefab already has that value")
    active = _active(history)
    active.append({
        "id": step_id, "at": time.time(), "summary": summary or f"Edit {label(edits[0]['key'])}", "by": by,
        "edits": records,
    })
    history = {"position": min(len(active), LIMIT), "steps": active[-LIMIT:]}
    _commit(project, originals, history)
    return step_id, history


def move(project: Project, *, redo: bool, force: bool) -> dict:
    history = load_history(project.root)
    position, steps = history["position"], history["steps"]
    if (redo and position == len(steps)) or (not redo and position == 0):
        return {"ok": True, "position": position, "paths": []}
    step = steps[position if redo else position - 1]
    originals = {}
    conflicts = []
    for edit in step["edits"] if redo else reversed(step["edits"]):
        path, fid, key, part = (edit[k] for k in ("path", "file_id", "key", "part"))
        expected = _encoding(edit["before" if redo else "after"])
        desired = _encoding(edit["after" if redo else "before"])
        actual = None
        try:
            slot = _slot(project, path, fid, key, part)
            actual = slot.value_token.value
        except HTTPException as exc:
            if force or exc.status_code not in {400, 404}:
                raise
            slot = None
        if slot is None or (actual != expected["value"] and not force):
            conflicts.append({"path": path, "key": key, "expected": expected["value"], "actual": actual})
            continue
        file = prefab_path(project, path)
        originals.setdefault(file, slot.inspector.prefab.text)
        if desired.get("missing"):
            text = _remove(slot, desired)
        elif slot.inspector.prefab.instance and not slot.modification:
            text, _ = _insert(slot, desired["raw"])
        else:
            text, _ = _replace(slot, desired["raw"], tuple(desired.get("padding", ("", ""))))
        project.pending[file] = text

    if conflicts:
        return {"conflict": conflicts}
    history["position"] += 1 if redo else -1
    _commit(project, originals, history)
    return {"ok": True, "position": history["position"], "paths": list(dict.fromkeys(e["path"] for e in step["edits"]))}
