"""JSON batch runner.

A batch file is a list of objects: {"kind": "image"|"model"|"sound", "out": "...", "prompt": "...", ...}.
Extra keys are the keyword arguments of generate_image / generate_model / generate_sound (see README).
A sound item may add "variants": N to make <out stem>_1..N.wav with seed+i.
"""
import json
import os

from . import client
from .audio import generate_sound, generate_variants
from .image import generate_image
from .model3d import generate_model

KINDS = ("image", "model", "sound")


def item_name(item):
    return item.get("name") or os.path.splitext(os.path.basename(item.get("out", "")))[0]


def _outputs(item):
    out = item["out"]
    if item["kind"] == "sound" and item.get("variants"):
        stem, _ = os.path.splitext(out)
        return [f"{stem}_{i}.wav" for i in range(1, int(item["variants"]) + 1)]
    if item["kind"] == "model" and item.get("ref_only"):
        return [item.get("ref_out") or os.path.splitext(out)[0] + "_ref.png"]
    return [out]


def run_item(item):
    """Run one item. Returns a short result string; raises on failure."""
    kind = item["kind"]
    a = {k: v for k, v in item.items() if k not in ("kind", "name", "out", "prompt", "variants")}
    if kind == "image":
        generate_image(item["prompt"], item["out"], **a)
        return item["out"]
    if kind == "model":
        r = generate_model(item["prompt"], item["out"], **a)
        return r["glb"] or r["ref"]
    if kind == "sound":
        if item.get("variants"):
            stem, _ = os.path.splitext(item["out"])
            outs = generate_variants(item["prompt"], os.path.dirname(stem) or ".", os.path.basename(stem),
                                     n=int(item["variants"]), **a)
            bad = [o for o in outs if isinstance(o, tuple)]
            if bad:
                raise client.ComfyError(f"{len(bad)} take(s) failed: {bad[0][1][:200]}")
            return ", ".join(outs)
        generate_sound(item["prompt"], item["out"], **a)
        return item["out"]
    raise client.ComfyError(f"unknown kind {kind!r} (use one of {KINDS})")


def run_items(items, names=(), force=False):
    """Run a list of items. Prints one line per item and continues on failure. Returns (ok, skipped, failed)."""
    ok = skipped = failed = 0
    names = set(names or ())
    for item in items:
        name = item_name(item)
        if names and name not in names:
            continue
        if item.get("kind") not in KINDS or "out" not in item or "prompt" not in item:
            print(f"{name or '?'} FAILED item needs kind (image|model|sound), out and prompt", flush=True)
            failed += 1
            continue
        if not force and all(os.path.exists(o) for o in _outputs(item)):
            print(f"{item['kind']} {name} skipped (exists)", flush=True)
            skipped += 1
            continue
        try:
            res = run_item(item)
            print(f"{item['kind']} {name} ok {res}", flush=True)
            ok += 1
        except (client.ComfyError, OSError, KeyError, TypeError, SystemExit) as e:
            print(f"{item['kind']} {name} FAILED {str(e)[:500]}", flush=True)
            failed += 1
    print(f"done: {ok} ok, {skipped} skipped, {failed} failed", flush=True)
    return ok, skipped, failed


def run_batch_file(path, names=(), force=False):
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        raise client.ComfyError(f"{path}: a comfyplug batch is a JSON list of objects (old row-lists go through the "
                                "old wrapper scripts)")
    return run_items(items, names, force)
