"""Images sent to models: converted and shrunk once when attached (macOS `sips`), and checked again
on every request so one missing, huge or odd file can't break every later turn of a session."""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import shutil
import struct
import subprocess
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

log = logging.getLogger("workspace.media")

# What Anthropic and OpenAI accept inline; anything else (HEIC, TIFF, BMP, …) is converted to JPEG.
SENDABLE = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 3_750_000  # 5 MB once base64-encoded (the per-image limit on Bedrock; the Claude API takes 10 MB)
# Longest side we send. Anthropic: 8000 px per image, but a request with more than 20 images gets a
# stricter per-image limit (2000 px historically; the docs now say keep each side ≤ 3000 px) and
# models downscale to 1568 px (2576 px on high-resolution models) anyway. OpenAI fits "high"
# detail into 2048 px. 2000 px is safe under all of them.
MAX_SIDE = 2000
HARD_MAX_SIDE = 8000  # Anthropic rejects anything larger even in a single-image request


def _sips() -> str | None:
    return shutil.which("sips") or (str(Path("/usr/bin/sips")) if Path("/usr/bin/sips").exists() else None)


def image_dims(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG, GIF, WebP or JPEG header, or None when it isn't one of those (or is cut off)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            kind = data[12:16]
            if kind == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if kind == b"VP8L":
                b = int.from_bytes(data[21:25], "little")
                return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
            if kind == b"VP8X":
                return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
            return None
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 4 <= len(data):
                if data[i] != 0xFF:
                    return None
                marker = data[i + 1]
                if marker == 0xFF:  # fill byte
                    i += 1
                    continue
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length
                    i += 2
                    continue
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # SOFn
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + seg
    except (struct.error, IndexError):
        return None
    return None


def file_dims(p: Path) -> tuple[int, int] | None:
    """image_dims of a file (reads at most its first 2 MB: JPEG metadata can push the size far in)."""
    try:
        with p.open("rb") as f:
            return image_dims(f.read(2 << 20))
    except OSError:
        return None


def _longest_side(sips: str, p: Path) -> int | None:
    if dims := file_dims(p):
        return max(dims)
    try:
        out = subprocess.run([sips, "-g", "pixelWidth", "-g", "pixelHeight", str(p)], capture_output=True,
                             text=True, timeout=30).stdout
        sides = [int(ln.split(":")[1]) for ln in out.splitlines() if ln.strip().startswith("pixel")]
        return max(sides) if sides else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _convert(sips: str, src: Path, stem: Path, mime: str, size: int) -> tuple[Path, str] | None:
    """Write src as an image every provider takes (≤ MAX_SIDE px, ≤ MAX_IMAGE_BYTES) to stem.png or
    stem.jpg. A PNG that's only too large in pixels stays PNG (transparency, crisp text); everything
    else becomes JPEG, at lower sizes and quality until it fits. None if sips fails."""
    longest = _longest_side(sips, src)
    attempts: list[tuple[str, int, int | None]] = []
    if mime == "image/png" and size <= MAX_IMAGE_BYTES:
        attempts.append(("png", MAX_SIDE, None))
    attempts += [("jpeg", MAX_SIDE, 85), ("jpeg", 1568, 75), ("jpeg", 1024, 70)]
    for fmt, side, quality in attempts:
        ext = ".png" if fmt == "png" else ".jpg"
        tmp = stem.with_name(stem.name + ".tmp" + ext)
        resize = ["-Z", str(side)] if longest is None or longest > side else []  # -Z would also upscale
        opts = ["-s", "formatOptions", str(quality)] if quality else []
        try:
            subprocess.run([sips, "-s", "format", fmt, *opts, *resize, str(src), "--out", str(tmp)],
                           capture_output=True, timeout=60, check=True)
            if tmp.stat().st_size <= MAX_IMAGE_BYTES or side == 1024:
                out = stem.with_name(stem.name + ext)
                tmp.replace(out)
                return out, "image/png" if fmt == "png" else "image/jpeg"
            tmp.unlink(missing_ok=True)
        except (OSError, subprocess.SubprocessError) as e:  # incl. sips exiting 0 without output
            log.warning("couldn't convert %s for sending: %s", src.name, e)
            tmp.unlink(missing_ok=True)
            return None
    return None


def prepare_image(path: str | Path, mime: str, out_dir: Path) -> tuple[str, str, str | None]:
    """(path to send, its mime, note for the user). The original is never changed; a converted copy
    goes to out_dir (named by the original's content, so repeated sends reuse it). Converted: formats
    the providers don't take, files over MAX_IMAGE_BYTES and images over MAX_SIDE px. Without `sips`
    (not macOS) the original is returned and the request-time check below has the last word."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return str(p), mime, None
    dims = file_dims(p) if mime in SENDABLE else None
    too_wide = bool(dims and max(dims) > MAX_SIDE)
    if mime in SENDABLE and size <= MAX_IMAGE_BYTES and not too_wide:
        return str(p), mime, None
    sips = _sips()
    if not sips:
        return str(p), mime, None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    stem = out_dir / h.hexdigest()[:24]
    got: tuple[Path, str] | None = next(((stem.with_name(stem.name + ext), m) for ext, m in
                                         ((".png", "image/png"), (".jpg", "image/jpeg"))
                                         if stem.with_name(stem.name + ext).exists()), None)
    if got is None:
        out_dir.mkdir(parents=True, exist_ok=True)
        got = _convert(sips, p, stem, mime, size)
        if got is None:
            return str(p), mime, None
    kind = mime.split("/")[-1].upper() if mime.startswith("image/") else "image"
    if mime not in SENDABLE:
        what = f"converted {kind} to JPEG"
    elif size > MAX_IMAGE_BYTES:
        what = f"shrunk from {size / 1e6:.1f} MB"
    else:
        what = f"resized from {dims[0]}×{dims[1]} px" if dims else "resized"
    return str(got[0]), got[1], f"{p.name}: {what} for the model; the original is kept."


# Request-time shrinks (images in tool results, attachments from before the pixel check): kept in
# memory by content, so a long turn with screenshots runs sips once per image, not once per call.
_FIT_CACHE: OrderedDict[str, tuple[str, str]] = OrderedDict()
_FIT_CACHE_MAX = 64


def _fit(raw: bytes, mime: str) -> tuple[str, str] | None:
    """(mime, base64) of `raw` brought under MAX_SIDE / MAX_IMAGE_BYTES with sips, or None (no sips, failed)."""
    key = hashlib.sha256(raw).hexdigest()
    if key in _FIT_CACHE:
        _FIT_CACHE.move_to_end(key)
        return _FIT_CACHE[key]
    sips = _sips()
    if not sips:
        return None
    with tempfile.TemporaryDirectory(prefix="ws-img-") as td:
        src = Path(td) / ("in." + (mime.split("/")[-1] if mime.startswith("image/") else "img"))
        src.write_bytes(raw)
        got = _convert(sips, src, Path(td) / "out", mime, len(raw))
        if got is None:
            return None
        res = (got[1], base64.b64encode(got[0].read_bytes()).decode())
    _FIT_CACHE[key] = res
    while len(_FIT_CACHE) > _FIT_CACHE_MAX:
        _FIT_CACHE.popitem(last=False)
    return res


MAX_REQUEST_MEDIA = 24_000_000  # base64 chars of inline media per request (Anthropic caps requests at 32 MB)


def cap_media(wire: list[dict], limit: int = MAX_REQUEST_MEDIA) -> list[dict]:
    """Wire messages (Anthropic `messages` or OpenAI `input`) with the oldest inline images and files
    replaced by a note when together they'd push the request over the provider's size limit; the
    newest stay. Changes the given structure in place and returns it."""
    refs: list[tuple[list, int, int, str]] = []

    def walk(blocks: list) -> None:
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            src = b.get("source")
            if b.get("type") in ("image", "document") and isinstance(src, dict) and src.get("type") == "base64":
                refs.append((blocks, i, len(src.get("data") or ""), b.get("title") or b["type"]))
            elif b.get("type") == "input_image" and str(b.get("image_url", "")).startswith("data:"):
                refs.append((blocks, i, len(b["image_url"]), "image"))
            elif b.get("type") == "input_file" and str(b.get("file_data", "")).startswith("data:"):
                refs.append((blocks, i, len(b["file_data"]), b.get("filename") or "file"))
            elif isinstance(b.get("content"), list):  # tool_result
                walk(b["content"])

    for m in wire:
        if isinstance(m, dict) and isinstance(m.get("content"), list):
            walk(m["content"])
    total = sum(r[2] for r in refs)
    for blocks, i, size, label in refs:
        if total <= limit:
            break
        kind = "input_text" if str(blocks[i].get("type", "")).startswith("input_") else "text"
        blocks[i] = {"type": kind, "text": f"[{label}: left out of this request to keep it under the provider's size "
                                            "limit; attach it again if it's still needed]"}
        total -= size
    return wire


def image_payload(media_type: str, data: str | None, path: str | None, name: str | None) -> tuple[str, str] | str:
    """(media_type, base64) for an image block, or a placeholder text when it can't be sent: the file
    is gone or unreadable, too big, or a format the providers don't take. Images over MAX_SIDE px or
    MAX_IMAGE_BYTES (in tool results too) are shrunk with sips; without it, only what no provider
    takes (over HARD_MAX_SIDE px or MAX_IMAGE_BYTES) becomes a placeholder."""
    label = f"Image '{name or (Path(path).name if path else 'image')}'"
    if data is not None:
        if media_type not in SENDABLE:
            return f"[{label}: {media_type} isn't a format the model accepts; not shown]"
        try:
            head = base64.b64decode(data[:2_800_000])  # a multiple of 4: decodes on its own
        except ValueError:
            return media_type, data
        dims = image_dims(head)
        size = len(data) * 3 // 4
        if (dims and max(dims) > MAX_SIDE) or size > MAX_IMAGE_BYTES:
            try:
                raw = base64.b64decode(data)
            except ValueError:
                return media_type, data
            return _fit_or_note(raw, media_type, dims, label) or (media_type, data)
        return media_type, data
    if not path:
        return f"[{label}: no data; not shown]"
    try:
        p = Path(path)
        size = p.stat().st_size
        if media_type not in SENDABLE:
            return f"[{label} ({media_type}) isn't a format the model accepts; not shown. Attach it again as PNG or JPEG.]"
        if size > 50_000_000:
            return f"[{label} is {size / 1e6:.1f} MB, over the model's image limit; not shown. Attach a smaller copy.]"
        raw = p.read_bytes()
    except OSError:
        return f"[{label} is no longer available (deleted or moved); not shown]"
    dims = image_dims(raw)
    if (dims and max(dims) > MAX_SIDE) or size > MAX_IMAGE_BYTES:
        return _fit_or_note(raw, media_type, dims, label) or (media_type, base64.b64encode(raw).decode())
    return media_type, base64.b64encode(raw).decode()


def _fit_or_note(raw: bytes, mime: str, dims: tuple[int, int] | None, label: str) -> tuple[str, str] | str | None:
    """A shrunk copy; else a note when no provider would take it; else None (send it as it is)."""
    if fitted := _fit(raw, mime):
        return fitted
    if len(raw) > MAX_IMAGE_BYTES:
        return f"[{label} is {len(raw) / 1e6:.1f} MB, over the model's image limit; not shown. Attach a smaller copy.]"
    if dims and max(dims) > HARD_MAX_SIDE:
        return (f"[{label} is {dims[0]}×{dims[1]} px, over the model's image limit; not shown. "
                "Attach a smaller copy.]")
    return None


# ---------------------------------------------------------------- rejected images

_IMAGE_REJECT = re.compile(r"image", re.I)
_IMAGE_REJECT_WHY = re.compile(r"dimension|pixel|too (large|big)|exceed|maximum|max allowed|size", re.I)


def is_image_rejected(status: int | None, message: str) -> bool:
    """A provider's 400 about an image's size or dimensions (not about the whole request)."""
    m = message or ""
    return status in (400, 413, None) and bool(_IMAGE_REJECT.search(m)) and bool(_IMAGE_REJECT_WHY.search(m))


def stub_rejected_images(messages: list[Any], error: str) -> tuple[list[Any], int]:
    """Messages (copies; the stored ones are untouched) with the images the provider rejected replaced
    by a note: those over the pixel limit the error states (e.g. "… many-image requests: 2000 pixels")
    or over its byte limit; when it states neither, or nothing matches, every image."""
    from .types import ImageBlock, Message, TextBlock, ToolResultBlock

    px = re.search(r"(\d{3,6})\s*(?:px|pixels)", error or "", re.I)
    by = re.search(r">\s*(\d{4,})\s*bytes", error or "", re.I)
    limit_px = int(px.group(1)) if px else None
    limit_b = int(by.group(1)) if by else None

    def offending(b: Any) -> bool:
        if limit_px is None and limit_b is None:
            return True
        try:
            raw = base64.b64decode(b.data[:2_800_000]) if b.data else (Path(b.path).read_bytes() if b.path else b"")
        except (OSError, ValueError):
            return False
        dims = image_dims(raw)
        size = len(b.data) if b.data else len(raw) * 4 // 3
        return bool((limit_px and dims and max(dims) > limit_px) or (limit_b and size > limit_b))

    def note(b: Any) -> Any:
        return TextBlock(text=f"[Image '{b.name or (Path(b.path).name if b.path else 'image')}' left out: the "
                              "provider rejected its size. Attach a smaller copy if it's still needed.]")

    def run(pick: Any) -> tuple[list[Any], int]:
        n, out = 0, []

        def swap(b: Any) -> Any:
            nonlocal n
            if isinstance(b, ImageBlock) and pick(b):
                n += 1
                return note(b)
            if isinstance(b, ToolResultBlock):
                inner = [swap(c) for c in b.content]
                return b if all(x is y for x, y in zip(inner, b.content)) else b.model_copy(update={"content": inner})
            return b

        for m in messages:
            content = [swap(b) for b in m.content]
            changed = any(x is not y for x, y in zip(content, m.content))
            out.append(Message(id=m.id, role=m.role, content=content, meta=m.meta) if changed else m)
        return out, n

    out, n = run(offending)
    if n == 0:
        out, n = run(lambda b: True)
    return out, n
