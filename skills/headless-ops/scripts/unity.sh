#!/usr/bin/env bash
# unity.sh: run Unity 6000.3 in batchmode on a project with a watchdog, parse the log, and print one result line.
# See ../SKILL.md and ../references/cli-reference.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
usage: unity.sh [common flags] <command> [args]

commands
  compile [--force]                       open the project headless, compile all scripts, report errors
                                          (--force: also request a clean recompile; needs HarnessCli in the project)
  test editmode|playmode [--filter X] [--category Y] [--assembly Z] [--results FILE] [--allow-empty]
                                          run tests (-runTests, never with -quit), summarise the NUnit XML
  import [paths...] [--force]             no paths: AssetDatabase.Refresh; paths (Assets/...): reimport them
                                          (--force: ImportAssetOptions.ForceUpdate). Needs HarnessCli.
  build <profile.asset|target> [--out PATH] [--dev] [--clean] [--scenes "a;b"]
                                          target: macos|windows|webgl|android|ios|linux, or a Build Profile
                                          asset path (Assets/...asset). Needs HarnessCli. Writes build-report.json.
  menu "<Path/To/Item>"                    run a menu item (EditorApplication.ExecuteMenuItem), then save assets.
                                          Needs HarnessCli (HarnessCli.MenuItem).
  screenshot --out FILE.png [--scene Assets/X.unity] [--camera NAME] [--cam-pos x,y,z] [--cam-rot x,y,z]
             [--fov F] [--width 1920] [--height 1080] [--time-of-day TEXT]
                                          render one PNG of a scene with the Editor closed (HarnessCli.Screenshot):
                                          default scene = first enabled build scene; a temporary camera unless
                                          --camera names one (and no --cam-pos/--cam-rot); the scene is never saved.
                                          Always runs WITH graphics (never -nographics). Needs HarnessCli version 3.
  exec <Ns.Class.Method> [unity args...] [--no-quit]
                                          run a static editor method with -quit; extra args go to Unity verbatim.
                                          --no-quit for methods that end with a deferred EditorApplication.Exit
                                          (automatic for Harness.Headless.HarnessCli.*; use it for Harness.Assets.*Batch,
                                          Harness.Safety.SceneAudit.RunBatch). Never pass -version.

common flags (anywhere before a literal --)
  --project DIR      Unity project root (default: $UNITY_PROJECT, else walk up from the current directory)
  --timeout SEC      watchdog; default compile 900, import 1800, test 1800, build 3600, exec 1800, menu 900, screenshot 900
  --log FILE         Unity log file (default <project>/Logs/harness/<command>-<timestamp>.log)
  --unity PATH       editor binary (default: $UNITY_PATH, else from ProjectSettings/ProjectVersion.txt)
  --accept-apiupdate pass -accept-apiupdate (lets the API updater rewrite obsolete API in your scripts)
  --graphics         do not pass -nographics (playmode tests and screenshot never get -nographics)
  -h, --help         this text

last line printed:  RESULT: OK <summary>   or   RESULT: FAIL <reason>
exit codes: 0 ok · 1 failure (compile errors, build/import/exec failed, Unity crashed) · 2 tests failed
            3 setup or usage error · 4 project is open in another Unity · 124 watchdog timeout
EOF
}

result() { # result <exit code> <OK|FAIL> <text>
  echo "RESULT: $2 $3"
  exit "$1"
}

# ---------- argument parsing ----------
PROJECT="${UNITY_PROJECT:-}"; TIMEOUT=""; LOG=""; UNITY_BIN="${UNITY_PATH:-}"; APIUPDATE=0; GRAPHICS=0
POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --project) PROJECT="${2:?--project needs a value}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout needs a value}"; shift 2 ;;
    --log) LOG="${2:?--log needs a value}"; shift 2 ;;
    --unity) UNITY_BIN="${2:?--unity needs a value}"; shift 2 ;;
    --accept-apiupdate) APIUPDATE=1; shift ;;
    --graphics) GRAPHICS=1; shift ;;
    --) shift; POS+=("$@"); break ;;
    *) POS+=("$1"); shift ;;
  esac
done
[ ${#POS[@]} -ge 1 ] || { usage; exit 3; }
CMD="${POS[0]}"
ARGS=("${POS[@]:1}")

case "$CMD" in
  compile|test|import|build|exec|menu|screenshot) ;;
  *) echo "unknown command: $CMD" >&2; usage >&2; result 3 FAIL "usage unknown command $CMD" ;;
esac

# ---------- project and editor ----------
if [ -z "$PROJECT" ]; then
  d="$PWD"
  while [ "$d" != "/" ] && [ ! -f "$d/ProjectSettings/ProjectVersion.txt" ]; do d="$(dirname "$d")"; done
  [ -f "$d/ProjectSettings/ProjectVersion.txt" ] || result 3 FAIL "setup no Unity project found (use --project)"
  PROJECT="$d"
fi
[ -f "$PROJECT/ProjectSettings/ProjectVersion.txt" ] || result 3 FAIL "setup not a Unity project: $PROJECT"
ROOT="$(cd "$PROJECT" && pwd)"
ROOT_REAL="$(cd "$PROJECT" && pwd -P)"
VERSION="$(sed -n 's/^m_EditorVersion: *//p' "$ROOT/ProjectSettings/ProjectVersion.txt" | tr -d '\r')"
if [ -z "$UNITY_BIN" ]; then
  UNITY_BIN="/Applications/Unity/Hub/Editor/$VERSION/Unity.app/Contents/MacOS/Unity"
fi
if [ ! -x "$UNITY_BIN" ]; then
  echo "Unity $VERSION not found at $UNITY_BIN. Installed: $(ls /Applications/Unity/Hub/Editor 2>/dev/null | tr '\n' ' ')" >&2
  result 3 FAIL "setup editor $VERSION not installed (set UNITY_PATH)"
fi

# Refuse when the project is open: batchmode cannot open a project an editor already has open.
regex_escape() { printf '%s' "$1" | sed -e 's/[][\.^$*+?(){}|]/\\&/g'; }
open_pid=""
for p in "$ROOT" "$ROOT_REAL"; do
  open_pid="$(pgrep -f "Unity\.app/Contents/MacOS/Unity.*-[pP]roject[pP]ath[= ]$(regex_escape "$p")/?( |\$)" 2>/dev/null | head -1 || true)"
  [ -n "$open_pid" ] && break
done
if [ -z "$open_pid" ] && [ -e "$ROOT/Temp/UnityLockfile" ]; then
  open_pid="$(lsof -t "$ROOT/Temp/UnityLockfile" 2>/dev/null | head -1 || true)"
fi
if [ -n "$open_pid" ]; then
  echo "The project is open in Unity (pid $open_pid). Close that editor, or drive it through MCP instead." >&2
  result 4 FAIL "project-open pid $open_pid"
fi

LOGDIR="$ROOT/Logs/harness"
mkdir -p "$LOGDIR"
TS="$(date +%Y%m%d-%H%M%S)"
[ -n "$LOG" ] || LOG="$LOGDIR/$CMD-$TS.log"
mkdir -p "$(dirname "$LOG")"
case "$LOG" in /*) ;; *) LOG="$PWD/$LOG" ;; esac
rm -f "$LOG"

has_harness_cli() { grep -rqs --include='*.cs' 'class HarnessCli' "$ROOT/Assets" "$ROOT/Packages" 2>/dev/null; }
need_harness_cli() {
  has_harness_cli || result 3 FAIL "setup HarnessCli.cs missing: copy headless-ops/templates/Editor into Assets/Harness/Headless/Editor"
}

# ---------- run with watchdog ----------
TIMED_OUT=0
run_unity() { # run_unity <timeout> args...
  local tmo="$1"; shift
  local flag="$LOGDIR/.timeout-$$"
  rm -f "$flag"
  echo "unity.sh: $UNITY_BIN -batchmode -projectPath $ROOT -logFile $LOG $*" >&2
  set +e
  "$UNITY_BIN" -batchmode -projectPath "$ROOT" -logFile "$LOG" "$@" >/dev/null 2>&1 &
  local upid=$!
  # Watchdog: detached from stdout so a lingering sleep never holds the caller's pipe open.
  ( set +e; trap 'kill $s 2>/dev/null; exit 0' TERM
    sleep "$tmo" & s=$!; wait $s
    if kill -0 "$upid" 2>/dev/null; then
      touch "$flag"
      pkill -TERM -P "$upid" 2>/dev/null; kill -TERM "$upid" 2>/dev/null
      sleep 10
      pkill -KILL -P "$upid" 2>/dev/null; kill -KILL "$upid" 2>/dev/null
    fi ) >/dev/null 2>&1 &
  local wpid=$!
  wait "$upid"; UNITY_RC=$?
  kill "$wpid" 2>/dev/null; wait "$wpid" 2>/dev/null
  set -e
  if [ -e "$flag" ]; then TIMED_OUT=1; rm -f "$flag"; fi
  [ -f "$LOG" ] && cp "$LOG" "$LOGDIR/last.log" 2>/dev/null || true
  echo "unity.sh: exit=$UNITY_RC log=$LOG" >&2
}

# Print compiler errors and abort reasons; set N_ERR.
N_ERR=0
report_log() {
  [ -f "$LOG" ] || { echo "(no log written)"; return; }
  local errs
  errs="$(grep -E 'error CS[0-9]+' "$LOG" | sed -E 's/^.*[[:space:]]([^[:space:]]+\.cs\([0-9]+,[0-9]+\): error)/\1/' | sort -u || true)"
  if [ -n "$errs" ]; then
    N_ERR="$(printf '%s\n' "$errs" | wc -l | tr -d ' ')"
    printf '%s\n' "$errs" | head -40
    if [ "$N_ERR" -gt 40 ]; then echo "... ($N_ERR error lines, see $LOG)"; fi
  fi
  grep -F '[HARNESS]' "$LOG" | sed 's/^.*\[HARNESS\] /[HARNESS] /' | awk '!seen[$0]++' | head -60 || true
  grep -E -A1 'Aborting batchmode due to failure:' "$LOG" | head -4 || true
  grep -E "executeMethod class '.*' could not be found|executeMethod method .* could not be found|Scripts have compiler errors\.|Multiple Unity instances cannot open the same project" "$LOG" | sort -u | head -5 || true
}

finish_generic() { # finish_generic <label>
  local label="$1"
  report_log
  [ "$TIMED_OUT" = 1 ] && result 124 FAIL "timeout $label after ${TIMEOUT}s (log $LOG)"
  [ -s "$LOG" ] || result 1 FAIL "$label no log written, Unity exit $UNITY_RC (did an arg like -version make Unity exit early?)"
  if [ "$N_ERR" -gt 0 ]; then result 1 FAIL "compile-errors $N_ERR ($label, log $LOG)"; fi
  if [ "$UNITY_RC" -ne 0 ]; then result 1 FAIL "$label exit $UNITY_RC (log $LOG)"; fi
}

NG=(-nographics); [ "$GRAPHICS" = 1 ] && NG=()
API=(); [ "$APIUPDATE" = 1 ] && API=(-accept-apiupdate)

# ---------- commands ----------
case "$CMD" in
compile)
  : "${TIMEOUT:=900}"
  FORCE=0
  for a in ${ARGS[@]+"${ARGS[@]}"}; do
    case "$a" in --force) FORCE=1 ;; *) result 3 FAIL "usage compile: unknown arg $a" ;; esac
  done
  if has_harness_cli; then
    EXTRA=(-executeMethod Harness.Headless.HarnessCli.Compile)
    [ "$FORCE" = 1 ] && EXTRA+=(-forceRecompile)
  else
    [ "$FORCE" = 1 ] && need_harness_cli
    EXTRA=(-quit)   # plain open + compile; Unity exits 1 on compiler errors
  fi
  run_unity "$TIMEOUT" ${NG[@]+"${NG[@]}"} ${API[@]+"${API[@]}"} "${EXTRA[@]}"
  finish_generic compile
  WARN="$( (grep -E 'warning CS[0-9]+' "$LOG" || true) | sort -u | wc -l | tr -d ' ')"
  result 0 OK "compile 0 errors, $WARN warning lines (log $LOG)"
  ;;

test)
  : "${TIMEOUT:=1800}"
  [ ${#ARGS[@]} -ge 1 ] || result 3 FAIL "usage test editmode|playmode"
  case "$(echo "${ARGS[0]}" | tr '[:upper:]' '[:lower:]')" in
    editmode|edit) PLAT=EditMode ;;
    playmode|play) PLAT=PlayMode; NG=() ;;   # PlayMode tests may need a graphics device
    *) result 3 FAIL "usage test: platform must be editmode or playmode" ;;
  esac
  FILTER=""; CATEGORY=""; ASSEMBLY=""; RESULTS=""; ALLOW_EMPTY=0
  set -- ${ARGS[@]+"${ARGS[@]:1}"}
  while [ $# -gt 0 ]; do
    case "$1" in
      --filter) FILTER="${2:?}"; shift 2 ;;
      --category) CATEGORY="${2:?}"; shift 2 ;;
      --assembly) ASSEMBLY="${2:?}"; shift 2 ;;
      --results) RESULTS="${2:?}"; shift 2 ;;
      --allow-empty) ALLOW_EMPTY=1; shift ;;
      *) result 3 FAIL "usage test: unknown arg $1" ;;
    esac
  done
  # A project without the test framework makes -runTests hang forever.
  grep -q '"com.unity.test-framework"' "$ROOT/Packages/manifest.json" 2>/dev/null \
    || result 3 FAIL "setup com.unity.test-framework missing from Packages/manifest.json (-runTests would hang)"
  [ -n "$RESULTS" ] || RESULTS="$LOGDIR/tests-$PLAT-$TS.xml"
  case "$RESULTS" in /*) ;; *) RESULTS="$PWD/$RESULTS" ;; esac
  mkdir -p "$(dirname "$RESULTS")"
  rm -f "$RESULTS"
  T=(-runTests -testPlatform "$PLAT" -testResults "$RESULTS")   # never -quit with -runTests
  [ -n "$FILTER" ] && T+=(-testFilter "$FILTER")
  [ -n "$CATEGORY" ] && T+=(-testCategory "$CATEGORY")
  [ -n "$ASSEMBLY" ] && T+=(-assemblyNames "$ASSEMBLY")
  run_unity "$TIMEOUT" ${NG[@]+"${NG[@]}"} ${API[@]+"${API[@]}"} "${T[@]}"
  report_log
  [ "$TIMED_OUT" = 1 ] && result 124 FAIL "timeout tests after ${TIMEOUT}s (log $LOG)"
  if [ ! -s "$RESULTS" ]; then
    [ "$N_ERR" -gt 0 ] && result 1 FAIL "compile-errors $N_ERR (no test results, log $LOG)"
    result 1 FAIL "no test results written, Unity exit $UNITY_RC (log $LOG)"
  fi
  grep -E 'Test run completed\. Exiting with code' "$LOG" | tail -1 || true
  set +e
  SUMARGS=("$RESULTS"); [ "$ALLOW_EMPTY" = 1 ] && SUMARGS+=(--allow-empty)
  SUMMARY="$(python3 "$SCRIPT_DIR/test_summary.py" "${SUMARGS[@]}")"
  SRC=$?
  set -e
  printf '%s\n' "$SUMMARY"
  LINE="$(printf '%s\n' "$SUMMARY" | grep -E '^tests: ' | head -1 | sed 's/^tests: //')"
  case "$SRC" in
    0) result 0 OK "tests $PLAT $LINE (xml $RESULTS)" ;;
    2) result 2 FAIL "tests $PLAT $LINE (xml $RESULTS)" ;;
    *) result 1 FAIL "tests $PLAT unreadable or empty results: $LINE (xml $RESULTS)" ;;
  esac
  ;;

import)
  : "${TIMEOUT:=1800}"
  need_harness_cli
  PATHS=(); FORCE=0
  for a in ${ARGS[@]+"${ARGS[@]}"}; do
    case "$a" in --force) FORCE=1 ;; -*) result 3 FAIL "usage import: unknown arg $a" ;; *) PATHS+=("$a") ;; esac
  done
  EXTRA=(-executeMethod Harness.Headless.HarnessCli.ImportAssets)
  if [ ${#PATHS[@]} -gt 0 ]; then
    joined="$(printf '%s;' "${PATHS[@]}")"; EXTRA+=(-importPaths "${joined%;}")
  fi
  [ "$FORCE" = 1 ] && EXTRA+=(-forceReimport)
  run_unity "$TIMEOUT" ${NG[@]+"${NG[@]}"} ${API[@]+"${API[@]}"} "${EXTRA[@]}"
  finish_generic import
  result 0 OK "import $(grep -F '[HARNESS] IMPORT' "$LOG" | tail -1 | sed 's/^.*\[HARNESS\] IMPORT //') (log $LOG)"
  ;;

build)
  : "${TIMEOUT:=3600}"
  need_harness_cli
  [ ${#ARGS[@]} -ge 1 ] || result 3 FAIL "usage build <profile.asset|target>"
  WHAT="${ARGS[0]}"; OUT=""; DEV=0; CLEAN=0; SCENES=""
  set -- ${ARGS[@]+"${ARGS[@]:1}"}
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) OUT="${2:?}"; shift 2 ;;
      --dev) DEV=1; shift ;;
      --clean) CLEAN=1; shift ;;
      --scenes) SCENES="${2:?}"; shift 2 ;;
      *) result 3 FAIL "usage build: unknown arg $1" ;;
    esac
  done
  B=(-executeMethod Harness.Headless.HarnessCli.Build)
  case "$WHAT" in
    *.asset)
      case "$WHAT" in Assets/*) ;; *) result 3 FAIL "usage build profile must be an Assets/... path (profiles under Packages/ fail from the CLI)" ;; esac
      [ -f "$ROOT/$WHAT" ] || result 3 FAIL "setup build profile not found: $WHAT"
      B+=(-activeBuildProfile "$WHAT" -buildProfile "$WHAT"); PLATDIR="$(basename "$WHAT" .asset | tr '[:upper:] ' '[:lower:]-')" ;;
    macos|mac|osx|osxuniversal|StandaloneOSX) B+=(-buildTarget osxuniversal); PLATDIR=macos ;;
    windows|win|win64|StandaloneWindows64)   B+=(-buildTarget win64); PLATDIR=windows ;;
    webgl|web|WebGL)                         B+=(-buildTarget webgl); PLATDIR=webgl ;;
    android|Android)                         B+=(-buildTarget android); PLATDIR=android ;;
    ios|iOS)                                 B+=(-buildTarget ios); PLATDIR=ios ;;
    linux|linux64|StandaloneLinux64)         B+=(-buildTarget linux64); PLATDIR=linux ;;
    *) result 3 FAIL "usage build: unknown target $WHAT (macos|windows|webgl|android|ios|linux|Assets/...asset)" ;;
  esac
  [ -n "$OUT" ] || OUT="$ROOT/Builds/$PLATDIR"
  case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
  B+=(-out "$OUT")
  [ "$DEV" = 1 ] && B+=(-dev)
  [ "$CLEAN" = 1 ] && B+=(-cleanBuild)
  [ -n "$SCENES" ] && B+=(-scenes "$SCENES")
  run_unity "$TIMEOUT" ${NG[@]+"${NG[@]}"} ${API[@]+"${API[@]}"} "${B[@]}"
  report_log
  [ "$TIMED_OUT" = 1 ] && result 124 FAIL "timeout build after ${TIMEOUT}s (log $LOG)"
  REPORT="$(grep -F '[HARNESS] REPORT ' "$LOG" 2>/dev/null | tail -1 | sed 's/^.*\[HARNESS\] REPORT //' || true)"
  if [ -n "$REPORT" ] && [ -f "$REPORT" ]; then
    SUM="$(python3 - "$REPORT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
print("%s %s %s %.1fMB %ss errors=%s" % (r.get("result"), r.get("platform"), r.get("outputPath"),
      (r.get("totalSize") or 0) / 1048576.0, r.get("totalSeconds"), r.get("totalErrors")))
for m in (r.get("errorMessages") or [])[:20]:
    print("  build error: " + m.splitlines()[0] if m else "")
PY
)"
    printf '%s\n' "$SUM"
    FIRST="$(printf '%s\n' "$SUM" | head -1)"
    case "$FIRST" in
      Succeeded*) [ "$UNITY_RC" -eq 0 ] && result 0 OK "build $FIRST (report $REPORT)" ;;
    esac
    result 1 FAIL "build $FIRST exit $UNITY_RC (report $REPORT, log $LOG)"
  fi
  [ "$N_ERR" -gt 0 ] && result 1 FAIL "compile-errors $N_ERR (build not started, log $LOG)"
  result 1 FAIL "build no report written, Unity exit $UNITY_RC (log $LOG)"
  ;;

menu)
  : "${TIMEOUT:=900}"
  need_harness_cli
  [ ${#ARGS[@]} -eq 1 ] || result 3 FAIL "usage menu \"Path/To/Item\" (one quoted menu path)"
  ITEM="${ARGS[0]}"
  case "$ITEM" in */*) ;; *) result 3 FAIL "usage menu: not a menu path: $ITEM" ;; esac
  run_unity "$TIMEOUT" ${NG[@]+"${NG[@]}"} ${API[@]+"${API[@]}"} -executeMethod Harness.Headless.HarnessCli.MenuItem -menu "$ITEM"
  finish_generic "menu $ITEM"
  grep -qF '[HARNESS] MENU OK' "$LOG" 2>/dev/null || result 1 FAIL "menu $ITEM did not report MENU OK (log $LOG)"
  result 0 OK "menu $ITEM (log $LOG)"
  ;;

screenshot)
  : "${TIMEOUT:=900}"
  need_harness_cli
  grep -rqs --include='HarnessCli.cs' 'public static void Screenshot()' "$ROOT/Assets" "$ROOT/Packages" 2>/dev/null \
    || result 3 FAIL "setup HarnessCli.cs has no Screenshot entry point (harness-version 3): update Assets/Harness/Headless/Editor"
  OUT=""; S=(-executeMethod Harness.Headless.HarnessCli.Screenshot)
  set -- ${ARGS[@]+"${ARGS[@]}"}
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) OUT="${2:?--out needs a value}"; shift 2 ;;
      --scene) S+=(-scene "${2:?}"); shift 2 ;;
      --camera) S+=(-camera "${2:?}"); shift 2 ;;
      --cam-pos) S+=(-camPos "${2:?}"); shift 2 ;;
      --cam-rot) S+=(-camRot "${2:?}"); shift 2 ;;
      --fov) S+=(-camFov "${2:?}"); shift 2 ;;
      --width) S+=(-width "${2:?}"); shift 2 ;;
      --height) S+=(-height "${2:?}"); shift 2 ;;
      --time-of-day) S+=(-timeOfDay "${2:?}"); shift 2 ;;
      *) result 3 FAIL "usage screenshot: unknown arg $1" ;;
    esac
  done
  [ -n "$OUT" ] || result 3 FAIL "usage screenshot --out FILE.png"
  case "$OUT" in *.png|*.PNG) ;; *) result 3 FAIL "usage screenshot: --out must end in .png" ;; esac
  case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
  [ ! -e "$OUT" ] && [ ! -L "$OUT" ] || result 3 FAIL "screenshot: refusing to overwrite existing --out file $OUT"
  mkdir -p "$(dirname "$OUT")"
  S+=(-out "$OUT")
  # Rendering needs a graphics device: no -nographics here, whatever --graphics says. No -quit (deferred Exit).
  run_unity "$TIMEOUT" ${API[@]+"${API[@]}"} "${S[@]}"
  finish_generic screenshot
  LINE="$(grep -F '[HARNESS] SHOT OK' "$LOG" 2>/dev/null | tail -1 | sed 's/^.*\[HARNESS\] SHOT OK //' || true)"
  [ -n "$LINE" ] && [ -s "$OUT" ] || result 1 FAIL "screenshot did not report SHOT OK or wrote no file (log $LOG)"
  echo "ARTIFACT: $OUT"
  result 0 OK "screenshot $LINE (log $LOG)"
  ;;

exec)
  : "${TIMEOUT:=1800}"
  [ ${#ARGS[@]} -ge 1 ] || result 3 FAIL "usage exec <Ns.Class.Method> [unity args]"
  METHOD="${ARGS[0]}"; QUIT=(-quit); PASS=()
  # HarnessCli entry points end with a deferred EditorApplication.Exit; -quit would end the run first with exit 0.
  case "$METHOD" in Harness.Headless.HarnessCli.*) QUIT=() ;; esac
  for a in ${ARGS[@]+"${ARGS[@]:1}"}; do
    case "$a" in --no-quit) QUIT=() ;; *) PASS+=("$a") ;; esac
  done
  run_unity "$TIMEOUT" ${NG[@]+"${NG[@]}"} ${API[@]+"${API[@]}"} ${QUIT[@]+"${QUIT[@]}"} -executeMethod "$METHOD" ${PASS[@]+"${PASS[@]}"}
  finish_generic "exec $METHOD"
  result 0 OK "exec $METHOD (log $LOG)"
  ;;
esac
