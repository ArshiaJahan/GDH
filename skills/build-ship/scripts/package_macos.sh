#!/usr/bin/env bash
# package_macos.sh: ad-hoc sign a Unity macOS .app for local/testing distribution and zip (and optionally dmg) it.
# Not notarized: other Macs will show a Gatekeeper warning; real distribution needs a Developer ID + notarytool.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: package_macos.sh <Game.app> [--name BASENAME] [--dmg] [--no-sign]
  Clears extended attributes (xattr -cr), ad-hoc signs (codesign --force --deep --sign -), verifies the signature,
  then writes <BASENAME>.zip (ditto, keeps the bundle intact) next to the .app, and <BASENAME>.dmg with --dmg.
  BASENAME defaults to <AppName>-<CFBundleShortVersionString>-macos.
Prints RESULT: OK package <files> | RESULT: FAIL <reason>. Exit 0 ok, 1 failed, 3 usage.
EOF
}
result() { echo "RESULT: $2 $3"; exit "$1"; }

[ $# -ge 1 ] || { usage; exit 3; }
case "$1" in -h|--help) usage; exit 0 ;; esac
APP="$1"; shift
NAME=""; DMG=0; SIGN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="${2:?}"; shift 2 ;;
    --dmg) DMG=1; shift ;;
    --no-sign) SIGN=0; shift ;;
    *) result 3 FAIL "usage unknown option $1" ;;
  esac
done
[ -d "$APP" ] && [ -f "$APP/Contents/Info.plist" ] || result 3 FAIL "usage not an .app bundle: $APP"
APP="$(cd "$APP" && pwd)"
DIR="$(dirname "$APP")"; APPNAME="$(basename "$APP" .app)"
VER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null || echo 0.0.0)"
[ -n "$NAME" ] || NAME="$(echo "$APPNAME" | tr ' ' '-')-$VER-macos"

xattr -cr "$APP"
if [ "$SIGN" = 1 ]; then
  chmod -R a+xr "$APP"
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || result 1 FAIL "codesign ad-hoc signing failed"
  codesign --verify --deep --strict "$APP" 2>&1 || result 1 FAIL "codesign --verify failed"
fi
ZIP="$DIR/$NAME.zip"
rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP" || result 1 FAIL "ditto zip failed"
OUTS="$ZIP"
if [ "$DMG" = 1 ]; then
  DMGF="$DIR/$NAME.dmg"
  rm -f "$DMGF"
  hdiutil create -quiet -volname "$APPNAME" -srcfolder "$APP" -ov -format UDZO "$DMGF" || result 1 FAIL "hdiutil create failed"
  OUTS="$OUTS $DMGF"
fi
shasum -a 256 $OUTS
result 0 OK "package $OUTS"
