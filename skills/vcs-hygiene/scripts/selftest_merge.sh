#!/usr/bin/env bash
# Self-test: prove that merge=unityyamlmerge + setup_unityyamlmerge.sh really invoke UnityYAMLMerge.
# Builds a THROWAWAY repo (never touches your project or your global git config), makes two branches
# that edit adjacent lines of one Transform in a .prefab (plain git text merge = conflict;
# UnityYAMLMerge = clean merge), merges with GIT_TRACE, then checks a real conflict stays a conflict.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: selftest_merge.sh [--project <unity-project-dir> | --version <6000.x.yf1>] [--dir <scratch-dir>]
  --project  read the editor version from <dir>/ProjectSettings/ProjectVersion.txt (read-only)
  --version  editor version to use (default: newest in /Applications/Unity/Hub/Editor)
  --dir      scratch directory; must not exist or be empty (default: a new mktemp -d under ${TMPDIR:-/tmp}).
             Nothing is ever deleted: every run uses a fresh directory.
Env: UNITY_YAML_MERGE=<path> overrides the binary.
Prints the git trace lines that show the driver call and ends with `RESULT: OK` or `RESULT: FAIL <reason>`.
EOF
}

HERE="$(cd "$(dirname "$0")" && pwd)"
VER=""; PROJ=""; DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --project) PROJ="${2:?}"; shift 2 ;;
    --version) VER="${2:?}"; shift 2 ;;
    --dir) DIR="${2:?}"; shift 2 ;;
    *) usage >&2; echo "RESULT: FAIL bad-args"; exit 2 ;;
  esac
done
fail() { echo "RESULT: FAIL $*"; exit 1; }

if [ -n "$PROJ" ]; then
  VER="$(sed -n 's/^m_EditorVersion: *//p' "$PROJ/ProjectSettings/ProjectVersion.txt" | tr -d '\r' | head -n1)"
fi
if [ -z "$VER" ] && [ -z "${UNITY_YAML_MERGE:-}" ]; then
  VER="$(ls /Applications/Unity/Hub/Editor 2>/dev/null | sort -V | tail -n1)"
fi
[ -n "$VER" ] || [ -n "${UNITY_YAML_MERGE:-}" ] || fail "no-unity-version"

# Fresh scratch repo with an isolated git config (GIT_CONFIG_GLOBAL) so nothing global is read or written.
if [ -z "$DIR" ]; then
  DIR="$(mktemp -d "${TMPDIR:-/tmp}/unityyamlmerge-selftest.XXXXXX")"
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  fail "dir-not-empty $DIR (use a new --dir; this script never deletes)"
fi
mkdir -p "$DIR/repo/ProjectSettings" "$DIR/repo/Assets"
export GIT_CONFIG_GLOBAL="$DIR/gitconfig" GIT_CONFIG_NOSYSTEM=1
printf '[user]\n\tname = selftest\n\temail = selftest@example.invalid\n[init]\n\tdefaultBranch = main\n' > "$GIT_CONFIG_GLOBAL"
cd "$DIR/repo"
git init -q
printf 'm_EditorVersion: %s\n' "${VER:-0.0.0}" > ProjectSettings/ProjectVersion.txt
printf '*.prefab merge=unityyamlmerge eol=lf\n*.meta merge=unityyamlmerge eol=lf\n' > .gitattributes

write_prefab() { # posX scaleX name
cat > Assets/Enemy.prefab <<EOF
%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &1000000000000000001
GameObject:
  m_ObjectHideFlags: 0
  serializedVersion: 6
  m_Component:
  - component: {fileID: 4000000000000000002}
  - component: {fileID: 212000000000000003}
  m_Layer: 0
  m_Name: $3
  m_TagString: Untagged
  m_IsActive: 1
--- !u!4 &4000000000000000002
Transform:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_GameObject: {fileID: 1000000000000000001}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: $1, y: 0, z: 0}
  m_LocalScale: {x: $2, y: 1, z: 1}
  m_ConstrainProportionsScale: 0
  m_Children: []
  m_Father: {fileID: 0}
--- !u!212 &212000000000000003
SpriteRenderer:
  m_ObjectHideFlags: 0
  m_GameObject: {fileID: 1000000000000000001}
  m_Enabled: 1
  m_SortingOrder: 0
  m_Color: {r: 1, g: 1, b: 1, a: 1}
EOF
}
write_prefab 0 1 Enemy; git add -A; git commit -qm base
git checkout -qb ours;   write_prefab 5 1 Enemy; git commit -qam "ours: move"
git checkout -q main;    write_prefab 0 2 Enemy; git commit -qam "theirs: scale"   # adjacent line
git checkout -q ours

echo "== control: plain text merge of the same three versions =="
git show main~0:Assets/Enemy.prefab > "$DIR/theirs.prefab"; git show main~1:Assets/Enemy.prefab > "$DIR/base.prefab"
cp Assets/Enemy.prefab "$DIR/ours.prefab"
if git merge-file -p "$DIR/ours.prefab" "$DIR/base.prefab" "$DIR/theirs.prefab" >/dev/null; then
  fail "control-did-not-conflict (test data broken)"
fi
echo "text merge: CONFLICT (expected)"

echo "== configure driver (local config of the scratch repo) =="
bash "$HERE/setup_unityyamlmerge.sh" --project "$DIR/repo"

echo "== merge main into ours with GIT_TRACE =="
set +e
GIT_TRACE="$DIR/trace.log" git merge --no-edit main; RC=$?
set -e
grep -E "run_command: .*UnityYAMLMerge" "$DIR/trace.log" | head -n 3 || true
grep -qE "run_command: .*UnityYAMLMerge" "$DIR/trace.log" || fail "driver-not-invoked (see $DIR/trace.log)"
[ $RC -eq 0 ] || fail "smart-merge-conflicted rc=$RC"
grep -q 'm_LocalPosition: {x: 5' Assets/Enemy.prefab || fail "lost-ours-change"
grep -q 'm_LocalScale: {x: 2' Assets/Enemy.prefab || fail "lost-theirs-change"
echo "smart merge: CLEAN, both changes kept"

echo "== real conflict (both sides change m_Name) must stay a conflict, no GUI fallback =="
git checkout -qb c1;  write_prefab 5 2 EnemyA; git commit -qam c1
git checkout -q ours; write_prefab 5 2 EnemyB; git commit -qam c2
set +e
GIT_TRACE="$DIR/trace.log" git merge --no-edit c1 >/dev/null 2>&1; RC2=$?
set -e
[ $RC2 -ne 0 ] || fail "real-conflict-was-auto-resolved"
git ls-files -u | grep -q Enemy.prefab || fail "conflict-not-recorded"
echo "real conflict: reported by git (rc=$RC2), resolve with: git checkout --ours|--theirs or git mergetool --tool=unityyamlmerge"
git merge --abort
echo "scratch: $DIR (trace: $DIR/trace.log)"
echo "RESULT: OK"
