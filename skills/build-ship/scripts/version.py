#!/usr/bin/env python3
"""Read or bump the release version in ProjectSettings/ProjectSettings.asset (text YAML) without opening Unity.

usage: version.py show [--project DIR]
       version.py next major|minor|patch [--project DIR]        print the next SemVer (no write)
       version.py set X.Y.Z [--build N] [--project DIR]          write version + build numbers
Fields (6000.3 ProjectSettings.asset):
  bundleVersion: X.Y.Z                 PlayerSettings.bundleVersion (= Application.version, all platforms)
  buildNumber: {Standalone, iPhone, tvOS, VisionOS}  PlayerSettings.macOS.buildNumber writes Standalone,
                                       PlayerSettings.iOS.buildNumber writes iPhone
  AndroidBundleVersionCode: N          PlayerSettings.Android.bundleVersionCode
`set` without --build uses max(current build numbers)+1. Only edit while the project is closed in Unity
(an open editor would overwrite the file); with the editor open use ShipVersion.Apply via execute_code.
Python 3 stdlib only. Exit 0 ok, 1 error.
"""
import os
import re
import sys

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$")


def find_project(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(d, "ProjectSettings", "ProjectSettings.asset")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def read(path):
    text = open(path, encoding="utf-8").read()
    ver = re.search(r"^  bundleVersion: *(.*)$", text, re.M)
    android = re.search(r"^  AndroidBundleVersionCode: *(\d+)", text, re.M)
    block = re.search(r"^  buildNumber:\n((?:    \S+: *.*\n)*)", text, re.M)
    nums = dict(re.findall(r"^    (\S+): *(.*)$", block.group(1), re.M)) if block else {}
    return text, (ver.group(1).strip() if ver else ""), (int(android.group(1)) if android else 0), nums


def to_int(s):
    try:
        return int(str(s).strip())
    except ValueError:
        return 0


def main(argv):
    args = list(argv[1:])
    project = None
    if "--project" in args:
        i = args.index("--project"); project = args[i + 1]; del args[i:i + 2]
    build = None
    if "--build" in args:
        i = args.index("--build"); build = int(args[i + 1]); del args[i:i + 2]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip()); return 0 if args else 1
    root = find_project(project or os.getcwd())
    if not root:
        print("error: no Unity project (ProjectSettings/ProjectSettings.asset) found", file=sys.stderr); return 1
    path = os.path.join(root, "ProjectSettings", "ProjectSettings.asset")
    text, ver, android, nums = read(path)
    cmd = args[0]

    if cmd == "show":
        print("version=%s macOS(Standalone)=%s iOS(iPhone)=%s android=%d"
              % (ver, nums.get("Standalone", "-"), nums.get("iPhone", "-"), android))
        return 0
    if cmd == "next":
        m = SEMVER.match(ver)
        major, minor, patch = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
        if not m:
            parts = [to_int(p) for p in re.split(r"[.\-]", ver)[:3]] + [0, 0, 0]
            major, minor, patch = parts[0], parts[1], parts[2]
        kind = args[1] if len(args) > 1 else "patch"
        if kind == "major": major, minor, patch = major + 1, 0, 0
        elif kind == "minor": minor, patch = minor + 1, 0
        elif kind == "patch": patch += 1
        else:
            print("error: next major|minor|patch", file=sys.stderr); return 1
        print("%d.%d.%d" % (major, minor, patch))
        return 0
    if cmd == "set":
        if len(args) < 2 or not SEMVER.match(args[1]):
            print("error: set needs a SemVer X.Y.Z", file=sys.stderr); return 1
        new = args[1]
        if build is None:
            build = max([android] + [to_int(v) for v in nums.values()]) + 1
        if not re.search(r"^  bundleVersion:", text, re.M) or not re.search(r"^  AndroidBundleVersionCode:", text, re.M):
            print("error: bundleVersion/AndroidBundleVersionCode not found in %s" % path, file=sys.stderr); return 1
        text = re.sub(r"^(  bundleVersion:).*$", r"\g<1> " + new, text, count=1, flags=re.M)
        text = re.sub(r"^(  AndroidBundleVersionCode:).*$", r"\g<1> %d" % build, text, count=1, flags=re.M)

        def fix_block(m):
            body = m.group(1)
            for key in ("Standalone", "iPhone"):
                if re.search(r"^    %s:" % key, body, re.M):
                    body = re.sub(r"^(    %s:).*$" % key, r"\g<1> %d" % build, body, flags=re.M)
                else:
                    body += "    %s: %d\n" % (key, build)
            return "  buildNumber:\n" + body
        if re.search(r"^  buildNumber:\n", text, re.M):
            text = re.sub(r"^  buildNumber:\n((?:    \S+: *.*\n)*)", fix_block, text, count=1, flags=re.M)
        else:
            print("error: buildNumber block not found in %s" % path, file=sys.stderr); return 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        _, ver, android, nums = read(path)
        print("version=%s macOS(Standalone)=%s iOS(iPhone)=%s android=%d"
              % (ver, nums.get("Standalone"), nums.get("iPhone"), android))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
