#!/usr/bin/env python3
"""vcs_check.py - VCS hygiene check for a Unity 6 project in git (python3 stdlib only).

Usage: vcs_check.py [--project DIR] [--max-blob-kb N] [--strict] [--no-history] [--json]

Checks (each prints PASS / WARN / FAIL):
  ignore      .gitignore ignores Library/ Temp/ Obj/ Logs/ UserSettings/ Build(s)/ MemoryCaptures/ *.csproj *.sln
  tracked     nothing under those folders (or *.csproj/*.sln) is tracked, and no tracked file matches .gitignore
  attributes  .gitattributes routes Unity YAML (.unity .prefab .asset .meta .mat .anim .controller) to merge=unityyamlmerge
  lfs-rules   .gitattributes sends binary art/audio/video/fonts/models to LFS (filter=lfs)
  lfs-install git-lfs is installed and the repo has the lfs filter configured
  driver      merge.unityyamlmerge.driver is configured (LOCAL config preferred) and its binary exists
  blobs       no blob in the index is larger than --max-blob-kb (default 1024) and every
              filter=lfs file in the index is an LFS pointer (not a raw binary)
  untracked   no untracked, non-ignored file larger than --max-blob-kb is waiting to be added outside LFS
  history     no blob > --max-blob-kb outside LFS anywhere in history (WARN only; fixing it means rewriting
              history with `git lfs migrate import`, which needs the user's approval). Skip with --no-history
  meta        every tracked file under Assets/ has a tracked .meta (and vice versa)       [WARN only]
  editor      ProjectSettings/EditorSettings.asset m_SerializationMode: 2 (Force Text) and
              VersionControlSettings.asset m_Mode: Visible Meta Files
Exit: 0 = no FAIL (WARN allowed unless --strict), 1 = at least one FAIL, 2 = usage/setup error.
Last line: RESULT: OK | RESULT: FAIL <n> check(s): <names>
"""
import argparse
import json
import os
import re
import subprocess
import sys

IGNORE_DIRS = ["Library", "Temp", "Obj", "Logs", "UserSettings", "Build", "Builds", "MemoryCaptures"]
IGNORE_FILES = ["Game.csproj", "Game.sln"]
YAML_EXTS = ["unity", "prefab", "asset", "meta", "mat", "anim", "controller", "physicsMaterial2D", "spriteatlasv2"]
LFS_EXTS = ["png", "psd", "aseprite", "wav", "ogg", "mp3", "mp4", "ttf", "otf", "fbx"]
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"

results = []


def report(status, check, detail):
    results.append({"status": status, "check": check, "detail": detail})


def git(repo, *args, input_bytes=None, check=True):
    p = subprocess.run(["git", "-C", repo, *args], input=input_bytes,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.decode(errors="replace").strip()))
    return p


def rel(prefix, path):
    return (prefix + path) if prefix else path


def check_ignore(repo, prefix):
    paths = [rel(prefix, d + "/probe.file") for d in IGNORE_DIRS] + [rel(prefix, f) for f in IGNORE_FILES]
    p = git(repo, "check-ignore", "--no-index", "--stdin", "-z",
            input_bytes=b"\0".join(x.encode() for x in paths) + b"\0", check=False)
    ignored = set(x.decode() for x in p.stdout.split(b"\0") if x)
    missing = [x for x in paths if x not in ignored]
    if missing:
        report("FAIL", "ignore", "not ignored: " + ", ".join(m.replace("/probe.file", "/") for m in missing))
    else:
        report("PASS", "ignore", "Library/ Temp/ Obj/ Logs/ UserSettings/ Build(s)/ MemoryCaptures/ *.csproj *.sln ignored")


def tracked_files(repo):
    out = git(repo, "ls-files", "-z").stdout
    return [x.decode("utf-8", "surrogateescape") for x in out.split(b"\0") if x]


def check_tracked(repo, files, prefix):
    out = git(repo, "ls-files", "-z", "-ci", "--exclude-standard").stdout
    ignored = [x.decode("utf-8", "surrogateescape") for x in out.split(b"\0") if x]
    if ignored:
        report("FAIL", "tracked", "%d tracked file(s) match .gitignore, e.g. %s (fix: git rm -r --cached <path>, commit)"
               % (len(ignored), ", ".join(ignored[:5])))
    bad = []
    lowered = [d.lower() + "/" for d in IGNORE_DIRS]
    for f in files:
        if prefix and not f.startswith(prefix):
            continue
        local = f[len(prefix):] if prefix else f
        if any(local.lower().startswith(d) for d in lowered) or local.endswith((".csproj", ".sln")):
            bad.append(f)
    if bad:
        report("FAIL", "tracked", "%d generated file(s) tracked, e.g. %s (fix: git rm -r --cached <dir>)"
               % (len(bad), ", ".join(bad[:5])))
    elif not ignored:
        report("PASS", "tracked", "no Library/Temp/Obj/Logs/UserSettings/Build/*.csproj/*.sln or other ignored files tracked")


def check_attr(repo, attr, names):
    p = git(repo, "check-attr", "-z", attr, "--", *names)
    parts = p.stdout.split(b"\0")
    out = {}
    for i in range(0, len(parts) - 2, 3):
        out[parts[i].decode()] = parts[i + 2].decode()
    return out


def check_attributes(repo, prefix):
    names = [rel(prefix, "Assets/probe." + e) for e in YAML_EXTS]
    got = check_attr(repo, "merge", names)
    bad = [n.rsplit(".", 1)[1] for n in names if got.get(n) != "unityyamlmerge"]
    if bad:
        report("FAIL", "attributes", "merge=unityyamlmerge missing for: ." + " .".join(bad))
    else:
        report("PASS", "attributes", "Unity YAML routed to merge=unityyamlmerge")
    eol = check_attr(repo, "eol", [rel(prefix, "Assets/probe.prefab")])
    if list(eol.values()) != ["lf"]:
        report("WARN", "attributes", "*.prefab has no eol=lf (got %s)" % list(eol.values()))


def check_lfs_rules(repo, prefix):
    names = [rel(prefix, "Assets/probe." + e) for e in LFS_EXTS]
    got = check_attr(repo, "filter", names)
    bad = [n.rsplit(".", 1)[1] for n in names if got.get(n) != "lfs"]
    if bad:
        status = "FAIL" if len(bad) > len(LFS_EXTS) // 2 else "WARN"
        report(status, "lfs-rules", "no filter=lfs for: ." + " .".join(bad))
    else:
        report("PASS", "lfs-rules", "binary art/audio/video/fonts/models -> LFS")
    return got


def check_lfs_install(repo):
    p = subprocess.run(["git", "lfs", "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        report("FAIL", "lfs-install", "git-lfs not installed (brew install git-lfs)")
        return
    clean = git(repo, "config", "--get", "filter.lfs.clean", check=False).stdout.decode().strip()
    if not clean:
        report("FAIL", "lfs-install", "filter.lfs.* not configured (run: git lfs install --local)")
    else:
        report("PASS", "lfs-install", p.stdout.decode().split()[0] + ", filter.lfs configured")


def check_driver(repo):
    local = git(repo, "config", "--local", "--get", "merge.unityyamlmerge.driver", check=False).stdout.decode().strip()
    anyscope = git(repo, "config", "--get", "merge.unityyamlmerge.driver", check=False).stdout.decode().strip()
    drv = local or anyscope
    if not drv:
        report("FAIL", "driver", "merge.unityyamlmerge.driver not configured (run scripts/setup_unityyamlmerge.sh)")
        return
    m = re.match(r"\s*'([^']+)'|\s*\"([^\"]+)\"|\s*(\S+)", drv)
    binpath = next(g for g in m.groups() if g) if m else ""
    if not os.path.isfile(binpath):
        report("FAIL", "driver", "driver binary missing: %s (editor upgraded? re-run setup)" % binpath)
        return
    if "--force" not in drv:
        report("WARN", "driver", "driver lacks --force: git temp files have no .prefab extension, UnityYAMLMerge may fall back")
    scope = "local" if local else "global/system"
    if local:
        report("PASS", "driver", "local driver -> %s" % binpath)
    else:
        report("WARN", "driver", "driver only in %s config; harness rule is LOCAL repo config" % scope)


def check_blobs(repo, prefix, files, max_kb, lfs_attr_cache):
    out = git(repo, "ls-files", "-s", "-z").stdout
    entries = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, path = rec.split(b"\t", 1)
        mode, sha, _stage = meta.split()
        if mode == b"160000":  # submodule
            continue
        entries.append((sha.decode(), path.decode("utf-8", "surrogateescape")))
    if not entries:
        report("PASS", "blobs", "index empty")
        return
    batch = git(repo, "cat-file", "--batch-check=%(objectname) %(objectsize)",
                input_bytes="\n".join(s for s, _ in entries).encode() + b"\n").stdout.decode().splitlines()
    sizes = {}
    for line in batch:
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])
    limit = max_kb * 1024
    big = [(p, sizes.get(s, 0)) for s, p in entries if sizes.get(s, 0) > limit]
    lfs_paths = [p for _, p in entries]
    filt = {}
    for i in range(0, len(lfs_paths), 500):
        filt.update(check_attr(repo, "filter", lfs_paths[i:i + 500]))
    not_pointer = []
    for sha, path in entries:
        if filt.get(path) == "lfs" and sizes.get(sha, 0) > 1024:
            head = git(repo, "cat-file", "blob", sha).stdout[:len(LFS_POINTER_PREFIX)]
            if head != LFS_POINTER_PREFIX:
                not_pointer.append(path)
    if big:
        big.sort(key=lambda x: -x[1])
        report("FAIL", "blobs", "%d blob(s) > %d KB outside LFS: %s" % (
            len(big), max_kb, ", ".join("%s (%d KB)" % (p, s // 1024) for p, s in big[:5])))
    if not_pointer:
        report("FAIL", "blobs", "%d LFS-pattern file(s) committed as raw blobs: %s (fix: git add --renormalize .; history needs git lfs migrate)"
               % (len(not_pointer), ", ".join(not_pointer[:5])))
    if not big and not not_pointer:
        report("PASS", "blobs", "%d indexed file(s); none > %d KB outside LFS" % (len(entries), max_kb))


def check_untracked(repo, max_kb):
    out = git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    paths = [x.decode("utf-8", "surrogateescape") for x in out.split(b"\0") if x]
    big = []
    for p in paths:
        try:
            sz = os.path.getsize(os.path.join(repo, p))
        except OSError:
            continue
        if sz > max_kb * 1024:
            big.append((p, sz))
    if big:
        attrs = check_attr(repo, "filter", [p for p, _ in big])
        outside = [(p, s) for p, s in big if attrs.get(p) != "lfs"]
        if outside:
            report("WARN", "untracked", "%d large untracked file(s) would be committed outside LFS: %s" % (
                len(outside), ", ".join("%s (%d KB)" % (p, s // 1024) for p, s in outside[:5])))
            return
    report("PASS", "untracked", "no large untracked files outside LFS")


def check_history(repo, max_kb):
    p = subprocess.run(["git", "-C", repo, "rev-list", "--objects", "--all"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        report("PASS", "history", "no commits yet")
        return
    objs = {}
    for line in p.stdout.decode("utf-8", "surrogateescape").splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1]:
            objs.setdefault(parts[0], parts[1])
    if not objs:
        report("PASS", "history", "no blobs in history")
        return
    batch = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                input_bytes="\n".join(objs).encode() + b"\n").stdout.decode().splitlines()
    big = []
    for line in batch:
        sha, typ, size = (line.split() + ["", "", ""])[:3]
        if typ == "blob" and size.isdigit() and int(size) > max_kb * 1024:
            big.append((objs[sha], int(size)))
    if big:
        big.sort(key=lambda x: -x[1])
        report("WARN", "history", "%d blob(s) > %d KB outside LFS in history, e.g. %s. Rewriting history "
               "(git lfs migrate import --include=... --everything) needs the user's approval and a force-push"
               % (len(big), max_kb, ", ".join("%s (%d KB)" % (p, s // 1024) for p, s in big[:3])))
    else:
        report("PASS", "history", "%d object(s) in history; none > %d KB outside LFS" % (len(objs), max_kb))


def check_meta(files, prefix):
    assets = rel(prefix, "Assets/")
    tracked = set(f for f in files if f.startswith(assets))
    if not tracked:
        report("WARN", "meta", "no tracked files under %s" % assets)
        return
    dirs = set()
    for f in tracked:
        parts = f[len(assets):].split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add(assets + "/".join(parts[:i]))
    no_meta, orphan = [], []
    for f in tracked:
        if f.endswith(".meta"):
            target = f[:-5]
            if target not in tracked and target not in dirs:
                orphan.append(f)
        elif f + ".meta" not in tracked:
            no_meta.append(f)
    for d in dirs:
        if d + ".meta" not in tracked:
            no_meta.append(d + "/")
    if no_meta or orphan:
        parts = []
        if no_meta:
            parts.append("%d asset(s) without tracked .meta (e.g. %s)" % (len(no_meta), ", ".join(sorted(no_meta)[:3])))
        if orphan:
            parts.append("%d orphan .meta (e.g. %s)" % (len(orphan), ", ".join(sorted(orphan)[:3])))
        report("WARN", "meta", "; ".join(parts) + " - open the project in Unity once, then commit the .meta files")
    else:
        report("PASS", "meta", "%d tracked Assets/ files all paired with .meta" % len(tracked))


def check_editor(project):
    es = os.path.join(project, "ProjectSettings", "EditorSettings.asset")
    vc = os.path.join(project, "ProjectSettings", "VersionControlSettings.asset")
    problems = []
    try:
        txt = open(es, encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*m_SerializationMode:\s*(\d+)", txt, re.M)
        if not m:
            problems.append("m_SerializationMode not found in EditorSettings.asset (binary-serialized?)")
        elif m.group(1) != "2":
            problems.append("m_SerializationMode=%s (want 2 = Force Text)" % m.group(1))
    except OSError:
        problems.append("missing %s" % es)
    try:
        txt = open(vc, encoding="utf-8", errors="replace").read()
        m = re.search(r"^\s*m_Mode:\s*(.+?)\s*$", txt, re.M)
        if not m or m.group(1) != "Visible Meta Files":
            problems.append("VersionControlSettings m_Mode=%s (want Visible Meta Files)" % (m.group(1) if m else "?"))
    except OSError:
        report("WARN", "editor", "no VersionControlSettings.asset (defaults to Visible Meta Files in Unity 6)")
    if problems:
        report("FAIL", "editor", "; ".join(problems))
    else:
        report("PASS", "editor", "Force Text (m_SerializationMode: 2) + Visible Meta Files")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="Unity project root (default: cwd)")
    ap.add_argument("--max-blob-kb", type=int, default=1024, help="max size of a non-LFS blob (default 1024)")
    ap.add_argument("--strict", action="store_true", help="treat WARN as FAIL")
    ap.add_argument("--no-history", action="store_true", help="skip the (slower) history scan")
    ap.add_argument("--json", action="store_true", help="print JSON instead of lines")
    a = ap.parse_args()

    project = os.path.realpath(a.project)
    if not os.path.isdir(os.path.join(project, "ProjectSettings")):
        print("ERROR: %s has no ProjectSettings/ (not a Unity project root)" % project, file=sys.stderr)
        print("RESULT: FAIL setup")
        return 2
    p = subprocess.run(["git", "-C", project, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        print("ERROR: %s is not inside a git repository" % project, file=sys.stderr)
        print("RESULT: FAIL setup")
        return 2
    repo = os.path.realpath(p.stdout.decode().strip())
    prefix = os.path.relpath(project, repo).replace(os.sep, "/")
    prefix = "" if prefix == "." else prefix + "/"

    try:
        files = tracked_files(repo)
        check_ignore(repo, prefix)
        check_tracked(repo, files, prefix)
        check_attributes(repo, prefix)
        lfs = check_lfs_rules(repo, prefix)
        check_lfs_install(repo)
        check_driver(repo)
        check_blobs(repo, prefix, files, a.max_blob_kb, lfs)
        check_untracked(repo, a.max_blob_kb)
        if not a.no_history:
            check_history(repo, a.max_blob_kb)
        check_meta(files, prefix)
        check_editor(project)
    except RuntimeError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        print("RESULT: FAIL setup")
        return 2

    failing = [r for r in results if r["status"] == "FAIL" or (a.strict and r["status"] == "WARN")]
    if a.json:
        print(json.dumps({"repo": repo, "project": project, "results": results, "ok": not failing}, indent=2))
    else:
        print("repo=%s project_prefix=%s" % (repo, prefix or "."))
        for r in results:
            print("%-4s %-11s %s" % (r["status"], r["check"], r["detail"]))
    if failing:
        names = sorted(set(r["check"] for r in failing))
        print("RESULT: FAIL %d check(s): %s" % (len(names), ",".join(names)))
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
