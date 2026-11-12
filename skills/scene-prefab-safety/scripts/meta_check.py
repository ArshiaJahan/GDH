#!/usr/bin/env python3
"""meta_check.py - GUID/.meta integrity check for a Unity project (python3 stdlib only).

Checks, under Assets/ and local (embedded) packages in Packages/:
  * missing .meta   : a file/folder Unity imports but that has no <name>.meta
  * orphan .meta    : a <name>.meta whose file/folder is gone
  * bad .meta       : .meta without a valid 32-hex 'guid:' line
  * duplicate GUIDs : two .meta files with the same guid
  * --refs          : GUIDs referenced from text-serialized YAML assets
                      (.unity .prefab .asset .mat .controller ...) that exist nowhere
                      (project metas + Library/PackageCache metas + built-in GUIDs)

Usage:
  meta_check.py [PROJECT_ROOT] [--refs] [--strict] [--json] [--max N]
Exit codes: 0 = clean, 1 = problems found, 2 = usage/setup error.
Last line is machine-readable:  RESULT: OK ...  |  RESULT: FAIL <counts>
"""
import argparse
import json
import os
import re
import sys

GUID_LINE = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.M)
GUID_REF = re.compile(r"guid:\s*([0-9a-fA-F]{32})")
# Unity built-in resource GUIDs (no .meta anywhere in the project):
#   0000000000000000e000000000000000 = Built-in Extra Resources
#   0000000000000000f000000000000000 = Built-in Default Resources (unity default resources)
#   0000000000000000d000000000000000 = Built-in editor resources
#   00000000000000000000000000000000 = null reference
BUILTIN_GUIDS = {
    "0000000000000000e000000000000000",
    "0000000000000000f000000000000000",
    "0000000000000000d000000000000000",
    "00000000000000000000000000000000",
}
YAML_EXTS = {
    ".unity", ".prefab", ".asset", ".mat", ".controller", ".overridecontroller", ".anim",
    ".mask", ".playable", ".mixer", ".physicsmaterial2d", ".physicmaterial", ".physicsmaterial",
    ".spriteatlas", ".spriteatlasv2", ".preset", ".lighting", ".guiskin", ".fontsettings",
    ".terrainlayer", ".signal", ".brush", ".flare", ".rendertexture", ".cubemap",
}


def unity_ignores(name):
    """Names the AssetDatabase never imports (so they need no .meta)."""
    low = name.lower()
    return (
        name.startswith(".")
        or name.endswith("~")
        or low == "cvs"
        or low.endswith(".tmp")
    )


def local_package_roots(project):
    """Embedded packages = real folders directly under Packages/ that hold a package.json."""
    pk = os.path.join(project, "Packages")
    roots = []
    if os.path.isdir(pk):
        for n in sorted(os.listdir(pk)):
            p = os.path.join(pk, n)
            if os.path.isdir(p) and not unity_ignores(n) and os.path.isfile(os.path.join(p, "package.json")):
                roots.append(p)
    # file: dependencies outside Packages/ (manifest "file:../x")
    man = os.path.join(pk, "manifest.json")
    try:
        with open(man, encoding="utf-8") as f:
            deps = json.load(f).get("dependencies", {})
        for v in deps.values():
            if isinstance(v, str) and v.startswith("file:") and not v.endswith(".tgz"):
                p = os.path.normpath(os.path.join(pk, v[5:]))
                if os.path.isdir(p) and p not in roots:
                    roots.append(p)
    except (OSError, ValueError):
        pass
    return roots


def read_guid(meta_path):
    try:
        with open(meta_path, encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except OSError:
        return None
    m = GUID_LINE.search(head)
    return m.group(1).lower() if m else None


def scan_root(root, is_package, problems, guids, yaml_files):
    """Walk one root. For Assets/ the root folder itself has no .meta; package roots don't either."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not unity_ignores(d)]
        entries = set(filenames) | set(dirnames)
        for name in filenames:
            path = os.path.join(dirpath, name)
            if name.endswith(".meta"):
                target = name[:-5]
                if unity_ignores(target):
                    continue
                if target not in entries:
                    problems["orphan_meta"].append(path)
                    continue
                g = read_guid(path)
                if g is None:
                    problems["bad_meta"].append(path)
                else:
                    guids.setdefault(g, []).append(path)
                continue
            if unity_ignores(name):
                continue
            if name + ".meta" not in entries:
                problems["missing_meta"].append(path)
            ext = os.path.splitext(name)[1].lower()
            if ext in YAML_EXTS:
                yaml_files.append(path)
        for d in dirnames:
            if d + ".meta" not in entries:
                problems["missing_meta"].append(os.path.join(dirpath, d) + "/")


def package_cache_guids(project):
    """GUIDs of registry/builtin packages resolved into Library/PackageCache (if the project was opened)."""
    cache = os.path.join(project, "Library", "PackageCache")
    found = set()
    if not os.path.isdir(cache):
        return found, False
    for dirpath, _dirnames, filenames in os.walk(cache):
        for name in filenames:
            if name.endswith(".meta"):
                g = read_guid(os.path.join(dirpath, name))
                if g:
                    found.add(g)
    return found, True


def scan_refs(yaml_files, known, problems):
    for path in yaml_files:
        try:
            with open(path, "rb") as f:
                head = f.read(5)
                if head != b"%YAML":
                    continue  # binary-serialized asset; cannot inspect
                text = (head + f.read()).decode("utf-8", errors="replace")
        except OSError:
            continue
        seen = set()
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in GUID_REF.finditer(line):
                g = m.group(1).lower()
                if g in BUILTIN_GUIDS or g in known or g in seen:
                    continue
                seen.add(g)
                problems["missing_ref"].append("%s:%d guid %s" % (path, lineno, g))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", default=".", help="Unity project root (default: cwd)")
    ap.add_argument("--refs", action="store_true", help="also check GUID references inside YAML assets")
    ap.add_argument("--strict", action="store_true",
                    help="with --refs and no Library/PackageCache: treat unresolved refs as errors (default: warnings)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--max", type=int, default=50, help="max lines printed per category (default 50)")
    a = ap.parse_args(argv)

    project = os.path.abspath(a.project)
    assets = os.path.join(project, "Assets")
    if not os.path.isdir(assets):
        print("RESULT: FAIL no Assets/ folder under %s" % project)
        return 2

    problems = {k: [] for k in ("missing_meta", "orphan_meta", "bad_meta", "duplicate_guid", "missing_ref")}
    guids, yaml_files = {}, []
    roots = [(assets, False)] + [(p, True) for p in local_package_roots(project)]
    for root, is_pkg in roots:
        scan_root(root, is_pkg, problems, guids, yaml_files)

    for g, paths in sorted(guids.items()):
        if len(paths) > 1:
            problems["duplicate_guid"].append("%s: %s" % (g, " | ".join(sorted(paths))))

    warnings = []
    if a.refs:
        known = set(guids)
        cache, has_cache = package_cache_guids(project)
        known |= cache
        scan_refs(yaml_files, known, problems)
        if not has_cache and problems["missing_ref"] and not a.strict:
            warnings.append("Library/PackageCache missing: %d unresolved refs may point into packages; "
                            "open/import the project once, or pass --strict" % len(problems["missing_ref"]))
            warnings.extend("unresolved " + r for r in problems["missing_ref"])
            problems["missing_ref"] = []

    rel = lambda s: s.replace(project + os.sep, "")
    counts = {k: len(v) for k, v in problems.items()}
    total = sum(counts.values())
    if a.json:
        print(json.dumps({"project": project, "roots": [rel(r) for r, _ in roots], "counts": counts,
                          "problems": {k: [rel(x) for x in v] for k, v in problems.items()},
                          "warnings": [rel(w) for w in warnings], "guids": len(guids),
                          "yaml_files": len(yaml_files)}, indent=2))
    else:
        print("meta_check: project=%s roots=%d metas=%d yaml_files=%d refs=%s"
              % (project, len(roots), sum(len(v) for v in guids.values()), len(yaml_files), a.refs))
        for k, v in problems.items():
            if not v:
                continue
            print("\n[%s] %d" % (k, len(v)))
            for x in v[: a.max]:
                print("  " + rel(x))
            if len(v) > a.max:
                print("  ... %d more" % (len(v) - a.max))
        for w in warnings[: a.max]:
            print("WARN " + rel(w))
    summary = " ".join("%s=%d" % (k, c) for k, c in counts.items())
    if a.json:
        return 1 if total else 0
    if total:
        print("RESULT: FAIL " + summary)
        return 1
    print("RESULT: OK " + summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
