#!/usr/bin/env python3
"""asset_audit.py - check Unity import settings (.meta files) against folder rules (python3 stdlib only).

Default rules mirror templates/Editor/ImportRules.cs (ImportRuleConfig):
  Assets/Art/Sprites/**   textures: Sprite, Point filter, no mipmaps, uncompressed (default platform and every
                          overridden platform), Clamp, PPU == --ppu (default 16), alpha is transparency
  Assets/Audio/SFX/**     audio: Decompress On Load, ADPCM, preload, no load-in-background
  Assets/Audio/Music/**   audio: Streaming, Vorbis, no preload, load in background
  Assets/Art/Atlases/**   .spriteatlasv2: Point, no mipmaps, no rotation, no tight packing, include in build
Anything under a folder named _NoRules is skipped (same opt-out as ImportRules.cs).

Usage:
  asset_audit.py [PROJECT_ROOT] [--ppu N] [--rules rules.json] [--print-default-rules] [--strict] [--json] [--max N]
  --rules replaces the defaults with a JSON list shaped like --print-default-rules output.
  --strict also fails on warnings (asset without .meta = never imported, unknown importer, audio platform overrides).
  Rule folders that do not exist are listed as notes and never fail.
Exit codes: 0 = no violations, 1 = violations, 2 = usage/setup error.
Last line is machine-readable:  RESULT: OK ...  |  RESULT: FAIL ...  (not printed with --json)
"""
import argparse
import json
import os
import sys

TEX_EXTS = [".png", ".jpg", ".jpeg", ".psd", ".tga", ".gif", ".bmp", ".tif", ".tiff"]
AUDIO_EXTS = [".wav", ".ogg", ".mp3", ".aif", ".aiff", ".flac", ".mod", ".it", ".s3m", ".xm"]
OPT_OUT = "_NoRules"

# Readable names for the numbers Unity writes into .meta files (used in messages only).
NAMES = {
    "textureType": {"0": "Default", "1": "NormalMap", "2": "GUI", "8": "Sprite", "10": "SingleChannel"},
    "filterMode": {"0": "Point", "1": "Bilinear", "2": "Trilinear"},
    "textureCompression": {"0": "Uncompressed", "1": "Compressed", "2": "CompressedHQ", "3": "CompressedLQ"},
    "wrapU": {"0": "Repeat", "1": "Clamp", "2": "Mirror", "3": "MirrorOnce"},
    "wrapV": {"0": "Repeat", "1": "Clamp", "2": "Mirror", "3": "MirrorOnce"},
    "loadType": {"0": "DecompressOnLoad", "1": "CompressedInMemory", "2": "Streaming"},
    "compressionFormat": {"0": "PCM", "1": "Vorbis", "2": "ADPCM", "3": "MP3"},
}


def default_rules(ppu):
    return [
        {
            "name": "pixel-sprites", "folder": "Assets/Art/Sprites", "exts": TEX_EXTS, "importer": "TextureImporter",
            "expect": {
                "textureType": "8",
                "textureSettings.filterMode": "0",
                "mipmaps.enableMipMap": "0",
                "spritePixelsToUnits": str(ppu),
                "textureSettings.wrapU": "1",
                "textureSettings.wrapV": "1",
                "alphaIsTransparency": "1",
                "platform[DefaultTexturePlatform].textureCompression": "0",
            },
            "overridden_platforms_expect": {"textureCompression": "0"},
        },
        {
            "name": "sfx", "folder": "Assets/Audio/SFX", "exts": AUDIO_EXTS, "importer": "AudioImporter",
            "expect": {
                "defaultSettings.loadType": "0",
                "defaultSettings.compressionFormat": "2",
                "defaultSettings.preloadAudioData": "1",
                "loadInBackground": "0",
            },
            "warn_platform_overrides": True,
        },
        {
            "name": "music", "folder": "Assets/Audio/Music", "exts": AUDIO_EXTS, "importer": "AudioImporter",
            "expect": {
                "defaultSettings.loadType": "2",
                "defaultSettings.compressionFormat": "1",
                "defaultSettings.preloadAudioData": "0",
                "loadInBackground": "1",
            },
            "warn_platform_overrides": True,
        },
        {
            "name": "atlases", "folder": "Assets/Art/Atlases", "exts": [".spriteatlasv2"], "importer": "SpriteAtlasImporter",
            "expect": {
                "textureSettings.filterMode": "0",
                "textureSettings.generateMipMaps": "0",
                "packingSettings.enableRotation": "0",
                "packingSettings.enableTightPacking": "0",
                "bindAsDefault": "1",
            },
        },
    ]


class _Node:
    __slots__ = ("indent", "name", "is_item", "count")

    def __init__(self, indent, name, is_item=False):
        self.indent, self.name, self.is_item, self.count = indent, name, is_item, 0


def flatten_meta(text):
    """Flatten the block-style YAML Unity writes into .meta files: {"TextureImporter.mipmaps.enableMipMap": "0",
    "TextureImporter.platformSettings[0].buildTarget": "DefaultTexturePlatform", ...}. Flow values stay strings."""
    out = {}
    stack = [_Node(-1, "")]

    def path_for(key):
        parts = [n.name for n in stack[1:]] + [key]
        s = ""
        for p in parts:
            s += p if p.startswith("[") else ("." + p if s else p)
        return s

    def put(key_val, indent):
        key, sep, val = key_val.partition(":")
        if not sep:
            return  # continuation of a wrapped scalar; ignore
        key, val = key.strip(), val.strip()
        if val == "":
            stack.append(_Node(indent, key))
        else:
            out[path_for(key)] = val

    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("%") or raw.startswith("---") or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        s = raw.strip()
        if s == "-" or s.startswith("- "):
            while len(stack) > 1 and stack[-1].indent > indent:
                stack.pop()
            while len(stack) > 1 and stack[-1].is_item and stack[-1].indent == indent:
                stack.pop()
            parent = stack[-1]
            idx = parent.count
            parent.count += 1
            stack.append(_Node(indent, "[%d]" % idx, is_item=True))
            rest = s[2:].strip() if s.startswith("- ") else ""
            if rest:
                if ":" in rest:
                    put(rest, indent + 2)
                else:
                    out[path_for("value")] = rest  # scalar list item, e.g. "- 1"
        else:
            while len(stack) > 1 and stack[-1].indent >= indent:
                stack.pop()
            put(s, indent)
    return out


def platform_entries(flat, importer):
    """{buildTarget: {key: value}} from <importer>.platformSettings[i].*"""
    prefix = importer + ".platformSettings["
    entries = {}
    for k, v in flat.items():
        if not k.startswith(prefix):
            continue
        idx, _, rest = k[len(prefix):].partition("].")
        entries.setdefault(idx, {})[rest] = v
    return {e.get("buildTarget", "#" + i): e for i, e in entries.items()}


def lookup(flat, importer, key, platforms):
    if key.startswith("platform["):
        target, _, sub = key[len("platform["):].partition("].")
        return platforms.get(target, {}).get(sub)
    return flat.get(importer + "." + key)


def pretty(key, value):
    if value is None:
        return "<absent>"
    last = key.rsplit(".", 1)[-1]
    name = NAMES.get(last, {}).get(value)
    return "%s(%s)" % (value, name) if name else value


def detect_importer(flat):
    for k in flat:
        head = k.split(".", 1)[0].split("[", 1)[0]
        if head.endswith("Importer"):
            return head
    return None


def audit(project, rules):
    violations, warnings, notes, checked, ppus = [], [], [], 0, {}
    for rule in rules:
        folder = os.path.join(project, rule["folder"])
        if not os.path.isdir(folder):
            notes.append("rule %s: folder %s does not exist (skipped)" % (rule["name"], rule["folder"]))
            continue
        exts = set(e.lower() for e in rule.get("exts", []))
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(d for d in dirnames if d != OPT_OUT and not d.startswith(".") and not d.endswith("~"))
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() not in exts:
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, project)
                meta = path + ".meta"
                if not os.path.isfile(meta):
                    warnings.append("%s: no .meta (never imported; open the project or refresh_unity)" % rel)
                    continue
                with open(meta, encoding="utf-8", errors="replace") as f:
                    flat = flatten_meta(f.read())
                importer = detect_importer(flat)
                if importer != rule["importer"]:
                    warnings.append("%s: importer %s, rule %s expects %s (skipped)" % (rel, importer, rule["name"], rule["importer"]))
                    continue
                checked += 1
                platforms = platform_entries(flat, importer)
                for key, want in rule.get("expect", {}).items():
                    got = lookup(flat, importer, key, platforms)
                    if got != str(want):
                        violations.append("%s [%s] %s = %s, expected %s"
                                          % (rel, rule["name"], key, pretty(key, got), pretty(key, str(want))))
                for target, entry in sorted(platforms.items()):
                    if target == "DefaultTexturePlatform" or entry.get("overridden") != "1":
                        continue
                    for key, want in rule.get("overridden_platforms_expect", {}).items():
                        if entry.get(key) != str(want):
                            violations.append("%s [%s] platform %s override %s = %s, expected %s"
                                              % (rel, rule["name"], target, key, pretty(key, entry.get(key)), pretty(key, str(want))))
                if rule.get("warn_platform_overrides") and flat.get(importer + ".platformSettingOverrides", "{}") != "{}":
                    warnings.append("%s [%s]: has per-platform audio overrides; check them by hand" % (rel, rule["name"]))
                ppu = flat.get(importer + ".spritePixelsToUnits")
                if importer == "TextureImporter" and ppu is not None:
                    ppus[ppu] = ppus.get(ppu, 0) + 1
    return violations, warnings, notes, checked, ppus


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", default=".", help="Unity project root (default: cwd)")
    ap.add_argument("--ppu", type=int, default=16, help="expected Pixels Per Unit for sprites (default 16)")
    ap.add_argument("--rules", help="JSON rules file (replaces the defaults)")
    ap.add_argument("--print-default-rules", action="store_true", help="print the default rules as JSON and exit")
    ap.add_argument("--strict", action="store_true", help="warnings also fail")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--max", type=int, default=100, help="max lines printed per section (default 100)")
    a = ap.parse_args(argv)

    if a.print_default_rules:
        print(json.dumps(default_rules(a.ppu), indent=2))
        return 0
    project = os.path.abspath(a.project)
    if not os.path.isdir(os.path.join(project, "Assets")):
        print("RESULT: FAIL no Assets/ folder under %s" % project)
        return 2
    rules = default_rules(a.ppu)
    if a.rules:
        try:
            with open(a.rules, encoding="utf-8") as f:
                rules = json.load(f)
            assert isinstance(rules, list) and all("folder" in r and "importer" in r for r in rules)
        except (OSError, ValueError, AssertionError) as e:
            print("RESULT: FAIL bad rules file %s: %s" % (a.rules, e))
            return 2
        for r in rules:
            r.setdefault("name", r["folder"])

    violations, warnings, notes, checked, ppus = audit(project, rules)
    failed = bool(violations) or (a.strict and bool(warnings))
    if a.json:
        print(json.dumps({"project": project, "checked": checked, "ppu_values": ppus,
                          "violations": violations, "warnings": warnings, "notes": notes}, indent=2))
    else:
        print("asset_audit: project=%s rules=%d checked=%d sprite_ppu_values=%s"
              % (project, len(rules), checked, json.dumps(ppus, sort_keys=True)))
        for title, items in (("violations", violations), ("warnings", warnings), ("notes", notes)):
            if items:
                print("\n[%s] %d" % (title, len(items)))
                for x in items[: a.max]:
                    print("  " + x)
                if len(items) > a.max:
                    print("  ... %d more" % (len(items) - a.max))
    if not a.json:  # JSON mode prints only the JSON document; use the exit code
        print("RESULT: %s checked=%d violations=%d warnings=%d"
              % ("FAIL" if failed else "OK", checked, len(violations), len(warnings)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
