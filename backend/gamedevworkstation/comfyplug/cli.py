"""Command line: python -m comfyplug {check,image,edit,model,sound,workflow,batch,loop,normalize,measure} ..."""
import argparse
import json
import os
import sys

from . import client
from .batch import run_batch_file
from .image import generate_image
from .edit import edit_image
from .model3d import generate_model
from .audio import generate_sound, generate_variants
from . import postaudio
from .workflow import run_any


def build_parser():
    ap = argparse.ArgumentParser(prog="comfyplug", description="ComfyPlug: ComfyUI generation of images, image edits, 3D models, sound, and any workflow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="check ComfyUI, comfy-cli and ffmpeg")

    p = sub.add_parser("image", help="one image (Qwen Image 2.1)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--aspect", default="1:1 (Square)")
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--megapixels", type=float, default=1.0)
    p.add_argument("--transparent", action="store_true", help="ask for an alpha channel")

    p = sub.add_parser("edit", help="edit one image with an instruction (Qwen Image 2.1 edit)")
    p.add_argument("--image", required=True, help="input PNG/JPG")
    p.add_argument("--prompt", required=True, help="edit instruction")
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--steps", type=int, default=25)
    p.add_argument("--width", type=int, default=None, help="default: input width (max ~1 MP)")
    p.add_argument("--height", type=int, default=None)

    p = sub.add_parser("model", help="one 3D model (Qwen reference -> TRELLIS.2). Slow.")
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True, help="output .glb")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--image-seed", type=int, default=None, help="reference image seed (default: --seed)")
    p.add_argument("--view", default="three-quarter front view")
    p.add_argument("--faces", type=int, default=12000)
    p.add_argument("--texture", type=int, default=1024)
    p.add_argument("--ref-out", help="where to keep the reference image (default <out>_ref.png)")
    p.add_argument("--ref-only", action="store_true", help="make only the reference image, to review it first")
    p.add_argument("--from-image", help="skip step 1 and use this PNG as the reference")

    p = sub.add_parser("sound", help="one sound (Stable Audio 3 medium)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True, help="output .wav (with --variants N: writes <stem>_1..N.wav)")
    p.add_argument("--seconds", type=float, default=2.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--category", default="SFX")
    p.add_argument("--raw-out", help="also keep the untouched model output here")
    p.add_argument("--no-trim", action="store_true", help="skip silence cut / fade / normalise")
    p.add_argument("--sample-rate", type=int, default=44100, help="44100, or 22050 for short fidget clips")
    p.add_argument("--variants", type=int, default=0, help="make N takes with seed+i")

    p = sub.add_parser("workflow", help="run any ComfyUI workflow JSON and keep all its outputs (video too)")
    p.add_argument("file", help="workflow JSON (a path, or a bundled template name)")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--slot", action="append", default=[], metavar="NODE.INPUT=JSON",
                   help='set a node input, e.g. --slot 6.text=\'"a red fox"\' --slot 3.seed=7 (repeatable)')
    p.add_argument("--ext", action="append", default=[], help="keep only these output extensions (repeatable)")
    p.add_argument("--prefix", help="name outputs <prefix>_<n><ext>")
    p.add_argument("--timeout", type=int, default=1800)

    p = sub.add_parser("batch", help="run a JSON batch file")
    p.add_argument("file")
    p.add_argument("names", nargs="*", help="only items with these names (out file stem)")
    p.add_argument("--force", action="store_true", help="regenerate outputs that already exist")

    p = sub.add_parser("loop", help="make a seamless loop from a raw sound (numpy + ffmpeg)")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--seconds", type=float, default=4.0)
    p.add_argument("--crossfade", type=float, default=0.5)
    p.add_argument("--lufs", type=float, default=-22.0, help="integrated loudness of the loop")
    p.add_argument("--skip", type=float, default=0.3, help="ignore this much at both ends of the source")

    p = sub.add_parser("normalize", help="gain-only loudness: one file (--target) or a rules file (--rules)")
    p.add_argument("files", nargs="*", help="wav files (with --target)")
    p.add_argument("--target", type=float, help="integrated LUFS target for the given files")
    p.add_argument("--rules", help="rules json (see README) to normalise a whole tree")
    p.add_argument("--toy", action="append", default=[], help="only this toy id (repeatable, with --rules)")
    p.add_argument("--backup", help="back up originals here before overwriting (<backup>/<toy>/ with --rules)")
    p.add_argument("--report", help="write a before/after markdown table here (with --rules)")
    p.add_argument("--dry-run", action="store_true", help="measure and plan only, write nothing")

    p = sub.add_parser("measure", help="print LUFS / true peak / peak / RMS of wav files (json lines)")
    p.add_argument("files", nargs="+")
    p.add_argument("--loop", action="store_true", help="also run the loop join check")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "check":
            stats = client.check_server()
            print("ComfyUI ok, version", stats.get("system", {}).get("comfyui_version"))
            print("comfy-cli:", client.find_comfy())
            print("ffmpeg:", client.find_ffmpeg())
        elif a.cmd == "image":
            out = generate_image(a.prompt, a.out, a.seed, a.aspect, a.steps, a.megapixels, a.transparent)
            print(json.dumps({"ok": True, "out": out}))
        elif a.cmd == "edit":
            out = edit_image(a.image, a.prompt, a.out, a.seed, a.steps, a.width, a.height)
            print(json.dumps({"ok": True, "out": out}))
        elif a.cmd == "model":
            r = generate_model(a.prompt, a.out, a.seed, a.view, a.ref_out, a.ref_only, a.from_image,
                               a.image_seed, a.faces, a.texture)
            print(json.dumps({"ok": True, **r}))
        elif a.cmd == "sound":
            kw = dict(seconds=a.seconds, seed=a.seed, category=a.category, trim=not a.no_trim,
                      sample_rate=a.sample_rate)
            if a.variants:
                stem = os.path.splitext(a.out)[0]
                outs = generate_variants(a.prompt, os.path.dirname(stem) or ".", os.path.basename(stem),
                                         n=a.variants, **kw)
                good = not any(isinstance(o, tuple) for o in outs)
                print(json.dumps({"ok": good, "out": outs}))
                return 0 if good else 1
            out = generate_sound(a.prompt, a.out, raw_out=a.raw_out, **kw)
            print(json.dumps({"ok": True, "out": out}))
        elif a.cmd == "workflow":
            slots = {}
            for kv in a.slot:
                k, sep, v = kv.partition("=")
                if not sep:
                    raise client.ComfyError(f"--slot needs NODE.INPUT=VALUE, got {kv!r}")
                try:
                    slots[k] = json.loads(v)
                except json.JSONDecodeError:
                    slots[k] = v
            outs = run_any(a.file, a.out_dir, slots, a.ext or None, a.timeout, a.prefix)
            print(json.dumps({"ok": True, "out": outs}))
        elif a.cmd == "batch":
            _, _, failed = run_batch_file(a.file, a.names, a.force)
            return 1 if failed else 0
        elif a.cmd == "loop":
            print(json.dumps(postaudio.make_loop(a.src, a.out, a.seconds, a.crossfade, a.lufs, a.skip), indent=1))
        elif a.cmd == "measure":
            for f in a.files:
                m = postaudio.measure(f)
                if a.loop:
                    m["join"] = postaudio.verify_loop(f)
                print(json.dumps({"file": f, **m}))
        elif a.cmd == "normalize":
            if a.rules:
                rows = postaudio.normalize_rules(a.rules, backup=a.backup, report=a.report, dry_run=a.dry_run,
                                                 toys=a.toy)
                lim = sum(1 for r in rows if r.get("peak_limited"))
                print(f"{len(rows)} files, {lim} peak-limited" + (" (dry run)" if a.dry_run else ""))
            elif a.target is not None and a.files:
                for f in a.files:
                    if a.dry_run:
                        m = postaudio.measure(f)
                        print(json.dumps({"file": f, "before": m, "gain": postaudio.gain_for(m, a.target)[0]}))
                    else:
                        r = postaudio.normalize_file(f, a.target, backup_dir=a.backup)
                        print(json.dumps({"file": f, **r}))
            else:
                raise client.ComfyError("normalize needs --rules FILE, or --target LUFS with wav files")
    except client.ComfyError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    return 0
