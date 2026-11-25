#!/usr/bin/env python3
"""Copy a ready-made C# kit into a Unity project instead of writing it again.

    scaffold.py list
    scaffold.py <kit> --out <root>/Assets/<Folder> --namespace <Ns> [--force] [--dry-run]

Kits are folders under ../templates. `GdwKit` in the templates (namespace and asmdef names) is
replaced by --namespace. Files that already exist are skipped unless --force. Prints one line per
file and `RESULT: OK kit=… written=N skipped=N`. Standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PLACEHOLDER = "GdwKit"
KIT_INFO = {
    "pooling": "PoolService (ObjectPool<T> per prefab, prewarm), PooledObject, IPoolable, ReleaseAfter",
    "enemies": "EnemyConfig SO, Health/IDamageable, EnemyBrain state machine, WaveConfig + WaveSpawner, EnemyRegistry"
               " (needs pooling)",
    "tuning": "ConfigAsset base SO (OnValidate, Changed event), GameTuning example, LiveTuning, ConfigLoader",
    "debug-kit": "DebugOverlay (FPS, ms, GC), DebugCommands console, DebugDraw gizmos, Editor DebugSceneBuilder",
}
REQUIRES = {"enemies": ["pooling"]}


def kits() -> list[str]:
    return sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir())


def scaffold(kit: str, out: Path, namespace: str, force: bool = False, dry_run: bool = False) -> tuple[int, int]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", namespace):
        raise ValueError(f"not a C# namespace: {namespace}")
    src = TEMPLATES / kit
    if not src.is_dir():
        raise KeyError(kit)
    written = skipped = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        rel = f.relative_to(src)
        dest = out / Path(str(rel).replace(PLACEHOLDER, namespace))
        if dest.exists() and not force:
            print(f"skip {dest} (exists)")
            skipped += 1
            continue
        print(f"{'would write' if dry_run else 'write'} {dest}")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f.read_text(encoding="utf-8").replace(PLACEHOLDER, namespace), encoding="utf-8")
        written += 1
    return written, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kit")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--namespace", default="Game")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.kit == "list":
        for k in kits():
            print(f"{k}: {KIT_INFO.get(k, '')}")
        return 0
    if a.kit not in kits():
        print(f"RESULT: FAIL unknown kit {a.kit}; kits: {', '.join(kits())}")
        return 2
    if not a.out:
        ap.error("--out is required")
    try:
        w, s = scaffold(a.kit, a.out, a.namespace, a.force, a.dry_run)
    except ValueError as e:
        print(f"RESULT: FAIL {e}")
        return 2
    need = REQUIRES.get(a.kit, [])
    print(f"RESULT: OK kit={a.kit} written={w} skipped={s}"
          + (f" (uses the {', '.join(need)} kit: scaffold it into the same namespace if it isn't there)" if need else ""))
    print("next: recompile and check the console (0 errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
