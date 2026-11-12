#!/usr/bin/env bash
# Configure UnityYAMLMerge (Smart Merge) as git merge driver + mergetool in the LOCAL repo config.
# Idempotent. Never touches --global or --system config.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: setup_unityyamlmerge.sh [--project <unity-project-dir>] [--set-default-tool] [--fallback <spec|none>] [--dry-run]

Finds the editor version in <project>/ProjectSettings/ProjectVersion.txt, locates
  /Applications/Unity/Hub/Editor/<ver>/Unity.app/Contents/Helpers/UnityYAMLMerge
(override with UNITY_YAML_MERGE=<path> or UNITY_PATH=<.../Unity.app/Contents/MacOS/Unity>)
and writes to the repo's LOCAL git config:
  merge.unityyamlmerge.name / .driver / .recursive   (used by merge=unityyamlmerge in .gitattributes)
  mergetool.unityyamlmerge.cmd / .trustExitCode      (for `git mergetool --tool=unityyamlmerge`)
Options:
  --project DIR        Unity project root (default: current directory)
  --set-default-tool   also set merge.tool=unityyamlmerge (local)
  --fallback VALUE     UnityYAMLMerge --fallback value for the merge DRIVER (default: none, so an
                       unresolved conflict never opens a GUI tool such as FileMerge; git then
                       reports a normal conflict)
  --dry-run            print what would change, change nothing
Prints one line per key (set|unchanged) and ends with `RESULT: OK` or `RESULT: FAIL <reason>`.
EOF
}

PROJECT="$PWD"; SET_DEFAULT=0; DRY=0; FALLBACK="none"
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --project) PROJECT="${2:?--project needs a value}"; shift 2 ;;
    --set-default-tool) SET_DEFAULT=1; shift ;;
    --fallback) FALLBACK="${2:?--fallback needs a value}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; echo "RESULT: FAIL bad-args"; exit 2 ;;
  esac
done

fail() { echo "ERROR: $*" >&2; echo "RESULT: FAIL $1"; exit 1; }

[ -d "$PROJECT" ] || fail "project-missing: $PROJECT"
PROJECT="$(cd "$PROJECT" && pwd)"
REPO="$(git -C "$PROJECT" rev-parse --show-toplevel 2>/dev/null)" || fail "not-a-git-repo: $PROJECT"

# 1. Locate UnityYAMLMerge
YM="${UNITY_YAML_MERGE:-}"
if [ -z "$YM" ] && [ -n "${UNITY_PATH:-}" ]; then
  YM="$(cd "$(dirname "$UNITY_PATH")/.." && pwd)/Helpers/UnityYAMLMerge"   # .../Contents/Helpers
fi
if [ -z "$YM" ]; then
  PV="$PROJECT/ProjectSettings/ProjectVersion.txt"
  [ -f "$PV" ] || fail "no-ProjectVersion.txt: $PV (pass --project or UNITY_YAML_MERGE)"
  VER="$(sed -n 's/^m_EditorVersion: *//p' "$PV" | tr -d '\r' | head -n1)"
  [ -n "$VER" ] || fail "cannot-parse-version: $PV"
  YM="/Applications/Unity/Hub/Editor/$VER/Unity.app/Contents/Helpers/UnityYAMLMerge"
  echo "editor version: $VER"
fi
[ -x "$YM" ] || fail "UnityYAMLMerge-not-found: $YM (Unity 6 macOS path is Contents/Helpers, not Contents/Tools)"
echo "UnityYAMLMerge: $YM"
case "$YM" in *"'"*) fail "path-contains-single-quote: $YM" ;; esac

# 2. Desired LOCAL config (args verified against `UnityYAMLMerge` usage text, 6000.3.21f1):
#    merge [-h headless] [-p premerge] [--force any extension] [--fallback spec|none] <base> <left=theirs> <right=mine> <dest>
#    git driver placeholders: %O base, %B theirs, %A ours (and result file).
#    --force is required because git hands the driver temp files without .prefab/.unity extensions.
DRIVER="'$YM' merge -h -p --force --fallback $FALLBACK %O %B %A %A"
TOOLCMD="'$YM' merge -p \"\$BASE\" \"\$REMOTE\" \"\$LOCAL\" \"\$MERGED\""

set_key() { # key value
  local key="$1" val="$2" cur
  cur="$(git -C "$REPO" config --local --get "$key" 2>/dev/null || true)"
  if [ "$cur" = "$val" ]; then
    echo "unchanged $key"
  elif [ $DRY -eq 1 ]; then
    echo "would-set $key = $val"
  else
    git -C "$REPO" config --local "$key" "$val"
    echo "set       $key = $val"
  fi
}

set_key merge.unityyamlmerge.name "Unity SmartMerge (UnityYAMLMerge)"
set_key merge.unityyamlmerge.driver "$DRIVER"
set_key merge.unityyamlmerge.recursive "binary"
set_key mergetool.unityyamlmerge.cmd "$TOOLCMD"
set_key mergetool.unityyamlmerge.trustExitCode "false"
set_key mergetool.keepBackup "false"
[ $SET_DEFAULT -eq 1 ] && set_key merge.tool "unityyamlmerge"

# 3. Warn (do not fail) when .gitattributes does not route Unity YAML to the driver
ATTR="$(git -C "$REPO" check-attr merge -- probe.prefab 2>/dev/null | sed 's/.*: merge: //')"
if [ "$ATTR" != "unityyamlmerge" ]; then
  echo "WARN: .gitattributes does not set merge=unityyamlmerge for *.prefab (got '$ATTR'); copy templates/Unity6.gitattributes"
fi
echo "repo: $REPO (config: $REPO/.git/config or worktree equivalent)"
echo "RESULT: OK"
