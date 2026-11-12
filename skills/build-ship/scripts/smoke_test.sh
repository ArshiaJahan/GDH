#!/usr/bin/env bash
# smoke_test.sh: launch a built macOS (or Windows/Linux, untested) player with -smoketest, wait for it to quit,
# and check the result file written by Harness.Ship.SmokeTest. See ../SKILL.md.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: smoke_test.sh <Game.app | player binary> [options] [-- extra player args]
  --seconds N       seconds the player runs the first scene before judging (default 5)
  --timeout S       watchdog for the whole run (default seconds+60)
  --out FILE        result file (default <app dir>/smoke-result.txt)
  --log FILE        player log (default <app dir>/smoke-player.log)
  --scene NAME      load this build scene instead of the first one
  --allow-errors    Debug.LogError does not fail the run (exceptions and asserts still do)
  --windowed WxH    window size (default 960x540, never fullscreen)
  --headless        add -batchmode -nographics (no window, no rendering; for CI and SSH sessions)
  -h, --help
Needs Harness.Ship.SmokeTest (build-ship/templates/Runtime) compiled into the build.
Prints RESULT: OK smoke ... | RESULT: FAIL <reason>.  Exit: 0 ok, 1 smoke failed, 3 setup, 124 timeout.
EOF
}

result() { echo "RESULT: $2 $3"; exit "$1"; }

[ $# -ge 1 ] || { usage; exit 3; }
case "$1" in -h|--help) usage; exit 0 ;; esac
TARGET="$1"; shift
SECONDS_RUN=5; TIMEOUT=""; OUT=""; PLOG=""; SCENE=""; ALLOW=0; SIZE="960x540"; HEADLESS=0; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --seconds) SECONDS_RUN="${2:?}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?}"; shift 2 ;;
    --out) OUT="${2:?}"; shift 2 ;;
    --log) PLOG="${2:?}"; shift 2 ;;
    --scene) SCENE="${2:?}"; shift 2 ;;
    --allow-errors) ALLOW=1; shift ;;
    --windowed) SIZE="${2:?}"; shift 2 ;;
    --headless) HEADLESS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; EXTRA=("$@"); break ;;
    *) result 3 FAIL "usage unknown option $1" ;;
  esac
done
[ -e "$TARGET" ] || result 3 FAIL "setup not found: $TARGET"
TARGET="$(cd "$(dirname "$TARGET")" && pwd)/$(basename "$TARGET")"

if [ -d "$TARGET" ] && [ -f "$TARGET/Contents/Info.plist" ]; then
  EXE="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$TARGET/Contents/Info.plist" 2>/dev/null || true)"
  BIN="$TARGET/Contents/MacOS/$EXE"
  if xattr -p com.apple.quarantine "$TARGET" >/dev/null 2>&1; then
    echo "warning: $TARGET is quarantined (downloaded/copied); if it will not start run: xattr -dr com.apple.quarantine \"$TARGET\"" >&2
  fi
else
  BIN="$TARGET"
fi
[ -x "$BIN" ] || result 3 FAIL "setup player binary not executable: $BIN"

BASE="$(dirname "$TARGET")"
[ -n "$OUT" ] || OUT="$BASE/smoke-result.txt"
[ -n "$PLOG" ] || PLOG="$BASE/smoke-player.log"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
case "$PLOG" in /*) ;; *) PLOG="$PWD/$PLOG" ;; esac
[ -n "$TIMEOUT" ] || TIMEOUT=$(( ${SECONDS_RUN%.*} + 60 ))
rm -f "$OUT" "$PLOG"

W="${SIZE%x*}"; H="${SIZE#*x}"
ARGS=(-smoketest -smokeSeconds "$SECONDS_RUN" -smokeOut "$OUT" -logFile "$PLOG"
      -screen-fullscreen 0 -screen-width "$W" -screen-height "$H")
[ -n "$SCENE" ] && ARGS+=(-smokeScene "$SCENE")
[ "$ALLOW" = 1 ] && ARGS+=(-smokeAllowErrors)
[ "$HEADLESS" = 1 ] && ARGS+=(-batchmode -nographics)

echo "smoke_test.sh: $BIN ${ARGS[*]} ${EXTRA[*]+${EXTRA[*]}}" >&2
FLAG="$(mktemp -t smoke-timeout.XXXXXX)"; rm -f "$FLAG"
set +e
"$BIN" "${ARGS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} >/dev/null 2>&1 &
PID=$!
( set +e; trap 'kill $s 2>/dev/null; exit 0' TERM
  sleep "$TIMEOUT" & s=$!; wait $s
  if kill -0 "$PID" 2>/dev/null; then touch "$FLAG"; kill -TERM "$PID"; sleep 5; kill -KILL "$PID" 2>/dev/null; fi
) >/dev/null 2>&1 &
WD=$!
wait "$PID"; RC=$?
kill "$WD" 2>/dev/null; wait "$WD" 2>/dev/null
set -e

if [ -e "$FLAG" ]; then
  rm -f "$FLAG"
  echo "--- last lines of $PLOG" >&2; tail -15 "$PLOG" >&2 2>/dev/null || echo "(no player log)" >&2
  if grep -q '\[SMOKE\] start' "$PLOG" 2>/dev/null; then where="after [SMOKE] start"; else where="before the smoke runner started"; fi
  result 124 FAIL "timeout player still running after ${TIMEOUT}s, stalled $where (log $PLOG; retry once, or --headless)"
fi
if [ ! -f "$OUT" ]; then
  grep -E 'Exception|\[SMOKE\]' "$PLOG" 2>/dev/null | head -10 || true
  result 1 FAIL "no result file (exit $RC; is Harness.Ship.SmokeTest in the build? log $PLOG)"
fi
cat "$OUT"
VERDICT="$(head -1 "$OUT")"
STATS="$(grep -E '^(frames|fps|exceptions|errors)=' "$OUT" | tr '\n' ' ')"
if [ "$VERDICT" = "ok" ] && [ "$RC" -eq 0 ]; then
  result 0 OK "smoke $STATS(result $OUT)"
fi
result 1 FAIL "smoke '$VERDICT' exit $RC $STATS(result $OUT, log $PLOG)"
