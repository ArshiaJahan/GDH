#!/usr/bin/env bash
# Builds dist/GameDevWorkstation.app and dist/GameDevWorkstation.dmg for Apple Silicon.
# Signing: the same certificate every build, so macOS remembers "Always Allow" for the Keychain
# (an ad-hoc signature is a new code identity each build, and the Keychain asks again). The identity
# is $GDW_SIGN_IDENTITY, else an "Apple Development" certificate, else "GameDevWorkstation Local
# Signing" (scripts/setup_signing.sh makes it), else ad-hoc with a note.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
# Output folder (default dist/). scripts/release.sh builds into a staging folder instead and
# sets GDW_SKIP_DMG=1.
DIST="${GDW_DIST_DIR:-$ROOT/dist}"
TARGET=aarch64-apple-darwin

# rm -rf that survives Finder writing .DS_Store into a folder while it is being deleted.
rm_tree() {
  local i
  for i in 1 2 3 4 5; do
    rm -rf "$@" 2>/dev/null && return 0
    sleep 1
  done
  rm -rf "$@"
}

# GUI-launched shells and fresh terminals may miss Homebrew/cargo paths.
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

echo "==> Checking prerequisites"
missing=()
[[ "$(uname -s)" == "Darwin" ]] || { echo "This script builds the macOS app; run it on your Mac."; exit 1; }
xcode-select -p >/dev/null 2>&1 || missing+=("Xcode Command Line Tools — run: xcode-select --install")
command -v cargo >/dev/null 2>&1 || missing+=("Rust — run: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
if command -v node >/dev/null 2>&1; then
  node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || missing+=("Node 20 or newer (you have $(node -v)) — run: brew install node")
else
  missing+=("Node 20+ — run: brew install node")
fi
command -v npm >/dev/null 2>&1 || missing+=("npm (comes with Node) — run: brew install node")
command -v uv >/dev/null 2>&1 || missing+=("uv — run: curl -LsSf https://astral.sh/uv/install.sh | sh")
command -v git >/dev/null 2>&1 || missing+=("git — run: xcode-select --install")
if (( ${#missing[@]} )); then
  echo "Missing:"; printf '  • %s\n' "${missing[@]}"; exit 1
fi
if command -v rustup >/dev/null 2>&1 && ! rustup target list --installed | grep -q "$TARGET"; then
  echo "    adding Rust target $TARGET"; rustup target add "$TARGET"
fi
command -v codex >/dev/null 2>&1 && echo "    Codex CLI: found" || echo "    Codex CLI: not installed (optional; the Codex CLI harness will show as unavailable)"
[[ "$(uname -m)" == "arm64" ]] || echo "    note: building on $(uname -m); the app targets $TARGET"

echo "==> Frontend"
# npm ci deletes node_modules first; Finder/Spotlight writing into it can make that fail once (ENOTEMPTY).
( cd frontend && { npm ci --no-audit --no-fund || { sleep 2; npm ci --no-audit --no-fund; }; } && npm run build )

echo "==> Backend (PyInstaller, arm64, onedir)"
uv sync --group dev --extra agent-sdk
uv run python scripts/version.py build-info >/dev/null  # version, commit, build time for About
rm_tree build/pyinstaller/backend  # PyInstaller's own clean-up fails if Finder touches the folder
uv run pyinstaller packaging/gamedevworkstation.spec --noconfirm --distpath build/pyinstaller --workpath build/pyi-work --log-level WARN
rm_tree src-tauri/resources/backend
mkdir -p src-tauri/resources
cp -R build/pyinstaller/backend src-tauri/resources/backend
touch src-tauri/resources/backend/.keep  # tracked placeholder; the rm above deletes it

echo "==> Desktop shell (Tauri)"
( cd "$ROOT" && npx --prefix frontend tauri build --target "$TARGET" --bundles app )

BUNDLE="src-tauri/target/$TARGET/release/bundle"
rm_tree "$DIST/GameDevWorkstation.app" "$DIST/GameDevWorkstation.dmg"
mkdir -p "$DIST"
cp -R "$BUNDLE/macos/GameDevWorkstation.app" "$DIST/GameDevWorkstation.app"

# The SHA-1 of the first valid code-signing identity whose name contains $1 (empty if none).
identity() { security find-identity -v -p codesigning 2>/dev/null | awk -v n="$1" 'index($0, "\"" n) { print $2; exit }'; }
SIGN="${GDW_SIGN_IDENTITY:-}"
[[ -n "$SIGN" ]] || SIGN="$(identity "Apple Development")"
[[ -n "$SIGN" ]] || SIGN="$(identity "GameDevWorkstation Local Signing")"
xattr -cr "$DIST/GameDevWorkstation.app"
if [[ -n "$SIGN" ]]; then
  echo "==> Signing ($(security find-identity -v -p codesigning | awk -v h="$SIGN" '$2 == h { $1 = $2 = ""; sub(/^  /, ""); print; exit }'))"
  # --deep doesn't reach code under Contents/Resources: sign the bundled backend (the process that
  # reads the Keychain) and its libraries first, inside out. The backend gets a fixed identifier:
  # PyInstaller's own ad-hoc one changes every build, and the Keychain remembers identifier + certificate.
  BACKEND_DIR="$DIST/GameDevWorkstation.app/Contents/Resources/backend"
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then codesign --force --sign "$SIGN" "$f" 2>/dev/null; fi
  done < <(find "$BACKEND_DIR" -type f ! -name gamedevworkstation-backend -print0)
  codesign --force --sign "$SIGN" -i dev.local.gamedevworkstation.backend "$BACKEND_DIR/gamedevworkstation-backend"
  codesign --force --deep --sign "$SIGN" "$DIST/GameDevWorkstation.app"
  # --deep re-signs nested bundles only; check the backend kept its identifier and a certificate
  # (not an ad-hoc cdhash). An Apple-issued identity puts "anchor apple generic" between the two.
  DR="$(codesign -dr - "$BACKEND_DIR/gamedevworkstation-backend" 2>&1)"
  [[ "$DR" == *'identifier "dev.local.gamedevworkstation.backend"'* && "$DR" == *" certificate "* && "$DR" != *cdhash* ]] \
    || { echo "The backend isn't signed with the stable identity." >&2; exit 1; }
elif [[ -n "${GDW_ALLOW_ADHOC:-}" ]]; then
  echo "==> Signing (ad-hoc, GDW_ALLOW_ADHOC: the Keychain will ask again for this build)"
  codesign --force --deep --sign - "$DIST/GameDevWorkstation.app"
else
  echo "No code-signing identity: run scripts/setup_signing.sh once (or set GDW_SIGN_IDENTITY)." >&2
  echo "An ad-hoc build is a new app to the Keychain, which asks for your password again; GDW_ALLOW_ADHOC=1 builds one anyway." >&2
  exit 1
fi
codesign --verify --deep --strict "$DIST/GameDevWorkstation.app" && echo "    signature OK"

if [[ -n "${GDW_SKIP_DMG:-}" ]]; then echo; echo "Built: $DIST/GameDevWorkstation.app"; exit 0; fi

echo "==> Disk image (from the signed app)"
STAGE="$(mktemp -d)"
cp -R "$DIST/GameDevWorkstation.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname GameDevWorkstation -srcfolder "$STAGE" -ov -format UDZO "$DIST/GameDevWorkstation.dmg" >/dev/null
rm -rf "$STAGE"

echo
echo "Built: $DIST/GameDevWorkstation.app"
echo "       $DIST/GameDevWorkstation.dmg"
