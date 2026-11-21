"""Images with the Qwen Image 2.1 text-to-image template.

Gotchas kept from the playbook: the prompt goes in slot 459/452 (comfy-cli 1.25 drops it on the switch/preview
chain, so the workflow is the "direct" copy); the template's prompt re-writer is OFF (459.switch=false) so the
prompt is used as written. No brand, franchise, film or show names in prompts.
"""
import shutil

from . import client

TEMPLATE = "qwen21_t2i_direct.json"

# Qwen Image 2.1 returns an alpha channel when asked like this.
TRANSPARENT_WRAP = ("This is an RGBA format image with transparency. {p} Isolated single object, centered, nothing "
                    "else in the image. The image has an alpha channel and a transparent background.")


def generate_image(prompt, out, seed=11, aspect="1:1 (Square)", steps=25, megapixels=1.0, transparent=False):
    """Make one PNG at `out`. aspect is the template's label, e.g. "9:16 (Portrait Widescreen)". Returns out."""
    if transparent:
        prompt = TRANSPARENT_WRAP.format(p=prompt)
    work, pid, files = client.run_workflow(TEMPLATE, {
        "459/452.prompt": prompt,
        "459.seed": int(seed),
        "459.steps": int(steps),
        "459.switch": False,
        "13.aspect_ratio": aspect,
        "13.megapixels": float(megapixels),
        "461.filename_prefix": "comfyplug",
    }, [".png"])
    try:
        client.ensure_parent(out)
        shutil.copy(files[0], out)
    finally:
        client.cleanup(work)
    return out
