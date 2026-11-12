#!/usr/bin/env bash
# scene_audit.sh - run Harness.Safety.SceneAudit in Unity batchmode (project must be CLOSED in the editor).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scene_audit.sh <projectPath> [build|all] [timeout_seconds]
  Runs -executeMethod Harness.Safety.SceneAudit.RunBatch (SceneAudit.cs must be in the project).
  build = enabled Build Settings scenes (default), all = every scene under Assets/. Prefabs: all under Assets/.
  Editor: from ProjectSettings/ProjectVersion.txt, override with UNITY_PATH. Default timeout 600 s.
  Writes <project>/Logs/scene_audit.log and <project>/Logs/scene_audit.json.
  Exit: 0 clean, 1 issues found, 2 audit crashed, 3 setup/usage error (incl. compile errors),
        4 project open in another Unity, 124 timeout (same 3/4/124 meaning as headless-ops' unity.sh).
  Last line: RESULT: OK ... | RESULT: FAIL <reason>
EOF
}
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi
if [[ $# -lt 1 ]]; then usage; exit 3; fi

PROJECT="$(cd "$1" && pwd)"
SCOPE="${2:-build}"
TIMEOUT="${3:-600}"
VER_FILE="$PROJECT/ProjectSettings/ProjectVersion.txt"
[[ -f "$VER_FILE" ]] || { echo "RESULT: FAIL not a Unity project: $PROJECT"; exit 3; }
VER="$(awk '/^m_EditorVersion:/ {print $2}' "$VER_FILE")"
UNITY="${UNITY_PATH:-/Applications/Unity/Hub/Editor/$VER/Unity.app/Contents/MacOS/Unity}"
[[ -x "$UNITY" ]] || { echo "RESULT: FAIL editor not found: $UNITY (set UNITY_PATH)"; exit 3; }

if pgrep -f "Unity.app/Contents/MacOS/Unity.*-projectPath ${PROJECT}( |$)" >/dev/null 2>&1 \
   || { [[ -f "$PROJECT/Temp/UnityLockfile" ]] && lsof "$PROJECT/Temp/UnityLockfile" >/dev/null 2>&1; }; then
  echo "RESULT: FAIL project is open in another Unity process; use execute_code with SceneAudit.RunToString instead"
  exit 4
fi

mkdir -p "$PROJECT/Logs"
LOG="$PROJECT/Logs/scene_audit.log"
REPORT="$PROJECT/Logs/scene_audit.json"
FLAG="$PROJECT/Logs/.scene_audit.timeout.$$"
rm -f "$LOG" "$REPORT" "$FLAG"

"$UNITY" -batchmode -nographics -projectPath "$PROJECT" -logFile "$LOG" \
  -executeMethod Harness.Safety.SceneAudit.RunBatch -auditScope "$SCOPE" -auditReport "$REPORT" </dev/null >/dev/null 2>&1 &
PID=$!
# Watchdog polls instead of one long sleep, and never holds our stdout (a background sleep that inherits
# stdout keeps tool calls/pipes open until it ends).
( i=0; while [[ $i -lt $TIMEOUT ]] && kill -0 "$PID" 2>/dev/null; do sleep 1; i=$((i+1)); done
  if kill -0 "$PID" 2>/dev/null; then touch "$FLAG"; kill -TERM "$PID" 2>/dev/null; sleep 10; kill -KILL "$PID" 2>/dev/null; fi ) </dev/null >/dev/null 2>&1 &
WD=$!
set +e
wait "$PID"; RC=$?
set -e
kill "$WD" 2>/dev/null || true
wait "$WD" 2>/dev/null || true
TIMED_OUT=0; if [[ -e "$FLAG" ]]; then TIMED_OUT=1; rm -f "$FLAG"; fi

grep -E "SceneAudit ISSUE" "$LOG" | sed 's/^/  /' | head -50 || true
if grep -qE "error CS[0-9]+" "$LOG"; then
  grep -E "error CS[0-9]+" "$LOG" | sort -u | head -10
  echo "RESULT: FAIL compile errors (see $LOG)"; exit 3
fi
LINE="$(grep -E "SceneAudit RESULT:" "$LOG" | tail -1 || true)"
if [[ $TIMED_OUT -eq 1 ]]; then echo "RESULT: FAIL timeout after ${TIMEOUT}s (see $LOG)"; exit 124; fi
if [[ $RC -ge 128 ]]; then echo "RESULT: FAIL Unity crashed (exit $RC) ${LINE:+after: ${LINE#*SceneAudit }} (see $LOG; rerun once)"; exit 2; fi
if [[ -z "$LINE" ]]; then echo "RESULT: FAIL no SceneAudit result (exit $RC; is SceneAudit.cs in an Editor folder? see $LOG)"; exit 3; fi
echo "${LINE#*SceneAudit }"
exit "$RC"
