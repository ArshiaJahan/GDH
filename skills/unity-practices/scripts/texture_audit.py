#!/usr/bin/env python3
"""Audit Unity texture import settings (.meta files) against a profile, without opening Unity.

    texture_audit.py <Assets dir> [--profile mobile|desktop|pixel] [--max 40]

One line per violation (`path RULE detail`), then a per-rule summary and a last line
`RESULT: OK textures=N` or `RESULT: FAIL violations=N textures=N`. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tga", ".psd", ".tif", ".tiff", ".exr", ".hdr", ".bmp", ".gif"}
SKIP_DIRS = {"Library", "Temp", "Logs", "obj", "Build", "Builds", "PackageCache"}
TYPE_DEFAULT, TYPE_NORMAL, TYPE_SPRITE = 0, 1, 8
UNCOMPRESSED_FORMATS = {3, 4, 5, 14, 17, 1}  # RGB24, RGBA32, ARGB32, BGRA32, RGBAHalf, Alpha8
NORMAL_NAME = re.compile(r"(_n|_nrm|_norm|_normal|normalmap)$", re.I)
DATA_NAME = re.compile(r"(_mask|_orm|_mra|_mods|_metal(lic)?|_rough(ness)?|_ao|_height|_spec)$", re.I)
PROFILES = {
    "mobile": {"max_size": 2048, "platforms": ("Android", "iPhone"), "pixel": False},
    "desktop": {"max_size": 4096, "platforms": ("Standalone",), "pixel": False},
    "pixel": {"max_size": 4096, "platforms": ("Standalone", "Android", "iPhone", "WebGL"), "pixel": True},
}


def _int(text: str, key: str, default: int | None = None) -> int | None:
    m = re.search(rf"^\s*{key}:\s*(-?\d+)", text, re.M)
    return int(m.group(1)) if m else default


def parse_meta(text: str) -> dict | None:
    if "TextureImporter:" not in text:
        return None
    head = text.split("platformSettings:")[0]
    info = {
        "mips": _int(head, "enableMipMap", 0), "srgb": _int(head, "sRGBTexture", 1),
        "readable": _int(head, "isReadable", 0), "type": _int(head, "textureType", 0),
        "filter": _int(head, "filterMode", 1), "max": _int(head, "maxTextureSize", 2048),
        "compression": _int(head, "textureCompression", None), "platforms": {},
    }
    for block in re.split(r"\n\s*- serializedVersion:", text.split("platformSettings:", 1)[1]) if "platformSettings:" in text else []:
        m = re.search(r"buildTarget:\s*(\S+)", block)
        if not m:
            continue
        info["platforms"][m.group(1)] = {k: _int(block, k) for k in
                                         ("maxTextureSize", "textureFormat", "textureCompression", "overridden",
                                          "crunchedCompression")}
    default = info["platforms"].get("DefaultTexturePlatform", {})
    if default.get("maxTextureSize") is not None:
        info["max"] = default["maxTextureSize"]
    if default.get("textureCompression") is not None:
        info["compression"] = default["textureCompression"]
    if info["compression"] is None:
        info["compression"] = 1
    return info


def effective(info: dict, platform: str) -> tuple[int, int, int]:
    """(max size, compression, format) for a platform: its override when overridden, else the default."""
    p = info["platforms"].get(platform) or {}
    if p.get("overridden") == 1:
        return (p.get("maxTextureSize") or info["max"], p.get("textureCompression", info["compression"]),
                p.get("textureFormat") if p.get("textureFormat") is not None else -1)
    return info["max"], info["compression"], -1


def check(stem: str, info: dict, profile: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if info["readable"] == 1:
        out.append(("READ_WRITE", "Read/Write is on (doubles memory); turn it off unless a script reads pixels"))
    if NORMAL_NAME.search(stem) and info["type"] != TYPE_NORMAL:
        out.append(("NORMAL_TYPE", "looks like a normal map but Texture Type isn't Normal map"))
    if DATA_NAME.search(stem) and info["srgb"] == 1 and info["type"] != TYPE_NORMAL:
        out.append(("SRGB_DATA", "data/mask texture with sRGB on; turn sRGB off"))
    if profile["pixel"]:
        if info["type"] == TYPE_SPRITE:
            if info["filter"] != 0:
                out.append(("PIXEL_FILTER", "pixel-art sprite without Point filtering"))
            if info["compression"] != 0:
                out.append(("PIXEL_COMPRESSION", "pixel-art sprite is compressed; use None"))
            if info["mips"] == 1:
                out.append(("SPRITE_MIPS", "sprite has mipmaps on"))
        return out
    if info["type"] == TYPE_SPRITE and info["mips"] == 1:
        out.append(("SPRITE_MIPS", "sprite/UI texture has mipmaps on (wasted memory in screen space)"))
    for plat in profile["platforms"]:
        size, comp, fmt = effective(info, plat)
        if size > profile["max_size"]:
            out.append(("MAX_SIZE", f"{plat} max size {size} > {profile['max_size']}"))
        if comp == 0 or fmt in UNCOMPRESSED_FORMATS:
            out.append(("UNCOMPRESSED", f"{plat} is uncompressed; use ASTC (mobile) or BC7/DXT5 (desktop)"))
    return out


def iter_metas(root: Path):
    for p in sorted(root.rglob("*.meta")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if Path(p.stem).suffix.lower() in IMAGE_EXT:
            yield p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="desktop")
    ap.add_argument("--max", type=int, default=40, help="most violation lines to print (the summary counts all)")
    a = ap.parse_args(argv)
    if not a.root.is_dir():
        print(f"RESULT: FAIL no such folder: {a.root}")
        return 2
    profile, counts, shown, textures = PROFILES[a.profile], Counter(), 0, 0
    for meta in iter_metas(a.root):
        info = parse_meta(meta.read_text(encoding="utf-8", errors="replace"))
        if info is None:
            continue
        textures += 1
        asset = Path(meta.stem)
        for rule, detail in check(asset.stem, info, profile):
            counts[rule] += 1
            if shown < a.max:
                print(f"{meta.relative_to(a.root).with_suffix('')} {rule} {detail}")
                shown += 1
    total = sum(counts.values())
    if total > shown:
        print(f"... {total - shown} more not shown (raise --max or fix these first)")
    if counts:
        print("SUMMARY " + " ".join(f"{k}={v}" for k, v in counts.most_common()))
        print(f"RESULT: FAIL violations={total} textures={textures} profile={a.profile}")
        return 1
    print(f"RESULT: OK textures={textures} profile={a.profile}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
