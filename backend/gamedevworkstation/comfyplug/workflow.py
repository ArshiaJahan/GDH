"""Any ComfyUI workflow: set slots, run it, keep every output (images, video, audio, 3D).

This is how ComfyPlug runs work it has no dedicated command for, video included: save the workflow from ComfyUI
(the same format the bundled templates use), then pass the node inputs to change as slots ("<node id>.<input>").
"""
import os
import shutil

from . import client

MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mkv",
              ".wav", ".flac", ".mp3", ".ogg", ".opus", ".glb", ".gltf", ".obj", ".fbx")


def run_any(workflow, out_dir, slots=None, exts=MEDIA_EXTS, timeout=1800, prefix=None):
    """Run `workflow` (a bundled template name or a path) with `slots`; copy its outputs into out_dir.

    prefix: name the copies <prefix>_<n><ext> (default: keep ComfyUI's file names). Returns the copied paths.
    """
    exts = tuple(e if e.startswith(".") else "." + e for e in (exts or MEDIA_EXTS))
    work, pid, files = client.run_workflow(workflow, dict(slots or {}), exts, timeout=timeout)
    try:
        os.makedirs(out_dir, exist_ok=True)
        outs = []
        for i, f in enumerate(sorted(files), 1):
            name = f"{prefix}_{i}{os.path.splitext(f)[1]}" if prefix else os.path.basename(f)
            dst = os.path.join(out_dir, name)
            shutil.copy(f, dst)
            outs.append(dst)
    finally:
        client.cleanup(work)
    return outs
