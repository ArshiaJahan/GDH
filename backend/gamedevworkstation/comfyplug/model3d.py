"""3D models: Qwen reference image -> TRELLIS.2 image-to-3D -> textured GLB.

Gotchas kept from the playbook: 316.value=true selects TRELLIS.2 (false = Pixal3D), 248.switch=true removes the
reference background, all four samplers share the seed, and the run saves several GLBs, of which we keep the
textured one. No brand, franchise, film or show names in prompts. Slow: 3 to 10 minutes per model.
"""
import json
import os
import shutil
import struct
import sys
import urllib.request
import uuid

from . import client
from .image import generate_image

TEMPLATE = "trellis2_i2m.json"
REF_PROMPT = ("A single {prompt}. One isolated object, centered, fully in frame with margin, {view}, even soft "
              "studio lighting, plain light grey seamless background, no shadow on the background, "
              "no text, no logos.")


def upload_image(image_path, name):
    """Upload a PNG to ComfyUI's input folder; returns the server-side name."""
    boundary = uuid.uuid4().hex
    unique = f"comfyplug3d_{name}.png"
    with open(image_path, "rb") as f:
        data = f.read()
    parts = [
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="image"; filename="' + unique.encode() + b'"',
        b"Content-Type: image/png", b"", data,
        f"--{boundary}".encode(), b'Content-Disposition: form-data; name="overwrite"', b"", b"true",
        f"--{boundary}".encode(), b'Content-Disposition: form-data; name="type"', b"", b"input",
        f"--{boundary}--".encode(),
    ]
    req = urllib.request.Request(f"{client.comfy_url()}/upload/image", data=b"\r\n".join(parts))
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
    except OSError as e:
        raise client.ComfyError(f"image upload failed: {e}")
    sub = result.get("subfolder", "")
    return f"{sub}/{result['name']}" if sub else result["name"]


def _glb_score(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        n = struct.unpack("<I", data[12:16])[0]
        j = json.loads(data[20:20 + n])
        attrs = j["meshes"][0]["primitives"][0]["attributes"]
        return (len(j.get("images", [])), int("TEXCOORD_0" in attrs), int("COLOR_0" in attrs))
    except Exception:
        return (-1, 0, 0)


def make_reference(prompt, ref_out, image_seed=1, view="three-quarter front view"):
    """Step 1 only: the reference image TRELLIS will start from. Look at it before running the 3D step."""
    return generate_image(REF_PROMPT.format(prompt=prompt, view=view), ref_out, seed=image_seed)


def generate_model(prompt, out_glb, seed=1, view="three-quarter front view", ref_out=None, ref_only=False,
                   from_image=None, image_seed=None, faces=12000, texture=1024):
    """Prompt -> GLB at out_glb. Returns a dict {"glb", "ref", "prompt_id"}.

    ref_out    where to keep the reference image (default <out_glb without .glb>_ref.png)
    ref_only   stop after the reference image (glb is None); review it, then rerun with from_image=<ref>
    from_image skip step 1 and use this PNG
    image_seed seed of the reference image (default: same as seed)
    """
    base = os.path.splitext(os.path.basename(out_glb))[0]
    if image_seed is None:
        image_seed = seed
    ref = None
    if from_image:
        image_path = from_image
    else:
        ref = ref_out or os.path.join(os.path.dirname(os.path.abspath(out_glb)), f"{base}_ref.png")
        image_path = make_reference(prompt, ref, image_seed, view)
    if ref_only:
        return {"glb": None, "ref": image_path, "prompt_id": None}

    server_image = upload_image(image_path, base)
    tex2 = max(int(texture) * 2, 1024)
    slots = {
        "122.image": server_image,
        "248.switch": True,
        "316.value": True,
        "12.seed": int(seed), "18.seed": int(seed), "3.seed": int(seed), "23.seed": int(seed),
        "186.target_face_count": int(faces),
        "147.texture_size": int(texture),
        "288.value": tex2,
        "322.filename_prefix": "3d/comfyplug_" + base,
    }
    work, pid, files = client.run_workflow(TEMPLATE, slots, [".glb", ".gltf", ".obj", ".fbx"], timeout=1800)
    try:
        files.sort(key=lambda p: (p.lower().endswith(".glb"), _glb_score(p)), reverse=True)
        print("downloaded: " + ", ".join(f"{os.path.basename(p)} {_glb_score(p)}" for p in files), file=sys.stderr)
        if not files[0].lower().endswith(".glb"):
            print(f"warning: falling back to {os.path.basename(files[0])} (not .glb)", file=sys.stderr)
        client.ensure_parent(out_glb)
        shutil.copy(files[0], out_glb)
    finally:
        client.cleanup(work)
    return {"glb": out_glb, "ref": ref or from_image, "prompt_id": pid}
